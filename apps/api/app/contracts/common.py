from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


class ContractModel(BaseModel):
    """Base dos contratos: no schema de saida, campos com default sao obrigatorios (tipos gerados sem opcionais espurios)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


def _money_str(value: Decimal) -> str:
    return format(value.normalize() if value != 0 else Decimal("0"), "f")


# Dinheiro sempre como Decimal; serializado como string para nunca virar float binario.
Money = Annotated[Decimal, PlainSerializer(_money_str, return_type=str, when_used="json")]


class ExecutionMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class Provider(StrEnum):
    MOCK = "mock"
    NEURALAKE = "neuralake"
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


# Provedores reais (gastam creditos). A chave pode vir do servidor ou do navegador de quem usa.
REAL_PROVIDERS = (Provider.NEURALAKE, Provider.OPENAI, Provider.GEMINI, Provider.ANTHROPIC)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
)


class DecisionStatus(StrEnum):
    RANKED = "ranked"
    TIE = "tie"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    INCONCLUSIVE = "inconclusive"
    NOT_EVALUATED = "not_evaluated"


class EvidenceType(StrEnum):
    SOURCE_CLAIM = "source_claim"
    DERIVED_CALCULATION = "derived_calculation"
    ASSUMPTION = "assumption"


class ConstraintKind(StrEnum):
    NUMERIC_MAX = "numeric_max"
    NUMERIC_MIN = "numeric_min"
    QUALITATIVE = "qualitative"


class CheckResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    PENDING = "pending"


class SpecialistKind(StrEnum):
    DOCUMENT_RESEARCH = "document_research"
    CALCULATION = "calculation"


class Role(StrEnum):
    THINKER = "thinker"
    SPECIALIST = "specialist"
    CRITIC = "critic"
    JUDGE = "judge"


class UsageQuality(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class CostQuality(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
