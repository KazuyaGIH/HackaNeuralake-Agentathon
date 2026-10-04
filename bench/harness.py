r"""Harness do benchmark A x B x C (Agentathon) — somente NeuraLake, modelo fixo `text` nas tarefas de geracao.

Uso (PowerShell, na pasta do repositorio):
    .venv\Scripts\python.exe <bench>\harness.py pilot            # 1 desafio x A,B,C (teste pequeno)
    .venv\Scripts\python.exe <bench>\harness.py main             # 6 desafios x 3 configs x 3 repeticoes (intercaladas)
    .venv\Scripts\python.exe <bench>\harness.py budget <cap_json> # rodada complementar B x C sob o mesmo teto

Instrumentacao: cada tentativa HTTP de qualquer configuracao (inclusive falhas, reparos e retries) passa por um
wrapper em OpenAICompatAdapter.generate que grava o `usage` BRUTO da NeuraLake (prompt/completion/cached/reasoning,
estimated_cost), o modelo informado, latencia, status HTTP e erro em calls.jsonl. A chave nunca e gravada.
A arquitetura (prompts, fases, limites) do Agentathon nao e alterada.
"""

import asyncio
import contextvars
import json
import random
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent  # repositorio que contem esta pasta bench\
BENCH = Path(__file__).resolve().parent
OUT = BENCH / "out"
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(BENCH))

import httpx  # noqa: E402

from app.agents import prompts as P  # noqa: E402
from app.config import Settings  # noqa: E402
from app.contracts.artifacts import (  # noqa: E402
    Critique, CritiqueOutput, EvidenceItem, EvidenceLocator, Finding, Proposal, ProposalOutput, ResearchOutput,
    SpecialistTask, TaskResult, ThinkerPlanOutput,
)
from app.contracts.challenge import Constraint  # noqa: E402
from app.contracts.common import EvidenceType, SpecialistKind  # noqa: E402
from app.evaluation.verifiers import accept_revision, verify_proposal  # noqa: E402
from app.evidence.calc import CalculationError, MissingInputError, catalog_text, resolve_brief_refs, run_calculation  # noqa: E402
from app.evidence.pack import BRIEF_PROVENANCE, SourceText, brief_items, build_pack, freeze_with_derivations  # noqa: E402
from app.orchestration.phases import CALC_INVALID, validate_plan  # noqa: E402
from app.evidence.retrieval import retrieve  # noqa: E402
from app.orchestration.coordinator import RETRY_WAIT_S, _parse  # noqa: E402
from app.providers.base import GenerateRequest, ProviderError  # noqa: E402
from app.providers.neuralake import NeuraLakeAdapter  # noqa: E402
from app.providers.openai_compat import OpenAICompatAdapter  # noqa: E402

from challenges import BY_ID, CHALLENGES  # noqa: E402

GEN_MODEL = "text"            # modelo fixo de geracao nas tres configuracoes
MAX_OUTPUT = 2000             # igual ao padrao das equipes do Agentathon
PLAN_MAX = 1500               # = min(max_output_tokens, 1500) do pensante
RESEARCH_MAX = 800            # = especialista de pesquisa do Agentathon
CRITIQUE_MAX = 1500           # = min(max_output_tokens, 1500) do critico
MAX_TASKS = 2                 # = MAX_SPECIALIST_TASKS
MAX_ATTEMPTS = 2              # = max_attempts_per_call (inicial + 1 repeticao/reparo)
CALL_TIMEOUT_S = 120
C_TOTAL_CAP = "2.00"          # teto da arena C na rodada principal (folgado; nao deve cortar etapas)
C_DEADLINE_S = 600
GLOBAL_SPEND_STOP_USD = 15.0  # trava do benchmark: para tudo se o custo (tabela publica) passar disso
PUBLIC_PRICES = {"text": (Decimal("0.50"), Decimal("0.75")), "code": (Decimal("1.00"), Decimal("1.00")),
                 "reasoning": (Decimal("2.00"), Decimal("4.00")), "reasoning-pro": (Decimal("2.00"), Decimal("4.50")),
                 "multimodal": (Decimal("1.50"), Decimal("1.50"))}

SINGLE_SYSTEM = P.THINKER_SYSTEM.replace(
    "Voce e o pensante de uma equipe em um hackathon entre agentes.", "Voce e um agente de IA responsavel por uma entrega."
)
assert SINGLE_SYSTEM != P.THINKER_SYSTEM
SINGLE_INSTRUCTIONS = (
    "Voce e o agente responsavel por esta entrega. Atenda ao objetivo do desafio, respeitando todas as restricoes "
    "obrigatorias. Cite evidencias por ID. Declare metricas numericas exigidas pelas restricoes com unidade e "
    "evidencia. Registre hipoteses e lacunas explicitamente."
)
SELF_CRITIC_SYSTEM = P.CRITIC_SYSTEM.replace(
    "Voce e o critico de uma equipe concorrente. Aponte fragilidades da proposta alheia",
    "Voce revisa criticamente a SUA PROPRIA proposta antes da entrega. Aponte fragilidades dela",
)
assert SELF_CRITIC_SYSTEM != P.CRITIC_SYSTEM

# --------------------------------------------------------------------------- instrumentacao

SEED_LABEL: dict[int, dict[str, Any]] = {}
_RAW: contextvars.ContextVar[dict | None] = contextvars.ContextVar("raw", default=None)
_LOG_FH = None
SPEND = {"public_usd": Decimal("0")}


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _hook(response: httpx.Response) -> None:
    holder = _RAW.get()
    if holder is None:
        return
    await response.aread()
    holder["http_status"] = response.status_code
    holder["ratelimit_remaining"] = response.headers.get("x-ratelimit-remaining")
    try:
        holder["json"] = response.json()
    except Exception:  # noqa: BLE001
        holder["body"] = response.text[:300]


_CLIENT: httpx.AsyncClient | None = None
_orig_generate = OpenAICompatAdapter.generate


async def _logged_generate(self, request: GenerateRequest):  # noqa: ANN001, ANN202
    holder: dict[str, Any] = {}
    tok = _RAW.set(holder)
    t0 = time.monotonic()
    started = _now()
    err: dict[str, Any] | None = None
    result = None
    try:
        result = await _orig_generate(self, request)
        return result
    except ProviderError as exc:
        err = {"type": exc.error_type, "usage_known": exc.usage_known, "msg": str(exc)[:300]}
        raise
    except BaseException as exc:  # timeout do coordenador (cancelamento) etc.
        err = {"type": type(exc).__name__, "usage_known": False, "msg": "tentativa interrompida (timeout/cancelamento); consumo desconhecido"}
        raise
    finally:
        _RAW.reset(tok)
        data = holder.get("json") if isinstance(holder.get("json"), dict) else {}
        usage = data.get("usage") if isinstance(data, dict) else None
        label = SEED_LABEL.get(request.seed, {"exec_id": f"seed-{request.seed}"})
        entry = {
            **label, "ts": started, "latency_ms": int((time.monotonic() - t0) * 1000), "stage": request.stage, "role": request.role,
            "candidate_id": request.candidate_id, "attempt": request.attempt, "repair": request.repair_of is not None,
            "requested_model": request.option, "reported_model": data.get("model") if data else None, "response_id": data.get("id") if data else None,
            "http_status": holder.get("http_status"), "usage_raw": usage, "finish_reason": (result.finish_reason if result else None),
            "content_chars": len(result.content) if result else None, "max_output_tokens": request.max_output_tokens,
            "prompt_chars": request.prompt_chars(), "error": err, "ratelimit_remaining": holder.get("ratelimit_remaining"),
        }
        entry.update(usage_fields(usage, request.option))
        SPEND["public_usd"] += Decimal(str(entry["cost_public_usd"] or 0))
        if _LOG_FH is not None:
            _LOG_FH.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            _LOG_FH.flush()


def usage_fields(usage: dict | None, model: str) -> dict[str, Any]:
    """Campos de consumo. prompt_tokens/completion_tokens sao os totais da API (cache e reasoning, quando
    informados, sao SUBCONJUNTOS desses totais no formato OpenAI: nao somar de novo). Sem usage => desconhecido."""
    if not isinstance(usage, dict) or not isinstance(usage.get("prompt_tokens"), int):
        return {"in_tok": None, "out_tok": None, "cached_tok": None, "reasoning_tok": None, "cost_public_usd": None,
                "cost_provider_usd": None, "usage_source": "indisponivel"}
    pin, pout = usage.get("prompt_tokens"), usage.get("completion_tokens")
    ptd = usage.get("prompt_tokens_details") or {}
    ctd = usage.get("completion_tokens_details") or {}
    pi, po = PUBLIC_PRICES[model]
    return {
        "in_tok": pin, "out_tok": pout, "cached_tok": ptd.get("cached_tokens") if isinstance(ptd, dict) else None,
        "reasoning_tok": ctd.get("reasoning_tokens") if isinstance(ctd, dict) else None,
        "cost_public_usd": float((Decimal(pin) * pi + Decimal(pout or 0) * po) / Decimal(1_000_000)),
        "cost_provider_usd": usage.get("estimated_cost"), "usage_source": "api_usage",
    }


def install_instrumentation(log_path: Path) -> None:
    global _LOG_FH, _CLIENT
    _LOG_FH = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    OpenAICompatAdapter.generate = _logged_generate
    orig_init = NeuraLakeAdapter.__init__

    def init(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        orig_init(self, *a, **kw)
        global _CLIENT
        if _CLIENT is None:
            _CLIENT = httpx.AsyncClient(event_hooks={"response": [_hook]})
        self._client = _CLIENT

    NeuraLakeAdapter.__init__ = init


def check_spend() -> None:
    if SPEND["public_usd"] > Decimal(str(GLOBAL_SPEND_STOP_USD)):
        raise SystemExit(f"TRAVA: custo acumulado (tabela publica) {SPEND['public_usd']} > {GLOBAL_SPEND_STOP_USD}")


# --------------------------------------------------------------------------- engine (C) e fontes

def bench_settings() -> Settings:
    data = BENCH / "data"
    data.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=data)


async def upload_sources(c: httpx.AsyncClient, ch: dict) -> list[str]:
    ids = []
    for title, text in ch["docs"]:
        r = await c.post("/api/v1/sources/text", json={"title": title, "text": text})
        r.raise_for_status()
        ids.append(r.json()["source_id"])
    return ids


async def pack_for(c: httpx.AsyncClient, source_ids: list[str], ch: dict):
    """Mesmo pacote v1 que a fase de evidencias do Agentathon monta (mesmas fontes, mesma ordem, mesmos IDs)."""
    texts = []
    for sid in source_ids:
        r = (await c.get(f"/api/v1/sources/{sid}", params={"preview_chars": 20000})).json()
        assert r["chars"] <= 20000
        texts.append(SourceText(sid, r["title"], r["media_type"], r["preview"], r["sha256"], r.get("pages"), False, list(r.get("warnings") or [])))
    brief = brief_items(ch["objective"], ch["context"], [Constraint(**k) for k in ch["constraints"]])
    return build_pack(texts, brief)


def snapshot_for(ch: dict, source_ids: list[str]) -> dict[str, Any]:
    # Mesmo formato que o snapshot do Agentathon entrega aos prompts (Constraint serializada com todos os campos).
    constraints = [Constraint(**k).model_dump(mode="json") for k in ch["constraints"]]
    return {"objective": ch["objective"], "context": ch["context"], "constraints": constraints, "source_ids": source_ids}


# --------------------------------------------------------------------------- chamada logica A/B (espelha o coordenador)

class Failed(Exception):
    pass


async def logical_call(adapter, *, seed: int, stage: str, role: str, system: str, user: str, schema, max_out: int):  # noqa: ANN001, ANN201
    repair_of = repair_err = None
    last = "sem tentativas"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        check_spend()
        req = GenerateRequest(role=role, stage=stage, candidate_id="c1", option=GEN_MODEL, system=system, user=user, schema_name=stage,
                              json_schema=schema.model_json_schema(), max_output_tokens=max_out, timeout_s=CALL_TIMEOUT_S, seed=seed,
                              attempt=attempt, repair_of=repair_of, repair_error=repair_err)
        try:
            res = await asyncio.wait_for(adapter.generate(req), timeout=CALL_TIMEOUT_S)
        except (ProviderError, TimeoutError) as exc:
            kind = getattr(exc, "error_type", "timeout")
            last = f"{kind}: {exc}"
            if getattr(exc, "retryable", True) and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_WAIT_S.get(kind, 0.0))
                continue
            raise Failed(last) from exc
        parsed, err = _parse(res.content, schema)
        if parsed is None and res.finish_reason in ("length", "max_tokens"):
            err = f"resposta cortada pelo limite de {max_out} tokens de saida; responda de forma mais curta ({err})"
        if parsed is not None:
            return parsed
        last = f"schema_invalid: {err}"
        repair_of, repair_err = res.content[:6000], err[:500]
    raise Failed(last)


class _Cand:
    allowed_specialists = [SpecialistKind.DOCUMENT_RESEARCH, SpecialistKind.CALCULATION]
    max_specialist_tasks = MAX_TASKS


class _Catalog:
    @staticmethod
    def specialist_kinds() -> set[str]:
        return {"document_research", "calculation"}


def _validate(out: ThinkerPlanOutput, pack):  # noqa: ANN001, ANN202
    """Chama o validate_plan REAL do Agentathon (inclui a validacao previa de calculo) com um contexto minimo."""
    from types import SimpleNamespace
    ctx = SimpleNamespace(candidate=lambda cid: _Cand, catalog=_Catalog, pack=pack)
    return validate_plan(ctx, "c1", out)


def _validate_tasks(out: ThinkerPlanOutput, pack=None) -> list[SpecialistTask]:  # noqa: ANN001
    return _validate(out, pack).tasks


async def run_task(adapter, seed: int, t: SpecialistTask, pack) -> TaskResult:  # noqa: ANN001
    known = pack.ids()
    if t.kind == SpecialistKind.CALCULATION:
        # espelha _run_task do Agentathon: origem do enunciado + valor precisa constar na evidencia citada
        spec, _resolved = resolve_brief_refs(t.calculation, [i for i in pack.items if i.provenance.startswith(BRIEF_PROVENANCE + ":")])
        try:
            d = run_calculation(spec, known, {i.evidence_id: i for i in pack.items})
        except MissingInputError as exc:
            return TaskResult(task_id=t.task_id, candidate_id="c1", kind=SpecialistKind.CALCULATION, status="skipped", error=f"pendencia: {exc}")
        except CalculationError as exc:
            return TaskResult(task_id=t.task_id, candidate_id="c1", kind=SpecialistKind.CALCULATION, status="failed", error=str(exc))
        item = EvidenceItem(evidence_id=f"drv-c1-{t.task_id}", source_id=None, type=EvidenceType.DERIVED_CALCULATION,
                            excerpt=f"{d.formula} = {d.result} {d.unit} (entradas: " + ", ".join(f"{i.name}={i.value}" for i in d.inputs) + ")",
                            locator=EvidenceLocator(section="derivacao"), provenance=f"specialist:calculation:c1:{t.task_id}", derivation=d)
        return TaskResult(task_id=t.task_id, candidate_id="c1", kind=SpecialistKind.CALCULATION, status="completed",
                          findings=[Finding(claim=f"{d.formula} = {d.result} {d.unit}", evidence_ids=[item.evidence_id], confidence="high")],
                          derived_evidence=[item], model_tier="none")
    excerpts = retrieve(t.query or "", pack.items, k=6)
    ex_meta = [{"evidence_id": e.evidence_id, "excerpt": e.excerpt[:900]} for e in excerpts]
    try:
        out = await logical_call(adapter, seed=seed, stage="research", role="specialist", system=P.SPECIALIST_SYSTEM,
                                 user=P.research_user(t.query or "", ex_meta), schema=ResearchOutput, max_out=RESEARCH_MAX)
    except Failed as exc:
        return TaskResult(task_id=t.task_id, candidate_id="c1", kind=SpecialistKind.DOCUMENT_RESEARCH, status="failed", error=str(exc))
    findings = [Finding(claim=f.claim, evidence_ids=[e for e in f.evidence_ids if e in known], confidence=f.confidence) for f in out.findings]
    return TaskResult(task_id=t.task_id, candidate_id="c1", kind=SpecialistKind.DOCUMENT_RESEARCH, status="completed",
                      findings=[f for f in findings if f.evidence_ids], model_option=GEN_MODEL)


def sanitize(out: ProposalOutput, pack, version: int, revised: bool) -> Proposal:
    known = pack.ids()
    invalid = sorted({e for e in out.evidence_ids if e not in known} | {e for m in out.metrics.values() for e in m.evidence_ids if e not in known})
    data = out.model_dump()
    data["evidence_ids"] = [e for e in out.evidence_ids if e in known]
    for m in data["metrics"].values():
        m["evidence_ids"] = [e for e in m["evidence_ids"] if e in known]
    return Proposal(**data, candidate_id="c1", version=version, invalid_evidence_ids=invalid, revised_from_critique=revised)


async def run_single(adapter, ch: dict, snap: dict, pack1, seed: int, *, self_review_rounds: int, budget_cap: Decimal | None = None) -> dict[str, Any]:  # noqa: ANN001
    """A (self_review_rounds=0) e B (>=1): uma rodada de ferramentas (pesquisa/calculo, mesmo catalogo e limite),
    proposta e, em B, autocritica + revisao (mesmos prompts de critica/revisao do Agentathon)."""
    cand = {"name": "Agente unico", "instructions": SINGLE_INSTRUCTIONS, "model_option": GEN_MODEL}
    stages: list[str] = []
    plan_error = None
    try:
        plan = await logical_call(adapter, seed=seed, stage="plan", role="thinker", system=SINGLE_SYSTEM,
                                  user=P.plan_user(snap, cand, pack1.model_dump(mode="json"), ["document_research", "calculation"], MAX_TASKS),
                                  schema=ThinkerPlanOutput, max_out=PLAN_MAX)
    except Failed as exc:
        # Igual ao Agentathon (phase_plan): planejamento indisponivel => segue sem especialistas.
        plan, plan_error = ThinkerPlanOutput(strategy_summary="(planejamento indisponivel)", tasks=[]), str(exc)
    validated = _validate(plan, pack1)
    plan_repaired = False
    bad = [r for r in validated.validation.rejected if r.reason.startswith(CALC_INVALID)]
    if bad:  # espelha phase_plan: no maximo 1 reparo por plano, com o erro e o catalogo exato
        fix = ("\n\nSEU PLANO ANTERIOR TEVE CALCULOS REJEITADOS:\n" + "\n".join(f"- {r.task_id}: {r.reason}" for r in bad)
               + f"\nCorrija usando somente estas funcoes e nomes de entrada: {catalog_text()} Cada valor deve aparecer no trecho citado. "
               "Se o dado nao existir, remova o calculo. Retorne o plano completo.")
        try:
            plan2 = await logical_call(adapter, seed=seed, stage="plan_repair", role="thinker", system=SINGLE_SYSTEM,
                                       user=P.plan_user(snap, cand, pack1.model_dump(mode="json"), ["document_research", "calculation"], MAX_TASKS) + fix,
                                       schema=ThinkerPlanOutput, max_out=PLAN_MAX)
            validated, plan, plan_repaired = _validate(plan2, pack1), plan2, True
        except Failed:
            pass
    tasks = validated.tasks
    results = [await run_task(adapter, seed, t, pack1) for t in tasks]
    derived = [d for r in results if r.status == "completed" for d in r.derived_evidence]
    pack = freeze_with_derivations(pack1, derived, [])
    tr = [r.model_dump(mode="json") for r in results]
    out = await logical_call(adapter, seed=seed, stage="propose", role="thinker", system=SINGLE_SYSTEM,
                             user=P.propose_user(snap, cand, pack.model_dump(mode="json"), tr, None, None), schema=ProposalOutput, max_out=MAX_OUTPUT)
    proposal = sanitize(out, pack, 1, False)
    history = [proposal.model_dump(mode="json")]
    rounds_done = 0
    for _ in range(self_review_rounds):
        if budget_cap is not None and not _round_fits(seed, budget_cap, snap, pack, proposal):
            break
        anon = proposal.model_dump(mode="json", exclude={"candidate_id", "call_ids", "invalid_evidence_ids", "revised_from_critique", "revised_from_feedback"})
        user = P.critique_user(snap, pack.model_dump(mode="json"), anon).replace(
            "PROPOSTA A CRITICAR (de outra equipe, anonimizada)", "SUA PROPRIA PROPOSTA (revise criticamente antes da entrega)")
        try:
            crit = await logical_call(adapter, seed=seed, stage="critique", role="critic", system=SELF_CRITIC_SYSTEM, user=user,
                                      schema=CritiqueOutput, max_out=CRITIQUE_MAX)
        except Failed:
            break
        known = pack.ids()
        objections = [o.model_copy(update={"evidence_ids": [e for e in o.evidence_ids if e in known]}) for o in crit.objections]
        critique = Critique(objections=objections, strengths=crit.strengths, author_candidate_id="c1", target_candidate_id="c1", target_version=proposal.version)
        try:
            rev = await logical_call(adapter, seed=seed, stage="revise", role="thinker", system=SINGLE_SYSTEM,
                                     user=P.propose_user(snap, cand, pack.model_dump(mode="json"), tr, critique.model_dump(mode="json"), proposal.model_dump(mode="json")),
                                     schema=ProposalOutput, max_out=MAX_OUTPUT)
        except Failed:
            break  # mantem a versao anterior (como o Agentathon faz quando a revisao falha)
        revised = sanitize(rev, pack, proposal.version + 1, True)
        history.append(revised.model_dump(mode="json"))
        # espelha _propose_one (Devin): revisao que passa a violar regra obrigatoria comprovada e rejeitada
        kept, rejected_reasons = accept_revision(proposal, revised, [Constraint(**k) for k in ch["constraints"]], pack)
        if rejected_reasons:
            stages.append("revision_rejected: " + "; ".join(rejected_reasons))
        proposal = kept
        rounds_done += 1
    stages.append(f"rounds={rounds_done}")
    return {"deliverable": proposal.model_dump(mode="json"), "pack": pack.model_dump(mode="json"), "tasks": tr,
            "plan_tasks": [t.model_dump(mode="json") for t in plan.tasks], "accepted_tasks": [t.task_id for t in tasks],
            "versions": history, "self_review_rounds_done": rounds_done, "plan_error": plan_error, "plan_repaired": plan_repaired,
            "plan_rejected": [r.model_dump(mode="json") for r in validated.validation.rejected], "notes": stages}


# --- teto de orcamento para B (rodada complementar): reserva conservadora igual a do ledger do Agentathon
def _spent_public(seed: int) -> Decimal:
    tot = Decimal("0")
    for line in (OUT / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("seed") == seed:
            if e["cost_public_usd"] is None:
                # consumo desconhecido: reserva cheia (prompt estimado + saida maxima), nunca zero
                pi, po = PUBLIC_PRICES[e["requested_model"]]
                tot += (Decimal((e["prompt_chars"] * 2 + 6) // 7) * pi + Decimal(e["max_output_tokens"]) * po) / Decimal(1_000_000)
            else:
                tot += Decimal(str(e["cost_public_usd"]))
    return tot


def _round_fits(seed: int, cap: Decimal, snap: dict, pack, proposal: Proposal) -> bool:  # noqa: ANN001
    """Uma rodada (critica + revisao) so comeca se a reserva conservadora das duas chamadas couber no teto: mesma
    politica de _round_affordable do Agentathon (uma critica + uma revisao, saida maxima, ~3,5 chars/token)."""
    pi, po = PUBLIC_PRICES[GEN_MODEL]
    chars = len(json.dumps(pack.model_dump(mode="json"), ensure_ascii=False)) + len(json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False)) + 6000
    tok_in = Decimal((chars * 2 + 6) // 7)
    one_round = (tok_in * pi + Decimal(CRITIQUE_MAX) * po) / Decimal(1_000_000) + (tok_in * pi + Decimal(MAX_OUTPUT) * po) / Decimal(1_000_000)
    return _spent_public(seed) + one_round <= cap


# --------------------------------------------------------------------------- C: arena real do Agentathon

def c_config(ch: dict, source_ids: list[str], seed: int, *, cap: str = C_TOTAL_CAP) -> dict[str, Any]:
    cand = {"provider": "neuralake", "model_option": GEN_MODEL, "max_specialist_tasks": MAX_TASKS, "max_output_tokens": MAX_OUTPUT}
    return {
        "title": f"[BENCH] {ch['id']} C seed={seed}", "objective": ch["objective"], "context": ch["context"], "source_ids": source_ids,
        "constraints": ch["constraints"],
        "budget": {"currency": "USD", "total_cap": cap, "strict": True, "common_share_pct": "30", "max_total_calls": 32,
                   "max_concurrent_calls": 2, "run_deadline_s": C_DEADLINE_S, "call_timeout_s": CALL_TIMEOUT_S, "max_attempts_per_call": MAX_ATTEMPTS},
        "mode": "real", "real_provider": "neuralake", "config_mode": "manual",
        "candidates": [{"name": "Equipe Equilíbrio", "preset": "balanced", **cand}, {"name": "Equipe Custo", "preset": "cost", **cand}],
        "judges": [{"name": "Padrão", "persona": "default", "provider": "neuralake", "model_option": GEN_MODEL, "max_output_tokens": 3000}],
        "critique_rounds": 1, "seed": seed,
    }


async def run_arena(c: httpx.AsyncClient, ch: dict, source_ids: list[str], seed: int, cap: str = C_TOTAL_CAP) -> dict[str, Any]:
    r = await c.post("/api/v1/runs", json=c_config(ch, source_ids, seed, cap=cap))
    if r.status_code != 202:
        return {"error": f"create {r.status_code}: {r.text[:400]}"}
    run_id = r.json()["run_id"]
    while True:
        await asyncio.sleep(1.0)
        d = (await c.get(f"/api/v1/runs/{run_id}")).json()
        if d["status"] in ("completed", "partial", "failed", "cancelled", "interrupted"):
            break
        check_spend()
    rep = d["artifacts"].get("report")
    packs = d["artifacts"].get("evidence_pack") or []
    pack = max(packs, key=lambda p: p["version"]) if packs else None
    deliverable, how = None, "sem_ranking"
    if rep:
        ranking = rep["ranking"]
        ranked = [e for e in ranking if e.get("rank") is not None]
        if ranked:
            top = min(ranked, key=lambda e: e["rank"])
            how = "rank1"
        else:
            scored = [e for e in ranking if e.get("score_0_100") is not None]
            top = max(scored, key=lambda e: Decimal(e["score_0_100"])) if scored else None
            how = "maior_score_sem_rank" if top else "sem_ranking"
        if top is not None:
            props = {p["candidate_id"]: p for p in rep["proposals"]}
            deliverable = props.get(top["candidate_id"])
    return {
        "run_id": run_id, "status": d["status"], "decision_status": d["decision_status"], "metrics": d["metrics"],
        "budget_buckets": d["budget_buckets"], "engine_calls": d["artifacts"].get("calls", []), "deliverable": deliverable, "deliverable_rule": how,
        "winner_candidate_id": rep.get("winner_candidate_id") if rep else None, "ranking": rep.get("ranking") if rep else None,
        "verifications": rep.get("verifications") if rep else None, "critiques": rep.get("critiques") if rep else None,
        "all_proposals": rep.get("proposals") if rep else None, "operational_changes": rep.get("operational_changes") if rep else None,
        "limitations": rep.get("limitations") if rep else None, "pack": pack, "cost_breakdown": rep.get("cost") if rep else None,
    }


# --------------------------------------------------------------------------- execucao

async def execute(c, adapter, ch, source_ids, pack1, config: str, rep: int, order: int, phase: str, cap: Decimal | None = None) -> dict:  # noqa: ANN001
    seed = random.SystemRandom().randrange(10_000, 2**31 - 1)
    exec_id = f"{phase}-{ch['id']}-{config}-r{rep}-{uuid.uuid4().hex[:6]}"
    SEED_LABEL[seed] = {"exec_id": exec_id, "seed": seed, "challenge": ch["id"], "config": config, "rep": rep, "phase": phase}
    snap = snapshot_for(ch, source_ids)
    t0 = time.monotonic()
    started = _now()
    rec: dict[str, Any] = {"exec_id": exec_id, "seed": seed, "phase": phase, "challenge": ch["id"], "complexity": ch["complexity"], "config": config,
                           "rep": rep, "order_in_block": order, "started": started, "cap": str(cap) if cap is not None else None}
    try:
        if config == "A":
            out = await run_single(adapter, ch, snap, pack1, seed, self_review_rounds=0)
        elif config == "B":
            out = await run_single(adapter, ch, snap, pack1, seed, self_review_rounds=1)
        elif config == "B+":
            out = await run_single(adapter, ch, snap, pack1, seed, self_review_rounds=4, budget_cap=cap)
        elif config in ("C", "C$"):
            out = await run_arena(c, ch, source_ids, seed, cap=str(cap) if cap is not None else C_TOTAL_CAP)
        else:
            raise ValueError(config)
        rec.update(out)
        rec["ok"] = rec.get("deliverable") is not None
        if "error" in out:
            rec["ok"] = False
    except Failed as exc:
        rec.update({"ok": False, "error": f"falha: {exc}"})
    except Exception as exc:  # noqa: BLE001
        rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    rec["wall_s"] = round(time.monotonic() - t0, 2)
    rec["finished"] = _now()
    with open(OUT / "runs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    print(f"[{_now()[11:19]}] {exec_id} ok={rec['ok']} wall={rec['wall_s']}s spend_total_public=${SPEND['public_usd']:.4f} {rec.get('error', '')[:160]}", flush=True)
    return rec


async def main() -> None:
    mode = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)
    install_instrumentation(OUT / "calls.jsonl")
    settings = bench_settings()
    assert settings.neuralake_api_key, "sem credencial NeuraLake"
    from app.main import create_app

    app = create_app(settings)
    adapter = NeuraLakeAdapter(api_key=settings.neuralake_api_key, base_url=settings.neuralake_base_url, json_mode=settings.neuralake_json_mode)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bench", timeout=900) as c:
            prepared: dict[str, tuple[list[str], Any]] = {}
            for ch in CHALLENGES:
                sids = await upload_sources(c, ch)
                prepared[ch["id"]] = (sids, await pack_for(c, sids, ch))
            configs = ["A", "B", "C"]
            if mode == "pilot":
                ch = BY_ID[sys.argv[2] if len(sys.argv) > 2 else "I1"]
                for k, cfg in enumerate(configs):
                    await execute(c, adapter, ch, *prepared[ch["id"]], cfg, 0, k, "pilot")
            elif mode == "main":
                reps = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [1, 2, 3]
                only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
                for rep in reps:
                    for i, ch in enumerate(CHALLENGES):
                        if only and ch["id"] not in only:
                            continue
                        rot = (i + rep) % 3
                        order = configs[rot:] + configs[:rot]  # ordem intercalada por desafio e repeticao
                        for k, cfg in enumerate(order):
                            await execute(c, adapter, ch, *prepared[ch["id"]], cfg, rep, k, "main")
            elif mode == "battery":
                # reteste 03/10: S1 (simples), I1 (intermediario), X1 (complexo); B (agente unico + 1 autorrevisao) x C (arena);
                # 1 repeticao, ordem intercalada por desafio; sequencial (concorrencia interna da arena = 2)
                rep = int(sys.argv[2]) if len(sys.argv) > 2 else 1
                ids = sys.argv[3].split(",") if len(sys.argv) > 3 else ["S1", "I1", "X1"]
                for i, cid in enumerate(ids):
                    order = ["B", "C"] if (i + rep) % 2 == 1 else ["C", "B"]
                    for k, cfg in enumerate(order):
                        await execute(c, adapter, BY_ID[cid], *prepared[cid], cfg, rep, k, "battery")
            elif mode == "budget":
                caps = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))  # {challenge_id: cap_usd}
                reps = int(sys.argv[3]) if len(sys.argv) > 3 else 1
                for rep in range(1, reps + 1):
                    for i, ch in enumerate(CHALLENGES):
                        order = ["B+", "C$"] if (i + rep) % 2 == 0 else ["C$", "B+"]
                        for k, cfg in enumerate(order):
                            await execute(c, adapter, ch, *prepared[ch["id"]], cfg, rep, k, "budget", cap=Decimal(str(caps[ch["id"]])))
    if _CLIENT is not None:
        await _CLIENT.aclose()


if __name__ == "__main__":
    asyncio.run(main())
