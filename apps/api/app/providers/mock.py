"""MockAdapter: deterministico, sem rede. Gera saidas estruturadas ancoradas no pacote de evidencias real.

Cenarios cobrem sucesso, inelegibilidade, dados insuficientes e falhas (schema, erro transitorio, timeout).
Todo conteudo leva o selo [SIMULADO].
"""

import hashlib
import json
import re
from decimal import Decimal
from typing import Any

from app.contracts.common import UsageQuality
from app.providers.base import GenerateRequest, GenerateResult, ProviderError, Usage, estimate_tokens

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w])")
SEAL = "[SIMULADO]"


def _h(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)


def _numbers(excerpt: str) -> list[Decimal]:
    out: list[Decimal] = []
    for m in _NUM.findall(excerpt):
        raw = m
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", raw):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", ".")
        try:
            out.append(Decimal(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


class MockAdapter:
    name = "mock"

    async def generate(self, request: GenerateRequest) -> GenerateResult:
        md = request.metadata
        scenario = md.get("scenario", "default")
        idx = md.get("candidate_index")
        stage = request.stage
        attempt = request.attempt

        if scenario == "transient_error_once" and stage == "propose" and idx == 0 and attempt == 1:
            raise ProviderError("server_error", f"{SEAL} erro transitorio simulado (HTTP 503)", retryable=True, usage_known=True)
        if scenario == "timeout_unknown_usage" and stage == "propose" and idx == 1 and attempt == 1:
            raise ProviderError("timeout", f"{SEAL} timeout simulado com consumo desconhecido", retryable=True, usage_known=False)

        builders = {
            "thinker_plan": self._plan,
            "research": self._research,
            "proposal": self._proposal,
            "critique": self._critique,
            "judge": self._judge,
        }
        builder = builders.get(request.schema_name)
        if builder is None:
            raise ProviderError("unsupported_schema", f"mock nao suporta schema {request.schema_name}")
        payload = builder(request)
        content = json.dumps(payload, ensure_ascii=False, default=str)
        in_tok = estimate_tokens(request.prompt_chars())
        out_tok = max(1, len(content) // 4)
        if scenario == "tie":
            in_tok, out_tok = 1200, 400
        return GenerateResult(
            content=content,
            usage=Usage(input_tokens=in_tok, output_tokens=out_tok, quality=UsageQuality.PROVIDER_REPORTED),
            reported_model=f"mock/{request.option}",
            request_id=f"mock-{_h(request.seed, stage, idx, attempt):x}",
            latency_ms=5,
            finish_reason="stop",
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _numeric_constraints(md: dict[str, Any]) -> list[dict[str, Any]]:
        return [c for c in md.get("constraints", []) if c.get("kind") in ("numeric_max", "numeric_min")]

    @staticmethod
    def _evidence(md: dict[str, Any]) -> list[dict[str, Any]]:
        return md.get("evidence", [])

    def _grounded_value(self, md: dict[str, Any], constraint: dict[str, Any], want_pass: bool) -> tuple[Decimal, list[str]] | None:
        """Escolhe um numero que exista nos trechos: o maior <= limite (pass) ou o menor > limite (fail)."""
        limit = Decimal(str(constraint["limit"]))
        is_max = constraint["kind"] == "numeric_max"
        best: tuple[Decimal, str] | None = None
        for item in self._evidence(md):
            if item.get("type") != "source_claim":
                continue
            for n in _numbers(item["excerpt"]):
                if n <= 0:
                    continue
                ok = (n <= limit) if is_max else (n >= limit)
                if ok != want_pass:
                    continue
                if is_max:
                    better = best is None or (n > best[0] if want_pass else n < best[0])
                else:
                    better = best is None or (n < best[0] if want_pass else n > best[0])
                if better:
                    best = (n, item["evidence_id"])
        if best is None:
            return None
        return best[0], [best[1]]

    # ------------------------------------------------------------------ builders

    def _plan(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        allowed = list(md.get("allowed_specialists", []))
        max_tasks = int(md.get("max_tasks", 2))
        scenario = md.get("scenario", "default")
        idx = int(md.get("candidate_index", 0))
        objective = md.get("objective", "")
        constraints = self._numeric_constraints(md)
        tasks: list[dict[str, Any]] = []
        focus = constraints[0]["description"] if constraints else objective[:80]
        if scenario == "unauthorized_specialist":
            tasks.append({"task_id": "t1", "kind": "web_search", "competence": "busca externa", "rationale": f"{SEAL} tenta ferramenta nao autorizada", "query": objective[:120]})
            tasks.append({"task_id": "t2", "kind": "calculation", "competence": "calculo", "rationale": f"{SEAL} tenta especialista possivelmente nao permitido",
                          "calculation": {"function": "sum", "inputs": [{"name": "a", "value": "1", "unit": "x", "evidence_ids": []}], "unit": "x"}})
            tasks.append({"task_id": "t3", "kind": "document_research", "competence": "pesquisa", "rationale": "pesquisa legitima", "query": focus})
            return {"strategy_summary": f"{SEAL} estrategia do candidato {idx + 1}", "tasks": tasks[: max_tasks + 1]}
        if "document_research" in allowed and max_tasks >= 1:
            task: dict[str, Any] = {"task_id": "t1", "kind": "document_research", "competence": "pesquisa documental",
                                    "rationale": f"{SEAL} levantar dados sobre: {focus[:100]}", "query": focus}
            if md.get("secondary_model_option"):
                task["model_tier"] = "secondary"  # busca simples: o pensante delega ao modelo economico
            tasks.append(task)
        if "calculation" in allowed and len(tasks) < max_tasks and idx % 2 == 0:
            nums: list[tuple[Decimal, str]] = []
            for item in self._evidence(md):
                if item.get("type") != "source_claim":
                    continue
                for n in _numbers(item["excerpt"]):
                    if n > 0:
                        nums.append((n, item["evidence_id"]))
                if len(nums) >= 2:
                    break
            if len(nums) >= 2:
                unit = constraints[0]["unit"] if constraints else "unid"
                tasks.append({
                    "task_id": "t2", "kind": "calculation", "competence": "calculo tipado",
                    "rationale": f"{SEAL} somar dois valores encontrados nas fontes",
                    "calculation": {"function": "sum", "unit": unit, "inputs": [
                        {"name": "a", "value": str(nums[0][0]), "unit": unit, "evidence_ids": [nums[0][1]]},
                        {"name": "b", "value": str(nums[1][0]), "unit": unit, "evidence_ids": [nums[1][1]]},
                    ]},
                })
        return {"strategy_summary": f"{SEAL} estrategia do candidato {idx + 1}: {md.get('candidate_name')} — {objective[:120]}", "tasks": tasks[:max_tasks]}

    def _research(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        findings = []
        for e in md.get("excerpts", [])[:3]:
            first = re.split(r"(?<=[.!?])\s", e["excerpt"].strip())[0][:180]
            findings.append({"claim": f"{SEAL} O trecho indica: {first}", "evidence_ids": [e["evidence_id"]], "confidence": "medium"})
        return {"findings": findings, "gaps": [f"{SEAL} pesquisa limitada aos trechos recuperados para '{md.get('query', '')[:60]}'"]}

    def _metrics_for(self, md: dict[str, Any], version: int) -> dict[str, Any]:
        scenario = md.get("scenario", "default")
        idx = int(md.get("candidate_index", 0))
        metrics: dict[str, Any] = {}
        for c in self._numeric_constraints(md):
            key = c["metric_key"]
            if scenario == "all_ineligible":
                want_pass = False
            elif scenario in ("tie", "insufficient_evidence"):
                want_pass = True
            elif idx == 1:
                want_pass = version >= 2
            elif idx == 2:
                continue  # omite a metrica: resultado unknown -> candidatura pendente
            else:
                want_pass = True
            picked = self._grounded_value(md, c, want_pass)
            if picked is None:
                picked = self._grounded_value(md, c, not want_pass)
                if picked is None:
                    continue
            value, ev = picked
            if scenario == "insufficient_evidence":
                ev = [e["evidence_id"] for e in self._evidence(md) if e["evidence_id"] not in ev][:1] or ev
                value = value + Decimal("0.37")
            metrics[key] = {"value": str(value), "unit": c["unit"], "evidence_ids": ev}
        return metrics

    def _proposal(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        idx = int(md.get("candidate_index", 0))
        version = int(md.get("version", 1))
        evidence = self._evidence(md)
        cited = [e["evidence_id"] for e in evidence[idx::max(1, len(evidence) // 4 or 1)]][:4] or [e["evidence_id"] for e in evidence[:3]]
        for tr in md.get("task_results", []):
            for f in tr.get("findings", []):
                cited += f.get("evidence_ids", [])
            for d in tr.get("derived_evidence", []):
                cited.append(d["evidence_id"])
        cited = list(dict.fromkeys(cited))[:8]
        metrics = self._metrics_for(md, version)
        critique = md.get("critique")
        revised = version >= 2 and critique is not None
        approach = ["priorizar equilibrio entre custo, prazo e qualidade", "minimizar custo total respeitando as restricoes",
                    "priorizar privacidade e robustez", "explorar alternativa nao convencional"][idx % 4]
        rec = (
            f"{SEAL} Recomendacao (v{version}) para: {md.get('objective', '')[:200]}. "
            f"Abordagem: {approach}. "
            + (f"Revisada apos critica: {len(critique.get('objections', []))} objecao(oes) consideradas. " if revised else "")
            + "Os valores citados vem exclusivamente do pacote comum de evidencias."
        )
        return {
            "title": f"{SEAL} Proposta v{version}: {approach}",
            "recommendation": rec,
            "steps": [f"{SEAL} Passo 1: consolidar requisitos a partir das evidencias", f"{SEAL} Passo 2: validar restricoes obrigatorias com dados citados",
                      f"{SEAL} Passo 3: plano de implantacao em fases", f"{SEAL} Passo 4: medir resultados e revisar"],
            "assumptions": [f"{SEAL} precos e prazos dos documentos permanecem validos"] + ([f"{SEAL} objecoes recebidas foram tratadas na revisao"] if revised else []),
            "tradeoffs": [f"{SEAL} custo x qualidade das respostas", f"{SEAL} prazo x robustez"],
            "risks": [f"{SEAL} dependencia de fornecedor", f"{SEAL} lacunas nas evidencias"],
            "metrics": metrics,
            "evidence_ids": cited,
            "open_items": [f"{SEAL} confirmar dados nao cobertos pelos documentos"],
        }

    def _critique(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        target = md.get("target_proposal", {})
        objections = []
        for c in self._numeric_constraints(md):
            m = (target.get("metrics") or {}).get(c["metric_key"])
            if m is None:
                objections.append({"point": f"{SEAL} A proposta nao declara a metrica '{c['metric_key']}' exigida pela restricao.", "severity": "medium", "evidence_ids": [], "constraint_id": c["constraint_id"]})
                continue
            value = Decimal(str(m["value"]))
            limit = Decimal(str(c["limit"]))
            violated = value > limit if c["kind"] == "numeric_max" else value < limit
            if violated:
                objections.append({"point": f"{SEAL} Conflito com restricao '{c['constraint_id']}': {value} {c['unit']} viola o limite {limit} {c['unit']}.",
                                   "severity": "high", "evidence_ids": m.get("evidence_ids", []), "constraint_id": c["constraint_id"]})
        objections.append({"point": f"{SEAL} As premissas nao explicitam o horizonte temporal dos custos.", "severity": "low", "evidence_ids": (target.get("evidence_ids") or [])[:1], "constraint_id": None})
        return {"objections": objections, "strengths": [f"{SEAL} cita evidencias por ID", f"{SEAL} passos claros"]}

    def _judge(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        scenario = md.get("scenario", "default")
        criteria = list(md.get("criteria", []))
        constraints = self._numeric_constraints(md)
        judge_id = md.get("judge_id", "j1")
        evaluations = []
        for p in md.get("proposals", []):
            label = p["label"]
            # O juiz j1 mantem a semente historica; os demais juizes do painel variam de forma deterministica.
            salt = "" if judge_id == "j1" else judge_id
            base_seed = _h(req.seed, json.dumps(p, sort_keys=True, default=str) + salt) if scenario != "tie" else 7
            grades = []
            for i, cid in enumerate(criteria):
                g = 6 + ((base_seed >> (i * 3)) % 4)  # 6..9
                if scenario == "tie":
                    g = 8
                if cid in ("adherence", "architecture_viability", "real_pain"):
                    for c in constraints:
                        m = (p.get("metrics") or {}).get(c["metric_key"])
                        if m is not None:
                            v = Decimal(str(m["value"]))
                            lim = Decimal(str(c["limit"]))
                            if (v > lim) if c["kind"] == "numeric_max" else (v < lim):
                                g = min(g, 4)
                grades.append({"criterion_id": cid, "grade": str(g), "justification": f"{SEAL} {label}: avaliacao de '{cid}' com base nas evidencias citadas.", "evidence_ids": (p.get("evidence_ids") or [])[:2]})
            if scenario == "judge_invalid_then_valid" and req.attempt == 1 and grades:
                grades[0]["grade"] = "12"
            if scenario == "judge_fails" and grades:
                grades = grades[1:]
            evaluations.append({"label": label, "grades": grades, "objections": [f"{SEAL} objecao residual sobre {label}"],
                                "assumptions": [f"{SEAL} evidencias refletem o cenario atual"], "uncertainties": [f"{SEAL} custos reais podem variar"]})
        return {"evaluations": evaluations}
