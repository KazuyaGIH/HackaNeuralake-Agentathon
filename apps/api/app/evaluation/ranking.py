"""Motor de ranking deterministico: eficiencia calculada no servidor, score ponderado, elegibilidade e decisao."""

from dataclasses import dataclass
from decimal import Decimal

from app.contracts.artifacts import EfficiencyInfo, Evaluation, RankingEntry, Verification
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
class CandidateInput:
    candidate_id: str
    candidate_name: str
    proposal_version: int | None
    verification: Verification | None
    evaluation: Evaluation | None
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


def compute_ranking(rubric: Rubric, inputs: list[CandidateInput]) -> RankingResult:
    entries: list[RankingEntry] = []
    reasons: list[str] = []
    server_criteria = [c for c in rubric.criteria if c.computed_by == "server_efficiency"]
    eff_criterion = server_criteria[0] if server_criteria else None
    any_unknown_cost = False

    for ci in inputs:
        notes: list[str] = []
        elig = ci.verification.eligibility if ci.verification else Eligibility.PENDING
        if ci.verification is None:
            notes.append("sem verificacao objetiva (proposta ausente)")
        grades: dict[str, Decimal] = {}
        score_val: Decimal | None = None
        eff_info: EfficiencyInfo | None = None
        if ci.evaluation is not None and ci.evaluation.status == "complete":
            grades = {g.criterion_id: Decimal(g.grade) for g in ci.evaluation.grades}
            if eff_criterion is not None:
                if ci.cost is None or ci.quota is None or ci.cost_quality == CostQuality.UNKNOWN:
                    any_unknown_cost = True
                    notes.append("consumo desconhecido: nota de eficiencia nao pode ser calculada")
                    eff_info = EfficiencyInfo(cost=ci.cost, quota=ci.quota, grade=None, cost_quality=ci.cost_quality)
                else:
                    g = efficiency_grade(ci.cost, ci.quota)
                    grades[eff_criterion.criterion_id] = g
                    eff_info = EfficiencyInfo(cost=ci.cost, quota=ci.quota, grade=g, cost_quality=ci.cost_quality)
            try:
                score_val = score(rubric, grades)
            except RankingError as exc:
                notes.append(f"score nao calculado: {exc}")
                score_val = None
        elif ci.evaluation is not None:
            notes.append("avaliacao incompleta do Judge")
        else:
            notes.append("nao avaliado")
        disq = None
        if elig == Eligibility.INELIGIBLE and ci.verification:
            disq = "; ".join(ci.verification.reasons) or "restricao obrigatoria violada"
        entries.append(
            RankingEntry(
                candidate_id=ci.candidate_id, candidate_name=ci.candidate_name, proposal_version=ci.proposal_version,
                score_0_100=score_val, rank=None, eligibility=elig, grades=grades, efficiency=eff_info,
                disqualification_reason=disq, notes=notes,
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
    threshold = rubric.min_score_threshold

    eligible = [e for e in ranked if e.eligibility == Eligibility.ELIGIBLE]
    if threshold is not None:
        below = [e for e in eligible if e.score_0_100 < threshold]
        for e in below:
            e.notes.append(f"abaixo do limiar minimo {threshold}")
        eligible = [e for e in eligible if e.score_0_100 >= threshold]

    if not inputs:
        return RankingResult(entries, DecisionStatus.NOT_EVALUATED, None, [], ["nenhum candidato"])
    if any_unknown_cost and eff_criterion is not None:
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
    reasons.append("primeiro colocado relativo entre elegiveis; nao significa aprovacao absoluta")
    return RankingResult(entries, DecisionStatus.RANKED, leaders[0].candidate_id, [], reasons)
