import json
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
    repair_error: str | None = Field(default=None, description="Motivo da invalidez anterior (schema/semantica).")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Contexto estruturado (usado pelo mock).")

    def schema_text(self) -> str:
        """JSON Schema compacto (sem titulos) que o modelo real precisa seguir; sem ele o modelo inventa os campos."""
        return json.dumps(_strip_titles(self.json_schema), ensure_ascii=False, separators=(",", ":"))

    def system_with_schema(self) -> str:
        if not self.json_schema:
            return self.system
        return (
            f"{self.system}\n\nFORMATO OBRIGATORIO DA RESPOSTA: um unico objeto JSON que siga exatamente o JSON Schema abaixo. "
            "Use exatamente os nomes de campos do schema (em ingles, como estao), preencha todos os campos obrigatorios, "
            "nao crie campos extras, nao use markdown nem texto fora do JSON. Seja conciso para a resposta caber no limite.\n"
            f"JSON Schema: {self.schema_text()}"
        )

    def prompt_chars(self) -> int:
        schema = len(self.schema_text()) + 400 if self.json_schema else 0
        return len(self.system) + len(self.user) + schema + (len(self.repair_of) if self.repair_of else 0)


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


def _strip_titles(node: Any) -> Any:
    # Remove so os "title" gerados pelo Pydantic (texto); um campo chamado "title" (dict) e mantido.
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def estimate_tokens(chars: int) -> int:
    """Estimativa conservadora (~3.5 chars/token) usada apenas para reservar orcamento."""
    return max(1, (chars * 2 + 6) // 7)
