"""Exportacao do relatorio em Markdown (texto sanitizado; sem HTML bruto)."""

import re

from app.contracts.artifacts import Report
from app.contracts.challenge import ChallengeConfig
from app.evaluation.verifiers import fmt_value

_HTML = re.compile(r"<[^>]+>")


def _t(text: object) -> str:
    return _HTML.sub("", str(text)).replace("|", "\\|").strip()


def _fmt(value: object) -> str:
    return "n/d" if value is None else _t(value)


def render_markdown(report: Report, snapshot: ChallengeConfig) -> str:
    names = {c.candidate_id: c.name for c in snapshot.candidates or []}
    labels = {c.metric_key: c.description for c in snapshot.constraints if c.metric_key}
    rules = {c.constraint_id: c.description for c in snapshot.constraints}
    lines: list[str] = []
    seal = "**SIMULADO**" if report.simulated else ("**REPLAY**" if report.replay else "**EXECUCAO REAL**")
    lines.append(f"# Relatorio Agentathon — {_t(report.title or report.run_id)}")
    lines.append("")
    lines.append(f"- Run: `{report.run_id}` · Status: `{report.status}` · Decisao: `{report.decision_status}` · Modo: {seal}")
    lines.append(f"- Gerado em: {report.generated_at.isoformat()}")
    if report.winner_candidate_id:
        lines.append(f"- Primeiro colocado relativo: **{_t(names.get(report.winner_candidate_id, report.winner_candidate_id))}** (nao significa aprovacao absoluta)")
    elif report.co_leaders:
        lines.append(f"- Co-lideranca: {', '.join(_t(names.get(c, c)) for c in report.co_leaders)}")
    else:
        lines.append("- Sem vencedor validado")
    lines.append("")
    lines.append("## Objetivo")
    lines.append(_t(snapshot.objective))
    lines.append("")
    if snapshot.refinement:
        r = snapshot.refinement
        lines.append(f"## Repescagem {r.round} (feedback do cliente)")
        out = [c.name for c in snapshot.candidates or [] if c.candidate_id not in {f.candidate_id for f in r.feedback}]
        if out:
            lines.append(f"- Fora da disputa: {', '.join(_t(n) for n in out)}")
        if r.general_comment:
            lines.append(f"- Comentario geral: {_t(r.general_comment)}")
        for f in r.feedback:
            lines.append(f"- {_t(names.get(f.candidate_id, f.candidate_id))}: {_t(f.comment)}")
        lines.append("")
    plan = report.action_plan
    if plan:
        lines.append(f"## Plano de acao (versao {plan.version}) — {_t(names.get(plan.candidate_id, plan.candidate_id))}")
        if plan.detail_request:
            lines.append(f"Detalhamento pedido: {_t(plan.detail_request)}")
        lines.append(f"### {_t(plan.title)}")
        lines.append(_t(plan.summary))
        lines.append("")
        if plan.objectives:
            lines.append("Objetivos:")
            lines += [f"- {_t(o)}" for o in plan.objectives]
            lines.append("")
        for i, ph in enumerate(plan.phases, start=1):
            lines.append(f"#### Fase {i}: {_t(ph.name)}" + (f" ({_t(ph.duration)})" if ph.duration else ""))
            if ph.goal:
                lines.append(f"Objetivo: {_t(ph.goal)}")
            if ph.tasks:
                lines.append("| Tarefa | Responsavel | Entregavel |")
                lines.append("|---|---|---|")
                lines += [f"| {_t(t.task)} | {_t(t.owner)} | {_t(t.deliverable)} |" for t in ph.tasks]
            lines.append("")
        if plan.kpis:
            lines.append("KPIs:")
            lines += [f"- {_t(k.metric)}: {_t(k.target)}" for k in plan.kpis]
            lines.append("")
        if plan.risks:
            lines.append("Riscos e mitigacao:")
            lines += [f"- {_t(r.risk)} → {_t(r.mitigation)}" for r in plan.risks]
            lines.append("")
        if plan.budget_estimate:
            lines.append(f"Orcamento estimado: {_t(plan.budget_estimate)}")
            lines.append("")
    lines.append("## Motivos da decisao")
    lines += [f"- {_t(r)}" for r in report.decision_reasons] or ["- (nenhum)"]
    lines.append("")
    lines.append("## Ranking")
    judges = snapshot.judges or []
    if len(judges) > 1:
        # Painel: uma coluna por juiz (nota 0-100 do juiz); a nota final e a media ponderada pelos pesos.
        cols = [f"{j.name} (peso {j.weight})" for j in judges]
        cell = lambda e, i: _fmt(e.judge_scores[i].score_0_100 if i < len(e.judge_scores) else None)  # noqa: E731
    else:
        rubric = judges[0].rubric if judges and judges[0].rubric else snapshot.rubric
        crit_ids = [c.criterion_id for c in rubric.criteria]
        cols = crit_ids
        cell = lambda e, i: _fmt(e.grades.get(crit_ids[i]))  # noqa: E731
    lines.append("| # | Candidato | Score 0-100 | Elegibilidade | " + " | ".join(_t(c) for c in cols) + " |")
    lines.append("|---|---|---|---|" + "---|" * len(cols))
    for e in sorted(report.ranking, key=lambda e: (e.rank is None, e.rank or 0, e.candidate_id)):
        grades = " | ".join(cell(e, i) for i in range(len(cols)))
        rank = f"{e.rank}{'*' if e.co_leader else ''}" if e.rank else "-"
        lines.append(f"| {rank} | {_t(e.candidate_name)} | {_fmt(e.score_0_100)} | {e.eligibility} | {grades} |")
    lines.append("")
    for e in report.ranking:
        if e.disqualification_reason or e.notes:
            lines.append(f"- {_t(e.candidate_name)}: {_t(e.disqualification_reason or '')} {' '.join(_t(n) for n in e.notes)}".rstrip())
    lines.append("")
    lines.append("## Propostas")
    for p in report.proposals:
        lines.append(f"### {_t(names.get(p.candidate_id, p.candidate_id))} — v{p.version}: {_t(p.title)}")
        lines.append(_t(p.recommendation))
        if p.metrics:
            lines.append("")
            lines.append("Metricas declaradas:")
            for k, m in p.metrics.items():
                lines.append(f"- {_t(labels.get(k, k.replace('_', ' ')))}: {fmt_value(m.value, m.unit)} (evidencias: {', '.join(m.evidence_ids) or 'nenhuma'})")
        for title, items in (("Passos", p.steps), ("Premissas", p.assumptions), ("Trade-offs", p.tradeoffs), ("Riscos", p.risks), ("Pendencias", p.open_items)):
            if items:
                lines.append("")
                lines.append(f"{title}:")
                lines += [f"- {_t(i)}" for i in items]
        lines.append("")
        lines.append(f"Evidencias citadas: {', '.join(p.evidence_ids) or 'nenhuma'}" + (f" · invalidas removidas: {', '.join(p.invalid_evidence_ids)}" if p.invalid_evidence_ids else ""))
        lines.append("")
    if report.verifications:
        lines.append("## Verificacoes objetivas")
        for v in report.verifications:
            lines.append(f"### {_t(names.get(v.candidate_id, v.candidate_id))} (v{v.proposal_version}) — {v.eligibility}")
            for c in v.checks:
                verdict = {"pass": "cumpre", "fail": "quebra", "unknown": "sem prova"}.get(str(c.result), str(c.result))
                lines.append(f"- {_t(rules.get(c.constraint_id, c.constraint_id))} → **{verdict}**: {_t(c.reason)}")
            lines.append("")
    if report.critiques:
        lines.append("## Criticas cruzadas")
        for c in report.critiques:
            lines.append(f"### {_t(names.get(c.author_candidate_id, c.author_candidate_id))} → {_t(names.get(c.target_candidate_id, c.target_candidate_id))} (v{c.target_version})")
            for o in c.objections:
                lines.append(f"- [{o.severity}] {_t(o.point)}" + (f" (restricao `{_t(o.constraint_id)}`)" if o.constraint_id else ""))
            lines.append("")
    if report.evaluations:
        lines.append("## Avaliacao dos juizes" if len(judges) > 1 else "## Avaliacao do Judge")
        lines.append(f"Ordem embaralhada com seed {report.judge_shuffle_seed}; propostas anonimizadas.")
        for ev in report.evaluations:
            who = f" — {_t(ev.judge_name)}" if len(judges) > 1 else ""
            lines.append(f"### {_t(names.get(ev.candidate_id, ev.candidate_id))} ({ev.judge_label}){who}")
            for g in ev.grades:
                lines.append(f"- `{_t(g.criterion_id)}`: {g.grade} — {_t(g.justification)}")
            for title, items in (("Objecoes", ev.objections), ("Hipoteses", ev.assumptions), ("Incertezas", ev.uncertainties)):
                if items:
                    lines.append(f"- {title}: " + "; ".join(_t(i) for i in items))
            lines.append("")
    lines.append("## Consumo")
    c = report.cost
    lines.append(f"- Total: {c.total} {c.currency} (qualidade: {c.quality}; chamadas: {c.calls_used}/{c.calls_cap}; teto: {_fmt(c.cap)}; estrito: {c.strict})")
    lines.append(f"- Comum (preparacao + Judge): {c.common} · Judge: {c.judge}")
    for cid, v in c.per_candidate.items():
        extra = ""
        if c.secondary_calls.get(cid):
            extra = f" · {c.secondary_calls[cid]} chamada(s) no modelo economico, economia estimada {c.secondary_savings.get(cid, 0)}"
        lines.append(f"- {_t(names.get(cid, cid))}: {v}{extra}")
    if c.pending_unknown_reserved > 0:
        lines.append(f"- Reservas pendentes (consumo desconhecido): {c.pending_unknown_reserved}")
    lines.append("")
    if report.diversity_observed:
        lines.append("## Diversidade observada")
        for prov, models in report.diversity_observed.items():
            lines.append(f"- {prov}: {', '.join(_t(m) for m in models)}")
        lines.append("")
    lines.append("## Limitacoes e mudancas operacionais")
    lines += [f"- {_t(l)}" for l in report.limitations] or ["- (nenhuma registrada)"]
    lines += [f"- [operacional] {_t(o)}" for o in report.operational_changes]
    if report.evidence_gaps:
        lines.append("")
        lines.append("Lacunas de evidencia:")
        lines += [f"- {_t(g)}" for g in report.evidence_gaps]
    lines.append("")
    lines.append("## Proximos passos")
    lines += [f"- {_t(s)}" for s in report.next_steps]
    lines.append("")
    return "\n".join(lines)
