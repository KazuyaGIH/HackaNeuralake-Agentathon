from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from app.contracts.challenge import ChallengeConfig
from app.contracts.common import ContractModel, CostQuality, DecisionStatus, ExecutionMode, Money, Provider, RunStatus, UsageQuality


class SourceCreateResponse(ContractModel):
    source_id: str
    title: str
    media_type: str
    size_bytes: int
    sha256: str
    extraction_status: str
    pages: int | None
    chars: int
    warnings: list[str]


class CatalogModelOption(ContractModel):
    provider: Provider
    option: str
    label: str
    kind: str = Field(description="'fixed_model' ou 'routing_capability'")
    capabilities: list[str]
    max_context_tokens: int | None
    max_output_tokens: int
    supports_json_mode: bool
    price_input_per_1m: Money | None
    price_output_per_1m: Money | None
    price_version: str
    price_known: bool
    enabled: bool
    unavailable_reason: str | None = None


class CatalogPreset(ContractModel):
    preset: str
    label: str
    description: str
    instructions: str
    model_option_by_provider: dict[str, str]
    secondary_by_provider: dict[str, str] = Field(default_factory=dict)
    allowed_specialists: list[str]
    max_specialist_tasks: int


class CatalogJudgePersona(ContractModel):
    persona: str
    name: str
    description: str
    instructions: str
    rubric: dict[str, Any]


class CatalogResponse(ContractModel):
    app_version: str
    catalog_version: str
    modes: list[ExecutionMode]
    providers: dict[str, dict[str, Any]]
    model_options: list[CatalogModelOption]
    specialists: list[dict[str, Any]]
    presets: list[CatalogPreset]
    limits: dict[str, Any]
    default_rubric: dict[str, Any]
    judge_personas: list[CatalogJudgePersona] = Field(default_factory=list)
    mock_scenarios: list[str]
    demo_preset_available: bool


class RunCreateResponse(ContractModel):
    run_id: str
    status: RunStatus
    created: bool
    links: dict[str, str]


class RunSummary(ContractModel):
    run_id: str
    title: str | None
    status: RunStatus
    decision_status: DecisionStatus
    mode: ExecutionMode
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    candidate_count: int
    parent_run_id: str | None
    simulated: bool


class BudgetBucketView(ContractModel):
    bucket_key: str
    cap: Money | None
    spent: Money
    reserved: Money
    provisioned: Money
    pending_unknown: Money
    calls_used: int
    calls_provisioned: int


class CallUsageView(ContractModel):
    call_id: str
    logical_call_id: str
    attempt: int
    stage: str
    role: str
    candidate_id: str | None
    provider: str
    requested_option: str
    reported_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    usage_quality: UsageQuality
    cost: Money | None
    cost_quality: CostQuality
    reserved: Money
    latency_ms: int | None
    request_id: str | None
    status: str
    error_type: str | None
    created_at: datetime


class RunEventView(ContractModel):
    seq: int
    type: str
    ts: datetime
    run_id: str
    payload: dict[str, Any]


class RunMetrics(ContractModel):
    calls_used: int
    calls_cap: int
    spent: Money
    reserved: Money
    pending_unknown: Money
    cap: Money | None
    currency: str
    cost_quality: CostQuality
    elapsed_s: float | None
    deadline_s: int


class RunDetail(ContractModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    owner_id: str
    title: str | None
    status: RunStatus
    decision_status: DecisionStatus
    mode: ExecutionMode
    simulated: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    seed: int
    app_version: str
    snapshot: ChallengeConfig
    snapshot_hashes: dict[str, str]
    parent_run_id: str | None
    error: str | None
    metrics: RunMetrics
    budget_buckets: list[BudgetBucketView]
    artifacts: dict[str, Any] = Field(description="Artefatos publicos ja produzidos, agrupados por tipo.")
    last_event_seq: int
