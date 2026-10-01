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


def _fmt_num(v: Any) -> str:
    """Numero no padrao brasileiro: 8000 -> 8.000; 0.5 -> 0,5."""
    d = Decimal(str(v))
    if d == d.to_integral_value():
        return f"{int(d):,}".replace(",", ".")
    whole, frac = f"{d:.2f}".split(".")
    return f"{int(whole):,}".replace(",", ".") + "," + frac


def _fmt_value(v: Any, unit: str | None) -> str:
    u = (unit or "").strip()
    if u.upper() == "BRL":
        return f"R$ {_fmt_num(v)}"
    if u.upper() == "USD":
        return f"US$ {_fmt_num(v)}"
    return f"{_fmt_num(v)} {u}".strip()


def _metric_label(md: dict[str, Any], key: str) -> str:
    """Nome legivel da metrica: a descricao da restricao correspondente (em minusculas), senao a chave por extenso."""
    for c in md.get("constraints", []):
        if c.get("metric_key") == key and c.get("description"):
            d = str(c["description"])
            return d[:1].lower() + d[1:]
    return key.replace("_", " ")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


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
            "action_plan": self._action_plan,
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
                                    "rationale": f"{SEAL} levantar dados sobre {focus[:100].lower()}", "query": focus}
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
                    "task_id": "t2", "kind": "calculation", "competence": "cálculo tipado",
                    "rationale": f"{SEAL} somar dois valores encontrados nas fontes",
                    "calculation": {"function": "sum", "unit": unit, "inputs": [
                        {"name": "a", "value": str(nums[0][0]), "unit": unit, "evidence_ids": [nums[0][1]]},
                        {"name": "b", "value": str(nums[1][0]), "unit": unit, "evidence_ids": [nums[1][1]]},
                    ]},
                })
        return {"strategy_summary": f"{SEAL} Estratégia da {md.get('candidate_name')}: {objective[:120]}", "tasks": tasks[:max_tasks]}

    def _research(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        findings = []
        for e in md.get("excerpts", [])[:3]:
            first = re.split(r"(?<=[.!?])\s", e["excerpt"].strip())[0][:180]
            findings.append({"claim": f"{SEAL} O trecho indica: {first}", "evidence_ids": [e["evidence_id"]], "confidence": "medium"})
        return {"findings": findings, "gaps": [f"{SEAL} Pesquisa limitada aos trechos recuperados sobre “{md.get('query', '')[:60]}”."]}

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
        feedback = md.get("human_feedback")
        revised = version >= 2 and critique is not None
        approach = ["equilibrar custo, prazo e qualidade", "minimizar o custo total respeitando as restrições",
                    "priorizar privacidade e robustez", "explorar uma alternativa não convencional"][idx % 4]
        n_obj = len(critique.get("objections", [])) if revised else 0
        declared = "; ".join(f"{_metric_label(md, k)}: {_fmt_value(m['value'], m['unit'])}" for k, m in metrics.items())
        objective = str(md.get("objective", "")).strip()
        objective = (objective[:280].rsplit(" ", 1)[0] + "…") if len(objective) > 280 else objective
        objective = objective if objective.endswith((".", "…")) else objective + "."
        rec = (
            f"{SEAL} Recomendação (versão {version}) para {objective[:1].lower() + objective[1:]} "
            f"Abordagem: {approach}."
            + (f" Números declarados — {declared}." if declared else "")
            + (f" Revisada após a crítica: {n_obj} objeç{'ão considerada' if n_obj == 1 else 'ões consideradas'}." if revised else "")
            + (f" Revisada com o feedback do cliente: “{feedback.get('comment') or feedback.get('general_comment', '')}”." if feedback else "")
            + " Os valores citados vêm exclusivamente do pacote comum de evidências."
        )
        return {
            "title": f"{SEAL} Proposta v{version}: {_cap(approach)}",
            "recommendation": rec,
            "steps": [f"{SEAL} Consolidar os requisitos a partir das evidências", f"{SEAL} Validar as restrições obrigatórias com os dados citados",
                      f"{SEAL} Implantar em fases, começando por um piloto", f"{SEAL} Medir os resultados e revisar o plano"],
            "assumptions": [f"{SEAL} Preços e prazos dos documentos continuam válidos"] + ([f"{SEAL} As objeções recebidas foram tratadas na revisão"] if revised else [])
            + ([f"{SEAL} Feedback do cliente incorporado (repescagem {feedback.get('round', 1)})"] if feedback else []),
            "tradeoffs": [f"{SEAL} Custo × qualidade das respostas", f"{SEAL} Prazo × robustez"],
            "risks": [f"{SEAL} Dependência de um único fornecedor", f"{SEAL} Lacunas nas evidências disponíveis"],
            "metrics": metrics,
            "evidence_ids": cited,
            "open_items": [f"{SEAL} Confirmar os dados que os documentos não cobrem"],
        }

    def _action_plan(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        p = md.get("proposal", {})
        metrics = p.get("metrics") or {}
        ev = (p.get("evidence_ids") or [])[:4]
        review = md.get("review") or {}
        objections = (review.get("objecoes_dos_juizes") or [])[:2]
        crit = [o.get("point", "") for c in (review.get("criticas_recebidas") or []) for o in c.get("objections", [])][:2]
        kinds = {c.get("metric_key"): c.get("kind") for c in md.get("constraints", [])}
        kpis = [
            {"metric": f"{SEAL} {_cap(_metric_label(md, k))}", "target": f"{'pelo menos' if kinds.get(k) == 'numeric_min' else 'até'} {_fmt_value(m.get('value'), m.get('unit'))}"}
            for k, m in metrics.items()
        ]
        clean = lambda s: str(s).replace(SEAL, "").strip()  # noqa: E731
        prev = md.get("previous_plan")
        if prev:
            # Detalhamento: mantem o plano e aprofunda cada fase com tarefas semanais e metas por fase.
            ask = str(md.get("plan_instructions", "")).strip().rstrip(".")[:160]
            version = int(prev.get("version", 1)) + 1
            phases = []
            for i, ph in enumerate(prev.get("phases", []), start=1):
                tasks = list(ph.get("tasks", []))
                name = clean(ph.get("name", ""))
                owner = tasks[0]["owner"] if tasks else "Equipe"
                tasks += [
                    {"task": f"{SEAL} Semana 1 — {name}: levantar pendências e validar o escopo da fase", "owner": owner, "deliverable": f"Checkpoint {i}.1"},
                    {"task": f"{SEAL} Semana 2 — {name}: executar, revisar e registrar as decisões", "owner": owner, "deliverable": f"Checkpoint {i}.2"},
                ]
                phases.append({**ph, "goal": f"{clean(ph.get('goal', ''))}, com acompanhamento semanal", "tasks": tasks[:12]})
            share = round(100 / max(1, len(phases)))
            return {
                **{k: prev.get(k) for k in ("objectives", "risks", "next_steps", "evidence_ids")},
                "title": f"{SEAL} Plano de ação v{version}: {clean(p.get('title', 'proposta')).split(': ', 1)[-1][:100]}",
                "summary": f"{SEAL} Versão {version}, mais detalhada a pedido do cliente ({ask[:1].lower() + ask[1:]}). " + clean(prev.get("summary", ""))[:600],
                "phases": phases,
                "kpis": (list(prev.get("kpis", [])) + [{"metric": f"{SEAL} Entregas da fase “{clean(ph['name'])}” no prazo", "target": "100%"} for ph in phases])[:10],
                "budget_estimate": f"{SEAL} Distribuição estimada por fase: " + "; ".join(f"{clean(ph['name'])} ≈ {share}%" for ph in phases) + ".",
            }
        limits = "; ".join(f"{_metric_label(md, k)}: {_fmt_value(m.get('value'), m.get('unit'))}" for k, m in metrics.items())
        return {
            "title": f"{SEAL} Plano de ação: {clean(p.get('title', 'proposta')).split(': ', 1)[-1][:120]}",
            "summary": f"{SEAL} Plano para executar a proposta (versão {p.get('version', 1)}) em fases curtas, com metas mensuráveis e riscos tratados."
                       + (f" Pedido do cliente considerado: {str(md.get('plan_instructions')).strip().rstrip('.')[:160]}." if md.get("plan_instructions") else ""),
            "objectives": [f"{SEAL} Entregar o piloto dentro das restrições obrigatórias", f"{SEAL} Validar a qualidade com usuários reais", f"{SEAL} Decidir a expansão com base em dados"],
            "phases": [
                {"name": f"{SEAL} Preparação", "duration": "2 semanas", "goal": "Alinhar o escopo e contratar", "tasks": [
                    {"task": f"{SEAL} Aprovar o escopo e o orçamento", "owner": "Patrocinador", "deliverable": "Termo de abertura"},
                    {"task": f"{SEAL} Contratar o fornecedor e montar a equipe", "owner": "Compras + TI", "deliverable": "Contrato assinado"}]},
                {"name": f"{SEAL} Piloto", "duration": "6 semanas", "goal": "Colocar no ar para um grupo restrito", "tasks": [
                    {"task": f"{SEAL} Integrar os documentos e configurar", "owner": "TI", "deliverable": "Ambiente de piloto"},
                    {"task": f"{SEAL} Treinar os usuários-chave", "owner": "RH", "deliverable": "Turma treinada"}]},
                {"name": f"{SEAL} Avaliação e expansão", "duration": "4 semanas", "goal": "Medir os resultados e decidir", "tasks": [
                    {"task": f"{SEAL} Medir os KPIs e coletar feedback", "owner": "Produto", "deliverable": "Relatório do piloto"},
                    {"task": f"{SEAL} Decidir a expansão", "owner": "Comitê", "deliverable": "Decisão registrada"}]},
            ],
            "kpis": kpis + [{"metric": f"{SEAL} Satisfação dos usuários do piloto", "target": "pelo menos 4 de 5"}],
            "risks": [{"risk": f"{SEAL} {_cap(clean(o))}", "mitigation": f"{SEAL} Tratar no plano da fase de piloto"} for o in objections + crit]
                     or [{"risk": f"{SEAL} Atraso do fornecedor", "mitigation": f"{SEAL} Marcos contratuais com multa"}],
            "budget_estimate": f"{SEAL} Dentro dos limites declarados na proposta" + (f" — {limits}." if limits else "."),
            "next_steps": [f"{SEAL} Apresentar o plano ao patrocinador", f"{SEAL} Aprovar a fase de preparação", f"{SEAL} Agendar o kick-off"],
            "evidence_ids": ev,
        }

    def _critique(self, req: GenerateRequest) -> dict[str, Any]:
        md = req.metadata
        target = md.get("target_proposal", {})
        objections = []
        for c in self._numeric_constraints(md):
            m = (target.get("metrics") or {}).get(c["metric_key"])
            label = _metric_label(md, c["metric_key"])
            if m is None:
                objections.append({"point": f"{SEAL} A proposta não informa o {label}, exigido pela regra.", "severity": "medium", "evidence_ids": [], "constraint_id": c["constraint_id"]})
                continue
            value = Decimal(str(m["value"]))
            limit = Decimal(str(c["limit"]))
            violated = value > limit if c["kind"] == "numeric_max" else value < limit
            if violated:
                limit_word = "o máximo" if c["kind"] == "numeric_max" else "o mínimo"
                objections.append({"point": f"{SEAL} Quebra a regra “{c['description']}”: {_fmt_value(value, c['unit'])}, quando {limit_word} é {_fmt_value(limit, c['unit'])}.",
                                   "severity": "high", "evidence_ids": m.get("evidence_ids", []), "constraint_id": c["constraint_id"]})
        objections.append({"point": f"{SEAL} As premissas não deixam claro o horizonte de tempo dos custos.", "severity": "low", "evidence_ids": (target.get("evidence_ids") or [])[:1], "constraint_id": None})
        return {"objections": objections, "strengths": [f"{SEAL} Cita evidências por ID", f"{SEAL} Passos claros"]}

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
                name = (md.get("criteria_names") or {}).get(cid, cid.replace("_", " "))
                tone = "forte" if g >= 9 else "bom" if g >= 7 else "regular" if g >= 5 else "fraco"
                grades.append({"criterion_id": cid, "grade": str(g), "justification": f"{SEAL} Desempenho {tone} em “{name}”, com base nas evidências citadas.",
                               "evidence_ids": (p.get("evidence_ids") or [])[:2]})
            if scenario == "judge_invalid_then_valid" and req.attempt == 1 and grades:
                grades[0]["grade"] = "12"
            if scenario == "judge_fails" and grades:
                grades = grades[1:]
            evaluations.append({"label": label, "grades": grades, "objections": [f"{SEAL} Confirmar os custos com o fornecedor antes de contratar"],
                                "assumptions": [f"{SEAL} As evidências refletem o cenário atual"], "uncertainties": [f"{SEAL} Os custos reais podem variar"]})
        return {"evaluations": evaluations}
