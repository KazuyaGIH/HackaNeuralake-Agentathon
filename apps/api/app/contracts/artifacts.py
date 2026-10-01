from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field

from app.contracts.common import (
    CheckResult,
    ContractModel,
    CostQuality,
    DecisionStatus,
    Eligibility,
    EvidenceType,
    Money,
    RunStatus,
    SpecialistKind,
)

# ----------------------------------------------------------------------------- evidencias


class EvidenceLocator(ContractModel):
    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class CalcInput(ContractModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    value: Money
    unit: str | None = Field(default=None, max_length=32)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class Derivation(ContractModel):
    model_config = ConfigDict(extra="forbid")

    function: str
    formula: str
    inputs: list[CalcInput]
    result: Money
    unit: str
    input_evidence_ids: list[str]


class EvidenceItem(ContractModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str | None = None
    type: EvidenceType
    excerpt: str = Field(max_length=4000)
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    provenance: str
    derivation: Derivation | None = None


class SourceSummary(ContractModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    media_type: str
    pages: int | None = None
    chars: int
    sha256: str
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class EvidencePack(ContractModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    frozen: bool
    sources: list[SourceSummary]
    items: list[EvidenceItem]
    assumptions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    extractor_version: str
    pack_hash: str = ""

    def ids(self) -> set[str]:
        return {i.evidence_id for i in self.items}


# ----------------------------------------------------------------------------- planejamento e delegacao


class CalculationSpec(ContractModel):
    model_config = ConfigDict(extra="forbid")

    function: str = Field(min_length=1, max_length=64)
    inputs: list[CalcInput] = Field(min_length=1, max_length=8)
    unit: str = Field(min_length=1, max_length=32)


class SpecialistTask(ContractModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    kind: str = Field(max_length=64, description="Competencia solicitada; validada contra o catalogo permitido.")
    competence: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=600)
    query: str | None = Field(default=None, max_length=600)
    calculation: CalculationSpec | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=2)
    model_tier: Literal["main", "secondary"] | None = Field(
        default=None, description="Escolha do pensante: 'secondary' (economico) para tarefas simples, 'main' se exigir raciocinio."
    )


class ThinkerPlanOutput(ContractModel):
    """Saida estruturada esperada do pensante na fase de planejamento."""

    model_config = ConfigDict(extra="forbid")

    strategy_summary: str = Field(max_length=2000)
    tasks: list[SpecialistTask] = Field(default_factory=list, max_length=6)


class PlanRejection(ContractModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    reason: str


class PlanValidation(ContractModel):
    model_config = ConfigDict(extra="forbid")

    accepted_task_ids: list[str]
    rejected: list[PlanRejection]
    adjusted: bool


class TaskPlan(ContractModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    strategy_summary: str
    tasks: list[SpecialistTask]
    validation: PlanValidation


class Finding(ContractModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"] = "medium"


class ResearchOutput(ContractModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=8)


class TaskResult(ContractModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    candidate_id: str
    kind: SpecialistKind
    status: Literal["completed", "failed", "skipped"]
    findings: list[Finding] = Field(default_factory=list)
    derived_evidence: list[EvidenceItem] = Field(default_factory=list)
    shareable: bool = True
    error: str | None = None
    call_ids: list[str] = Field(default_factory=list)
    model_tier: Literal["main", "secondary", "none"] = "main"
    model_option: str | None = None


# ----------------------------------------------------------------------------- propostas e critica


class ProposalMetric(ContractModel):
    model_config = ConfigDict(extra="forbid")

    value: Money
    unit: str = Field(max_length=32)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class ProposalOutput(ContractModel):
    """Saida estruturada do pensante ao consolidar/revisar a proposta."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=200)
    recommendation: str = Field(max_length=6000)
    steps: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    tradeoffs: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=20)
    metrics: dict[str, ProposalMetric] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    open_items: list[str] = Field(default_factory=list, max_length=20)


class Proposal(ProposalOutput):
    candidate_id: str
    version: int
    invalid_evidence_ids: list[str] = Field(default_factory=list)
    revised_from_critique: bool = False
    call_ids: list[str] = Field(default_factory=list)


class Objection(ContractModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(max_length=1000)
    severity: Literal["low", "medium", "high"] = "medium"
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    constraint_id: str | None = None


class CritiqueOutput(ContractModel):
    model_config = ConfigDict(extra="forbid")

    objections: list[Objection] = Field(default_factory=list, max_length=12)
    strengths: list[str] = Field(default_factory=list, max_length=8)


class Critique(CritiqueOutput):
    author_candidate_id: str
    target_candidate_id: str
    target_version: int
    call_ids: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- verificacao e avaliacao


class ConstraintCheck(ContractModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    mandatory: bool
    result: CheckResult
    observed_value: Money | None = None
    unit: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class Verification(ContractModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    proposal_version: int
    checks: list[ConstraintCheck]
    valid_evidence_ids: list[str]
    invalid_evidence_ids: list[str]
    eligibility: Eligibility
    reasons: list[str] = Field(default_factory=list)


class CriterionGrade(ContractModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    grade: Money = Field(ge=0, le=10)
    justification: str = Field(max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class JudgeProposalEvaluation(ContractModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Rotulo anonimo da proposta (ex.: P1).")
    grades: list[CriterionGrade]
    objections: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)


class JudgeOutput(ContractModel):
    model_config = ConfigDict(extra="forbid")

    evaluations: list[JudgeProposalEvaluation]


class Evaluation(ContractModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    proposal_version: int
    judge_id: str = "j1"
    judge_name: str = "Padrão"
    judge_label: str
    rubric_hash: str
    pack_version: int
    grades: list[CriterionGrade]
    objections: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    status: Literal["complete", "incomplete"]
    call_ids: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- ranking e relatorio


class EfficiencyInfo(ContractModel):
    model_config = ConfigDict(extra="forbid")

    cost: Money | None
    quota: Money | None
    grade: Money | None
    cost_quality: CostQuality


class JudgeScore(ContractModel):
    model_config = ConfigDict(extra="forbid")

    judge_id: str
    judge_name: str
    weight: Money
    score_0_100: Money | None
    grades: dict[str, Money] = Field(default_factory=dict)


class RankingEntry(ContractModel):
    """score_0_100 = media ponderada (pelo peso de cada juiz) das notas dos juizes em judge_scores.
    'grades' traz as notas por criterio apenas quando o painel tem um unico juiz (compatibilidade)."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_name: str
    proposal_version: int | None
    score_0_100: Money | None
    rank: int | None
    co_leader: bool = False
    eligibility: Eligibility
    grades: dict[str, Money] = Field(default_factory=dict)
    judge_scores: list[JudgeScore] = Field(default_factory=list)
    efficiency: EfficiencyInfo | None = None
    disqualification_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class CostBreakdown(ContractModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    common: Money
    judge: Money
    per_candidate: dict[str, Money]
    total: Money
    pending_unknown_reserved: Money
    quality: CostQuality
    calls_used: int
    calls_cap: int
    cap: Money | None
    strict: bool
    secondary_calls: dict[str, int] = Field(default_factory=dict, description="Chamadas feitas no modelo economico, por candidato.")
    secondary_savings: dict[str, Money] = Field(
        default_factory=dict, description="Economia estimada vs. fazer as mesmas chamadas no modelo principal (precos versionados)."
    )


class Report(ContractModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    title: str | None
    status: RunStatus
    decision_status: DecisionStatus
    simulated: bool
    replay: bool = False
    generated_at: datetime
    winner_candidate_id: str | None
    co_leaders: list[str] = Field(default_factory=list)
    decision_reasons: list[str] = Field(default_factory=list)
    ranking: list[RankingEntry]
    proposals: list[Proposal]
    critiques: list[Critique]
    verifications: list[Verification]
    evaluations: list[Evaluation]
    evidence_pack_version: int | None
    evidence_gaps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    operational_changes: list[str] = Field(default_factory=list)
    cost: CostBreakdown
    next_steps: list[str] = Field(default_factory=list)
    judge_shuffle_seed: int | None = None
    diversity_observed: dict[str, list[str]] = Field(
        default_factory=dict, description="provider -> modelos efetivamente informados (ou 'unknown')."
    )


ZERO = Decimal("0")
