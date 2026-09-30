from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.common import ConstraintKind, ExecutionMode, Money, Provider, Slug, SpecialistKind

MAX_CANDIDATES = 4
MIN_CANDIDATES = 2
MAX_SPECIALIST_TASKS = 2
MAX_TOTAL_CALLS = 32
MAX_CONCURRENT_CALLS = 4
MAX_ATTEMPTS = 2
MAX_SOURCES = 5
MAX_CRITIQUE_ROUNDS = 1

EFFICIENCY_CRITERION_ID = "efficiency"


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: Slug
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    weight: Money = Field(ge=0, le=100)
    computed_by: Literal["judge", "server_efficiency"] = "judge"


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[RubricCriterion] = Field(min_length=1, max_length=12)
    min_score_threshold: Money | None = Field(
        default=None, ge=0, le=100, description="Limiar minimo opcional; default sem limiar universal."
    )

    @model_validator(mode="after")
    def _check(self) -> "Rubric":
        ids = [c.criterion_id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion_id duplicado na rubrica")
        total = sum((c.weight for c in self.criteria), Decimal("0"))
        if total != Decimal("100"):
            raise ValueError(f"os pesos da rubrica devem somar 100 (soma atual: {total})")
        server_computed = [c for c in self.criteria if c.computed_by == "server_efficiency"]
        if len(server_computed) > 1:
            raise ValueError("no maximo um criterio pode ser computado pelo servidor (eficiencia)")
        return self


def default_rubric() -> Rubric:
    return Rubric(
        criteria=[
            RubricCriterion(
                criterion_id="adherence",
                name="Aderencia ao objetivo e as premissas",
                description="Responde ao pedido e respeita as condicoes.",
                weight=Decimal("30"),
            ),
            RubricCriterion(
                criterion_id="evidence_quality",
                name="Qualidade das evidencias",
                description="Fontes pertinentes e afirmacoes sustentadas.",
                weight=Decimal("25"),
            ),
            RubricCriterion(
                criterion_id="reasoning",
                name="Consistencia do raciocinio apresentado",
                description="Justificativa coerente, sem contradicoes ou inferencias indevidas.",
                weight=Decimal("20"),
            ),
            RubricCriterion(
                criterion_id="completeness",
                name="Completude",
                description="Cobre entregaveis, dependencias e passos necessarios.",
                weight=Decimal("10"),
            ),
            RubricCriterion(
                criterion_id=EFFICIENCY_CRITERION_ID,
                name="Eficiencia da execucao",
                description="Consumo da equipe em relacao a cota: 10 * max(0, 1 - cost/quota). Calculado pelo servidor.",
                weight=Decimal("10"),
                computed_by="server_efficiency",
            ),
            RubricCriterion(
                criterion_id="uncertainty",
                name="Tratamento de incertezas",
                description="Explicita limites, hipoteses e dados ausentes.",
                weight=Decimal("5"),
            ),
        ]
    )


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: Slug
    description: str = Field(min_length=1, max_length=500)
    kind: ConstraintKind
    metric_key: Slug | None = Field(
        default=None, description="Metrica que a proposta deve declarar (ex.: monthly_cost_brl)."
    )
    limit: Money | None = None
    unit: str | None = Field(default=None, max_length=32)
    mandatory: bool = True

    @model_validator(mode="after")
    def _check(self) -> "Constraint":
        if self.kind in (ConstraintKind.NUMERIC_MAX, ConstraintKind.NUMERIC_MIN):
            if self.metric_key is None or self.limit is None or not self.unit:
                raise ValueError(f"restricao numerica '{self.constraint_id}' exige metric_key, limit e unit")
        return self

    @property
    def verifiable(self) -> bool:
        return self.kind != ConstraintKind.QUALITATIVE


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    total_cap: Money | None = Field(default=None, gt=0, description="Teto monetario. Obrigatorio em modo real.")
    strict: bool = Field(default=True, description="Teto estrito (bloqueia chamadas sem cobertura) ou indicativo.")
    common_share_pct: Money = Field(
        default=Decimal("30"), ge=5, le=80, description="Percentual do teto para a cota comum (evidencias + Judge)."
    )
    max_total_calls: int = Field(default=MAX_TOTAL_CALLS, ge=4, le=MAX_TOTAL_CALLS)
    max_concurrent_calls: int = Field(default=2, ge=1, le=MAX_CONCURRENT_CALLS)
    run_deadline_s: int = Field(default=300, ge=10, le=3600)
    call_timeout_s: int = Field(default=60, ge=1, le=300)
    max_attempts_per_call: int = Field(default=MAX_ATTEMPTS, ge=1, le=MAX_ATTEMPTS)


class CandidateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Slug | None = Field(default=None, description="Gerado pelo servidor (c1..c4) se ausente.")
    name: str = Field(min_length=1, max_length=60)
    preset: Literal["balanced", "cost", "robust"] | None = None
    instructions: str = Field(default="", max_length=6000, description="Instrucoes estrategicas privadas do pensante.")
    provider: Provider = Provider.MOCK
    model_option: str = Field(default="mock-default", max_length=64)
    allowed_specialists: list[SpecialistKind] = Field(
        default_factory=lambda: [SpecialistKind.DOCUMENT_RESEARCH, SpecialistKind.CALCULATION]
    )
    max_specialist_tasks: int = Field(default=MAX_SPECIALIST_TASKS, ge=0, le=MAX_SPECIALIST_TASKS)
    max_output_tokens: int = Field(default=2000, ge=200, le=8000)
    quota_weight: Money = Field(default=Decimal("1"), gt=0, description="Peso relativo da cota; default igual.")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class JudgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider = Provider.MOCK
    model_option: str = Field(default="mock-default", max_length=64)
    max_output_tokens: int = Field(default=3000, ge=300, le=8000)


class ChallengeConfig(BaseModel):
    """Configuracao completa de um desafio. Depois de validada e resolvida vira o snapshot imutavel do Run."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=160)
    objective: str = Field(min_length=10, max_length=8000)
    context: str = Field(default="", max_length=20000)
    source_ids: list[str] = Field(default_factory=list, max_length=MAX_SOURCES)
    constraints: list[Constraint] = Field(default_factory=list, max_length=20)
    rubric: Rubric = Field(default_factory=default_rubric)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    mode: ExecutionMode = ExecutionMode.MOCK
    config_mode: Literal["auto", "manual"] = "auto"
    candidate_count: int = Field(default=2, ge=MIN_CANDIDATES, le=MAX_CANDIDATES)
    candidates: list[CandidateConfig] | None = Field(default=None, max_length=MAX_CANDIDATES)
    judge: JudgeConfig | None = None
    critique_rounds: int = Field(default=1, ge=0, le=MAX_CRITIQUE_ROUNDS)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    mock_scenario: str = Field(default="default", max_length=64, description="Somente em modo mock.")
    tags: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _check(self) -> "ChallengeConfig":
        ids = [c.constraint_id for c in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint_id duplicado")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids duplicados")
        if self.config_mode == "manual":
            if not self.candidates or len(self.candidates) < MIN_CANDIDATES:
                raise ValueError("modo manual exige entre 2 e 4 candidatos")
        if self.candidates and len(self.candidates) < MIN_CANDIDATES:
            raise ValueError("entre 2 e 4 candidatos")
        if self.candidates:
            names = [c.name.strip().lower() for c in self.candidates]
            if len(names) != len(set(names)):
                raise ValueError("nomes de candidatos devem ser unicos")
            given_ids = [c.candidate_id for c in self.candidates if c.candidate_id]
            if len(given_ids) != len(set(given_ids)):
                raise ValueError("candidate_id duplicado")
        if self.mode == ExecutionMode.REAL and self.budget.total_cap is None:
            raise ValueError("modo real exige budget.total_cap explicito")
        if self.mode == ExecutionMode.REAL and self.mock_scenario != "default":
            raise ValueError("mock_scenario so e aceito em modo mock")
        return self
