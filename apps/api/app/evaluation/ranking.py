"""Motor de ranking deterministico: eficiencia calculada no servidor, score ponderado por juiz, media ponderada do
painel de juizes, elegibilidade e decisao."""

from dataclasses import dataclass
from decimal import Decimal

from app.contracts.artifacts import EfficiencyInfo, Evaluation, JudgeScore, RankingEntry, Verification
from app.contracts.challenge import Rubric
from app.contracts.common import CostQuality, DecisionStatus, Eligibility

TEN = Decimal("10")
ZERO = Decimal("0")


class RankingError(ValueError):
    pass


def efficiency_grade(cost: Decimal, quota: Decimal) -> Decimal:
    if quota <= 0:
        raise RankingError("cota de eficiencia deve ser positiva")
    return TEN * max(ZERO, Decimal("1") - cost / quota)


def validate_grades(rubric: Rubric, grades: dict[str, Decimal]) -> None:
    expected = {c.criterion_id for c in rubric.criteria}
    missing = expected - set(grades)
    extra = set(grades) - expected
    if missing:
        raise RankingError(f"criterios ausentes: {', '.join(sorted(missing))}")
    if extra:
        raise RankingError(f"criterios desconhecidos: {', '.join(sorted(extra))}")
    for cid, g in grades.items():
        if not (ZERO <= g <= TEN):
            raise RankingError(f"nota fora da faixa 0-10 em '{cid}': {g}")


def score(rubric: Rubric, grades: dict[str, Decimal]) -> Decimal:
    validate_grades(rubric, grades)
    total = sum((c.weight * grades[c.criterion_id] for c in rubric.criteria), ZERO)
    return total / TEN


@dataclass
class PanelJudge:
    judge_id: str
    name: str
    weight: Decimal
    rubric: Rubric


@dataclass
class CandidateInput:
    candidate_id: str
    candidate_name: str
    proposal_version: int | None
    verification: Verification | None
    # Avaliacoes por juiz (judge_id -> Evaluation). Uma Evaluation solta equivale a um painel de um unico juiz.
    evaluation: Evaluation | dict[str, Evaluation] | None
    cost: Decimal | None
    quota: Decimal | None
    cost_quality: CostQuality


@dataclass
class RankingResult:
    entries: list[RankingEntry]
    decision_status: DecisionStatus
    winner_candidate_id: str | None
    co_leaders: list[str]
    reasons: list[str]


def _evaluations(ci: CandidateInput, panel: list[PanelJudge]) -> dict[str, Evaluation]:
    if ci.evaluation is None:
        return {}
    if isinstance(ci.evaluation, Evaluation):
        return {panel[0].judge_id: ci.evaluation}
    return ci.evaluation


def compute_ranking(panel: Rubric | list[PanelJudge], inputs: list[CandidateInput]) -> RankingResult:
    if isinstance(panel, Rubric):
        panel = [PanelJudge("j1", "Padrão", Decimal("1"), panel)]
    entries: list[RankingEntry] = []
    reasons: list[str] = []
    needs_efficiency = any(c.computed_by == "server_efficiency" for j in panel for c in j.rubric.criteria)
    any_unknown_cost = False

    # Juizes ativos: os que entregaram avaliacao completa de pelo menos uma proposta. Um juiz que falhou por inteiro
    # sai do painel para todos (registrado nas razoes); a falta de nota de um juiz ativo deixa a candidatura sem score.
    complete = [{jid for jid, ev in _evaluations(ci, panel).items() if ev.status == "complete"} for ci in inputs]
    active_ids = {j.judge_id for j in panel if any(j.judge_id in c for c in complete)}
    active = [j for j in panel if j.judge_id in active_ids]
    missing_judges = [j for j in panel if j.judge_id not in active_ids]
    if active and missing_judges:
        reasons.append("painel incompleto: sem avaliacao de " + ", ".join(j.name for j in missing_judges) + "; media calculada com os demais juizes")

    for ci in inputs:
        notes: list[str] = []
        elig = ci.verification.eligibility if ci.verification else Eligibility.PENDING
        if ci.verification is None:
            notes.append("sem verificacao objetiva (proposta ausente)")
        evals = _evaluations(ci, panel)
        eff_info: EfficiencyInfo | None = None
        eff_grade: Decimal | None = None
        if needs_efficiency and any(ev.status == "complete" for ev in evals.values()):
            if ci.cost is None or ci.quota is None or ci.cost_quality == CostQuality.UNKNOWN:
                any_unknown_cost = True
                notes.append("consumo desconhecido: nota de eficiencia nao pode ser calculada")
                eff_info = EfficiencyInfo(cost=ci.cost, quota=ci.quota, grade=None, cost_quality=ci.cost_quality)
            else:
                eff_grade = efficiency_grade(ci.cost, ci.quota)
                eff_info = EfficiencyInfo(cost=ci.cost, quota=ci.quota, grade=eff_grade, cost_quality=ci.cost_quality)

        judge_scores: list[JudgeScore] = []
        for j in panel:
            ev = evals.get(j.judge_id)
            grades: dict[str, Decimal] = {}
            score_j: Decimal | None = None
            if ev is not None and ev.status == "complete":
                grades = {g.criterion_id: Decimal(g.grade) for g in ev.grades}
                eff = next((c for c in j.rubric.criteria if c.computed_by == "server_efficiency"), None)
                if eff is not None and eff_grade is not None:
                    grades[eff.criterion_id] = eff_grade
                try:
                    score_j = score(j.rubric, grades)
                except RankingError as exc:
                    notes.append(f"{j.name}: score nao calculado: {exc}" if len(panel) > 1 else f"score nao calculado: {exc}")
            elif ev is not None:
                notes.append(f"avaliacao incompleta de {j.name}" if len(panel) > 1 else "avaliacao incompleta do Judge")
            judge_scores.append(JudgeScore(judge_id=j.judge_id, judge_name=j.name, weight=j.weight, score_0_100=score_j, grades=grades))

        score_val: Decimal | None = None
        active_scores = [(j, s) for j, s in zip(panel, judge_scores) if j.judge_id in active_ids]
        if not evals:
            notes.append("nao avaliado")
        elif active_scores and all(s.score_0_100 is not None for _, s in active_scores):
            total_w = sum((j.weight for j, _ in active_scores), ZERO)
            score_val = sum((j.weight * (s.score_0_100 or ZERO) for j, s in active_scores), ZERO) / total_w
        disq = None
        if elig == Eligibility.INELIGIBLE and ci.verification:
            disq = "; ".join(ci.verification.reasons) or "restricao obrigatoria violada"
        entries.append(
            RankingEntry(
                candidate_id=ci.candidate_id, candidate_name=ci.candidate_name, proposal_version=ci.proposal_version,
                score_0_100=score_val, rank=None, eligibility=elig, grades=judge_scores[0].grades if len(panel) == 1 else {},
                judge_scores=judge_scores, efficiency=eff_info, disqualification_reason=disq, notes=notes,
            )
        )

    scored = [e for e in entries if e.score_0_100 is not None]
    # Ordem: elegiveis primeiro, depois pendentes, depois inelegiveis; dentro do grupo por score desc e ID asc.
    order = {Eligibility.ELIGIBLE: 0, Eligibility.PENDING: 1, Eligibility.INELIGIBLE: 2}
    ranked = sorted(scored, key=lambda e: (order[e.eligibility], -e.score_0_100, e.candidate_id))
    rank = 0
    prev: tuple[int, Decimal] | None = None
    for i, e in enumerate(ranked):
        key = (order[e.eligibility], e.score_0_100)
        if key != prev:
            rank = i + 1
            prev = key
        e.rank = rank
    threshold = panel[0].rubric.min_score_threshold if len(panel) == 1 else None

    eligible = [e for e in ranked if e.eligibility == Eligibility.ELIGIBLE]
    if threshold is not None:
        below = [e for e in eligible if e.score_0_100 < threshold]
        for e in below:
            e.notes.append(f"abaixo do limiar minimo {threshold}")
        eligible = [e for e in eligible if e.score_0_100 >= threshold]

    if not inputs:
        return RankingResult(entries, DecisionStatus.NOT_EVALUATED, None, [], ["nenhum candidato"])
    if any_unknown_cost:
        reasons.append("consumo desconhecido impede nota completa e vencedor oficial")
        return RankingResult(entries, DecisionStatus.INCONCLUSIVE, None, [], reasons)
    if not scored:
        reasons.append("nenhuma avaliacao completa disponivel")
        return RankingResult(entries, DecisionStatus.NOT_EVALUATED, None, [], reasons)
    if len(scored) < len(inputs):
        reasons.append(f"apenas {len(scored)} de {len(inputs)} propostas avaliadas: competicao incompleta")
    if not eligible:
        pending = [e for e in ranked if e.eligibility == Eligibility.PENDING]
        if pending:
            reasons.append("nenhum candidato elegivel validado; ha candidatos pendentes por restricoes sem prova")
            return RankingResult(entries, DecisionStatus.INCONCLUSIVE, None, [], reasons)
        reasons.append("todos os candidatos avaliados sao inelegiveis")
        return RankingResult(entries, DecisionStatus.NO_ELIGIBLE_CANDIDATE, None, [], reasons)
    top = eligible[0].score_0_100
    leaders = [e for e in eligible if e.score_0_100 == top]
    if len(leaders) > 1:
        for e in leaders:
            e.co_leader = True
        reasons.append("empate na pontuacao: co-lideranca, ordem visual por ID")
        return RankingResult(entries, DecisionStatus.TIE, None, [e.candidate_id for e in leaders], reasons)
    if len(active) > 1:
        reasons.append(f"nota final = media ponderada de {len(active)} juizes")
    reasons.append("primeiro colocado relativo entre elegiveis; nao significa aprovacao absoluta")
    return RankingResult(entries, DecisionStatus.RANKED, leaders[0].candidate_id, [], reasons)
