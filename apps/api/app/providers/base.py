from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.contracts.common import UsageQuality


class ProviderError(Exception):
    """Erro tipado de provedor. `usage_known=False` significa consumo desconhecido (ex.: timeout)."""

    def __init__(self, error_type: str, message: str, *, retryable: bool = False, usage_known: bool = True) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable
        self.usage_known = usage_known


class GenerateRequest(BaseModel):
    role: str
    stage: str
    candidate_id: str | None = None
    option: str
    system: str
    user: str
    schema_name: str
    json_schema: dict[str, Any]
    max_output_tokens: int
    timeout_s: float
    seed: int
    attempt: int = 1
    repair_of: str | None = Field(default=None, description="Conteudo invalido anterior, quando for reparacao.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Contexto estruturado (usado pelo mock).")

    def prompt_chars(self) -> int:
        return len(self.system) + len(self.user) + (len(self.repair_of) if self.repair_of else 0)


class Usage(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    quality: UsageQuality


class GenerateResult(BaseModel):
    content: str
    usage: Usage
    reported_model: str | None
    request_id: str | None
    latency_ms: int
    finish_reason: str | None = None


class ProviderAdapter(Protocol):
    name: str

    async def generate(self, request: GenerateRequest) -> GenerateResult: ...


def estimate_tokens(chars: int) -> int:
    """Estimativa conservadora (~3.5 chars/token) usada apenas para reservar orcamento."""
    return max(1, (chars * 2 + 6) // 7)
