"""AnthropicAdapter: Claude pela Messages API, via SDK oficial (`anthropic`).

- Thinking: nos modelos atuais (Opus 5.5 / Sonnet 5.5) o raciocinio e sempre adaptativo e conta como saida;
  usamos `output_config.effort="low"` para as tarefas estruturadas da arena caberem no limite de saida
  reservado no orcamento. Haiku 4.5 nao aceita `effort` e roda sem thinking.
- Fallback de modelo em recusa NAO e habilitado: o projeto exige que o modelo usado seja o configurado e
  registrado (sem troca silenciosa). Recusa (`stop_reason == "refusal"`) vira erro tipado.
- Saida JSON: pedida pelo prompt (o sistema ja valida e repara); `output_config.format` nao e usado porque os
  schemas da arena usam restricoes (maxLength, pattern) fora do subconjunto aceito.
"""

import time
from typing import Any

import anthropic

from app.contracts.common import UsageQuality
from app.providers.base import GenerateRequest, GenerateResult, ProviderError, Usage

# Modelos que aceitam `output_config.effort` (Haiku 4.5 nao aceita).
_EFFORT_MODELS = ("claude-opus-", "claude-sonnet-", "claude-fable-")


class AnthropicAdapter:
    name = "anthropic"
    label = "Claude"

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if not api_key:
            raise ValueError("AnthropicAdapter exige api_key (AGENTATHON_ANTHROPIC_API_KEY)")
        # max_retries=0: tentativas e reparacoes sao controladas (e contabilizadas) pelo coordenador.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    @staticmethod
    def build_messages(request: GenerateRequest) -> list[dict[str, str]]:
        messages = [{"role": "user", "content": request.user}]
        if request.repair_of is not None:
            messages.append({"role": "assistant", "content": request.repair_of})
            messages.append({
                "role": "user",
                "content": (
                    "A resposta anterior nao seguiu o schema exigido"
                    + (f": {request.repair_error}" if request.repair_error else "")
                    + ". Responda novamente SOMENTE com JSON valido conforme o schema, sem texto adicional."
                ),
            })
        return messages

    def build_params(self, request: GenerateRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": request.option,
            "max_tokens": request.max_output_tokens,
            "system": request.system_with_schema(),
            "messages": self.build_messages(request),
        }
        if request.option.startswith(_EFFORT_MODELS):
            params["output_config"] = {"effort": "low"}
        return params

    async def generate(self, request: GenerateRequest) -> GenerateResult:
        started = time.monotonic()
        try:
            msg = await self._client.with_options(timeout=request.timeout_s).messages.create(**self.build_params(request))
        except anthropic.AuthenticationError as exc:
            raise ProviderError("auth", "Claude recusou a chave (401). Confira a chave conectada.", retryable=False, usage_known=True) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("auth", "Claude: a chave nao tem permissao para este modelo (403).", retryable=False, usage_known=True) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate_limit", "Claude: limite de requisicoes (429)", retryable=True, usage_known=True) from exc
        except anthropic.BadRequestError as exc:
            body = str(exc)[:500]
            kind = "context_length" if "context" in body.lower() and "length" in body.lower() else "bad_request"
            raise ProviderError(kind, f"Claude: requisicao rejeitada (400): {body}", retryable=False, usage_known=True) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("timeout", f"timeout na chamada Claude ({request.timeout_s:.0f}s); consumo desconhecido", retryable=True, usage_known=False) from exc
        except anthropic.APIStatusError as exc:
            retry = exc.status_code >= 500
            raise ProviderError("server_error" if retry else "bad_request", f"Claude: erro {exc.status_code}: {str(exc)[:300]}", retryable=retry, usage_known=not retry) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("network", f"falha de conexao com Claude: {exc}", retryable=True, usage_known=True) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if msg.stop_reason == "refusal":
            category = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ProviderError("refusal", f"Claude recusou a tarefa (categoria: {category or 'n/d'})", retryable=False, usage_known=True)
        # Blocos de thinking chegam vazios por padrao; a resposta util esta nos blocos de texto.
        content = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        in_tok = getattr(msg.usage, "input_tokens", None)
        out_tok = getattr(msg.usage, "output_tokens", None)
        if isinstance(in_tok, int) and isinstance(out_tok, int):
            usage = Usage(input_tokens=in_tok, output_tokens=out_tok, quality=UsageQuality.PROVIDER_REPORTED)
        else:
            usage = Usage(input_tokens=None, output_tokens=None, quality=UsageQuality.UNKNOWN)
        return GenerateResult(
            content=content, usage=usage, reported_model=getattr(msg, "model", None), request_id=getattr(msg, "_request_id", None) or getattr(msg, "id", None),
            latency_ms=latency_ms, finish_reason=msg.stop_reason,
        )
