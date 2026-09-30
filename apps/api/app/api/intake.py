"""Validacao, resolucao (modo automatico), congelamento do snapshot e persistencia do job."""

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import APP_VERSION
from app.agents.prompts import PROMPTS_VERSION, prompts_hash
from app.budget.ledger import COMMON_BUCKET, Ledger, candidate_bucket, split_caps
from app.budget.prices import NEURALAKE_OPTIONS, PriceTable, from_nano
from app.config import Settings
from app.contracts.challenge import EFFICIENCY_CRITERION_ID, CandidateConfig, ChallengeConfig, JudgeConfig
from app.contracts.common import ConstraintKind, DecisionStatus, ExecutionMode, Provider, RunStatus
from app.providers.catalog import CATALOG_VERSION, MOCK_SCENARIOS, MODEL_OPTIONS, PRESETS, Catalog
from app.storage.models import Run, Source
from app.storage.repo import utcnow

PRESET_ORDER = ["balanced", "cost", "robust", "explorer"]


class IntakeError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_config", hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


@dataclass
class Prepared:
    snapshot: ChallengeConfig
    hashes: dict[str, str]
    seed: int
    warnings: list[str] = field(default_factory=list)
    bucket_specs: list[tuple[str, int | None, int, int]] = field(default_factory=list)


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    return _sha(payload)


def resolve_candidates(cfg: ChallengeConfig, catalog: Catalog) -> list[CandidateConfig]:
    provider = Provider.MOCK if cfg.mode == ExecutionMode.MOCK else Provider.NEURALAKE
    if cfg.candidates:
        out: list[CandidateConfig] = []
        for i, c in enumerate(cfg.candidates, start=1):
            data = c.model_dump()
            preset = catalog.preset(c.preset) if c.preset else None
            if preset is not None:
                if not data["instructions"]:
                    data["instructions"] = preset.instructions
                if data["model_option"] == "mock-default" and c.provider != Provider.MOCK:
                    data["model_option"] = preset.model_option_by_provider.get(str(c.provider), data["model_option"])
                if not data.get("color"):
                    data["color"] = preset.color
            data["candidate_id"] = data["candidate_id"] or f"c{i}"
            out.append(CandidateConfig(**data))
        return out
    out = []
    for i in range(cfg.candidate_count):
        preset = next(p for p in PRESETS if p.preset == PRESET_ORDER[i % len(PRESET_ORDER)])
        out.append(
            CandidateConfig(
                candidate_id=f"c{i + 1}", name=f"Equipe {preset.label}", preset=preset.preset, instructions=preset.instructions,
                provider=provider, model_option=preset.model_option_by_provider[str(provider)],
                allowed_specialists=list(preset.allowed_specialists), max_specialist_tasks=preset.max_specialist_tasks, color=preset.color,
            )
        )
    return out


async def prepare_run(cfg: ChallengeConfig, *, owner_id: str, session: AsyncSession, settings: Settings, catalog: Catalog, prices: PriceTable) -> Prepared:
    warnings: list[str] = []
    candidates = resolve_candidates(cfg, catalog)
    ids = [c.candidate_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise IntakeError("candidate_id duplicado apos resolucao")
    judge = cfg.judge or JudgeConfig(
        provider=Provider.MOCK if cfg.mode == ExecutionMode.MOCK else Provider.NEURALAKE,
        model_option="mock-default" if cfg.mode == ExecutionMode.MOCK else "reasoning",
    )
    if cfg.budget.run_deadline_s > settings.server_max_deadline_s:
        raise IntakeError(f"run_deadline_s excede o maximo do servidor ({settings.server_max_deadline_s}s)")
    if cfg.mode == ExecutionMode.MOCK and cfg.mock_scenario not in MOCK_SCENARIOS:
        raise IntakeError(f"mock_scenario desconhecido: {cfg.mock_scenario}", hint=f"cenarios: {', '.join(MOCK_SCENARIOS)}")

    # Provedores/opcoes: sem fallback silencioso entre provedores ou para mock.
    for role, provider, option in [(c.name, c.provider, c.model_option) for c in candidates] + [("judge", judge.provider, judge.model_option)]:
        if cfg.mode == ExecutionMode.MOCK and provider != Provider.MOCK:
            raise IntakeError(f"{role}: modo mock aceita apenas provider 'mock' (recebido '{provider}')", code="provider_mismatch")
        if cfg.mode == ExecutionMode.REAL and provider == Provider.MOCK:
            raise IntakeError(f"{role}: modo real nao aceita provider 'mock'; use um provedor real habilitado", code="provider_mismatch")
        if not catalog.provider_enabled(provider):
            raise IntakeError(
                f"{role}: provedor '{provider}' indisponivel. {catalog.unavailable.get(str(provider), '')}".strip(),
                code="provider_unavailable", hint="Configure a credencial no backend (.env) e reinicie; nao ha troca automatica para o modo simulado.",
            )
        if catalog.option_spec(provider, option) is None:
            raise IntakeError(f"{role}: opcao '{option}' nao existe para o provedor '{provider}'", code="unknown_option",
                              hint=f"opcoes: {', '.join(m.option for m in MODEL_OPTIONS if m.provider == provider)}")
    kinds = catalog.specialist_kinds()
    for c in candidates:
        bad = [str(k) for k in c.allowed_specialists if str(k) not in kinds]
        if bad:
            raise IntakeError(f"{c.name}: especialistas desconhecidos: {bad}")

    # Fontes: existentes, do proprietario e com extracao utilizavel.
    if cfg.source_ids:
        rows = list((await session.execute(select(Source).where(Source.id.in_(cfg.source_ids)))).scalars())
        by_id = {r.id: r for r in rows}
        for sid in cfg.source_ids:
            r = by_id.get(sid)
            if r is None or r.owner_id != owner_id:
                raise IntakeError(f"fonte '{sid}' nao encontrada", code="source_not_found")
            if r.extraction_status != "ok":
                raise IntakeError(f"fonte '{r.title}' nao utilizavel (status={r.extraction_status}): {'; '.join(r.warnings or [])}", code="source_unusable")

    # Restricoes qualitativas obrigatorias: consequencia explicitada na validacao inicial.
    for k in cfg.constraints:
        if k.kind == ConstraintKind.QUALITATIVE and k.mandatory:
            warnings.append(
                f"restricao '{k.constraint_id}' e qualitativa e obrigatoria: sem verificador objetivo o resultado sera 'unknown' e a candidatura ficara pendente"
            )

    # Orcamento: eficiencia exige cota positiva; modo estrito exige precos conhecidos.
    has_eff = any(c.computed_by == "server_efficiency" for c in cfg.rubric.criteria)
    if has_eff and cfg.budget.total_cap is None:
        raise IntakeError(
            "o criterio de eficiencia exige budget.total_cap para definir cotas", code="budget_required",
            hint=f"defina budget.total_cap ou remova o criterio '{EFFICIENCY_CRITERION_ID}' da rubrica antes de iniciar",
        )
    ledger = Ledger(prices, strict=cfg.budget.strict)
    if cfg.budget.strict:
        for role, provider, option in [(c.name, c.provider, c.model_option) for c in candidates] + [("judge", judge.provider, judge.model_option)]:
            price = prices.get(str(provider), option) or (prices.max_price(str(provider), NEURALAKE_OPTIONS) if option == "auto" else None)
            if price is None:
                raise IntakeError(
                    f"{role}: preco desconhecido para {provider}/{option}; modo de orcamento estrito bloqueado", code="price_unknown",
                    hint="configure AGENTATHON_NEURALAKE_PRICES_FILE com precos versionados ou use budget.strict=false (orcamento indicativo)",
                )
    weights = {c.candidate_id or "": Decimal(c.quota_weight) for c in candidates}
    caps = split_caps(cfg.budget.total_cap, Decimal(cfg.budget.common_share_pct), weights)
    specs: list[tuple[str, int | None, int, int]] = []
    judge_est = ledger.plan(str(judge.provider), judge.model_option, 16000, judge.max_output_tokens, NEURALAKE_OPTIONS).amount_nano
    specs.append((COMMON_BUCKET, caps[COMMON_BUCKET], judge_est, 1))
    for c in candidates:
        est = ledger.plan(str(c.provider), c.model_option, 12000, c.max_output_tokens, NEURALAKE_OPTIONS).amount_nano
        specs.append((candidate_bucket(c.candidate_id or ""), caps[candidate_bucket(c.candidate_id or "")], est, 1))
    if cfg.budget.total_cap is not None and cfg.budget.strict:
        for key, cap, prov, _ in specs:
            if cap is not None and prov > cap:
                raise IntakeError(
                    f"orcamento insuficiente para uma execucao minima: bucket '{key}' precisa de ~{from_nano(prov)} {cfg.budget.currency} para a etapa protegida, cota = {from_nano(cap)}",
                    code="budget_insufficient", hint="aumente budget.total_cap, reduza max_output_tokens ou ajuste common_share_pct",
                )
    if len(candidates) + 1 > cfg.budget.max_total_calls:
        raise IntakeError("max_total_calls insuficiente para consolidacao de todos os candidatos e Judge", code="budget_insufficient")
    if cfg.mode == ExecutionMode.REAL and not cfg.budget.strict:
        warnings.append("orcamento indicativo: o teto monetario nao e estrito; limites de tokens, chamadas e tempo continuam ativos")

    seed = cfg.seed if cfg.seed is not None else secrets.randbelow(2**31 - 1)
    snapshot = cfg.model_copy(update={"candidates": candidates, "judge": judge, "seed": seed, "config_mode": cfg.config_mode})
    snap_json = snapshot.model_dump(mode="json")
    hashes = {
        "config": _sha(snap_json),
        "rubric": _sha(snap_json["rubric"]),
        "constraints": _sha(snap_json["constraints"]),
        "prompts": prompts_hash(),
        "prompts_version": PROMPTS_VERSION,
        "prices_version": prices.version,
        "catalog_version": CATALOG_VERSION,
        "app_version": APP_VERSION,
        **{f"instructions:{c.candidate_id}": _sha(c.instructions) for c in candidates},
    }
    return Prepared(snapshot=snapshot, hashes=hashes, seed=seed, warnings=warnings, bucket_specs=specs)


async def persist_run(session: AsyncSession, prepared: Prepared, *, owner_id: str, run_id: str, ledger: Ledger, parent_run_id: str | None = None) -> Run:
    snap = prepared.snapshot
    run = Run(
        id=run_id, owner_id=owner_id, title=snap.title, status=str(RunStatus.QUEUED), decision_status=str(DecisionStatus.NOT_EVALUATED),
        mode=str(snap.mode), simulated=snap.mode == ExecutionMode.MOCK, snapshot=snap.model_dump(mode="json"), snapshot_hashes=prepared.hashes,
        seed=prepared.seed, app_version=APP_VERSION, created_at=utcnow(), parent_run_id=parent_run_id, calls_cap=snap.budget.max_total_calls,
    )
    session.add(run)
    await session.flush()
    await ledger.init_buckets(session, run_id, prepared.bucket_specs)
    return run
