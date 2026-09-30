from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.common import (
    CheckResult,
    CostQuality,
    DecisionStatus,
    Eligibility,
    EvidenceType,
    Money,
    RunStatus,
    SpecialistKind,
)

# ----------------------------------------------------------------------------- evidencias


class EvidenceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class CalcInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    value: Money
    unit: str | None = Field(default=None, max_length=32)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class Derivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str
    formula: str
    inputs: list[CalcInput]
    result: Money
    unit: str
    input_evidence_ids: list[str]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str | None = None
    type: EvidenceType
    excerpt: str = Field(max_length=4000)
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    provenance: str
    derivation: Derivation | None = None


class SourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    media_type: str
    pages: int | None = None
    chars: int
    sha256: str
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
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


class CalculationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str = Field(min_length=1, max_length=64)
    inputs: list[CalcInput] = Field(min_length=1, max_length=8)
    unit: str = Field(min_length=1, max_length=32)


class SpecialistTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    kind: str = Field(max_length=64, description="Competencia solicitada; validada contra o catalogo permitido.")
    competence: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=600)
    query: str | None = Field(default=None, max_length=600)
    calculation: CalculationSpec | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=2)


class ThinkerPlanOutput(BaseModel):
    """Saida estruturada esperada do pensante na fase de planejamento."""

    model_config = ConfigDict(extra="forbid")

    strategy_summary: str = Field(max_length=2000)
    tasks: list[SpecialistTask] = Field(default_factory=list, max_length=6)


class PlanRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    reason: str


class PlanValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_task_ids: list[str]
    rejected: list[PlanRejection]
    adjusted: bool


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    strategy_summary: str
    tasks: list[SpecialistTask]
    validation: PlanValidation


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"] = "medium"


class ResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=8)


class TaskResult(BaseModel):
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


# ----------------------------------------------------------------------------- propostas e critica


class ProposalMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Money
    unit: str = Field(max_length=32)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class ProposalOutput(BaseModel):
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


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(max_length=1000)
    severity: Literal["low", "medium", "high"] = "medium"
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    constraint_id: str | None = None


class CritiqueOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objections: list[Objection] = Field(default_factory=list, max_length=12)
    strengths: list[str] = Field(default_factory=list, max_length=8)


class Critique(CritiqueOutput):
    author_candidate_id: str
    target_candidate_id: str
    target_version: int
    call_ids: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- verificacao e avaliacao


class ConstraintCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    mandatory: bool
    result: CheckResult
    observed_value: Money | None = None
    unit: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    proposal_version: int
    checks: list[ConstraintCheck]
    valid_evidence_ids: list[str]
    invalid_evidence_ids: list[str]
    eligibility: Eligibility
    reasons: list[str] = Field(default_factory=list)


class CriterionGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    grade: Money = Field(ge=0, le=10)
    justification: str = Field(max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class JudgeProposalEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Rotulo anonimo da proposta (ex.: P1).")
    grades: list[CriterionGrade]
    objections: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluations: list[JudgeProposalEvaluation]


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    proposal_version: int
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


class EfficiencyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost: Money | None
    quota: Money | None
    grade: Money | None
    cost_quality: CostQuality


class RankingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_name: str
    proposal_version: int | None
    score_0_100: Money | None
    rank: int | None
    co_leader: bool = False
    eligibility: Eligibility
    grades: dict[str, Money] = Field(default_factory=dict)
    efficiency: EfficiencyInfo | None = None
    disqualification_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class CostBreakdown(BaseModel):
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


class Report(BaseModel):
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
