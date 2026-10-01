"""NeuraLakeAdapter: API OpenAI-compatible (chat/completions) com opcoes de roteamento por capacidade.

Referencia publica consultada em 30/09/2026: base https://api.neuralake.cloud/v1, `model` em
{auto, text, code, reasoning, reasoning-pro, multimodal}. Parametros, usage e recursos NAO foram
validados contra o ambiente real nesta implementacao; ver README (teste real pendente).
Nunca faz fallback para mock, outro modelo ou outro provedor.
"""

import json
import time
from typing import Any

import httpx

from app.contracts.common import UsageQuality
from app.providers.base import GenerateRequest, GenerateResult, ProviderError, Usage


class NeuraLakeAdapter:
    name = "neuralake"

    def __init__(self, api_key: str, base_url: str, *, json_mode: bool = False, client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ValueError("NeuraLakeAdapter exige api_key (AGENTATHON_NEURALAKE_API_KEY)")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.json_mode = json_mode
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", "Accept": "application/json"}

    @staticmethod
    def build_messages(request: GenerateRequest) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}]
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

    def build_payload(self, request: GenerateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.option,
            "messages": self.build_messages(request),
            "max_tokens": request.max_output_tokens,
            "temperature": 0.2,
            "stream": False,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def generate(self, request: GenerateRequest) -> GenerateResult:
        payload = self.build_payload(request)
        started = time.monotonic()
        timeout = httpx.Timeout(request.timeout_s, connect=min(10.0, request.timeout_s))
        try:
            if self._client is not None:
                resp = await self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers(), timeout=timeout)
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
        except httpx.ConnectError as exc:
            raise ProviderError("network", f"falha de conexao com NeuraLake: {exc}", retryable=True, usage_known=True) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"timeout na chamada NeuraLake ({request.timeout_s:.0f}s); consumo desconhecido", retryable=True, usage_known=False) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network", f"erro HTTP: {exc}", retryable=False, usage_known=False) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")

        if resp.status_code in (401, 403):
            raise ProviderError("auth", "NeuraLake recusou a credencial (401/403). Verifique AGENTATHON_NEURALAKE_API_KEY.", retryable=False, usage_known=True)
        if resp.status_code == 429:
            raise ProviderError("rate_limit", "NeuraLake: limite de requisicoes (429)", retryable=True, usage_known=True)
        if resp.status_code in (408, 502, 503, 504) or resp.status_code >= 500:
            raise ProviderError("server_error", f"NeuraLake: erro do servidor ({resp.status_code})", retryable=True, usage_known=False)
        if resp.status_code >= 400:
            body = resp.text[:500]
            kind = "context_length" if "context" in body.lower() and "length" in body.lower() else "bad_request"
            raise ProviderError(kind, f"NeuraLake: requisicao rejeitada ({resp.status_code}): {body}", retryable=False, usage_known=True)
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("invalid_response", "NeuraLake: corpo nao e JSON", retryable=True, usage_known=False) from exc
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid_response", f"NeuraLake: resposta sem choices[0].message.content: {str(data)[:300]}", retryable=True, usage_known=False) from exc
        usage_raw = data.get("usage") or {}
        in_tok = usage_raw.get("prompt_tokens")
        out_tok = usage_raw.get("completion_tokens")
        if isinstance(in_tok, int) and isinstance(out_tok, int):
            usage = Usage(input_tokens=in_tok, output_tokens=out_tok, quality=UsageQuality.PROVIDER_REPORTED)
        else:
            usage = Usage(input_tokens=None, output_tokens=None, quality=UsageQuality.UNKNOWN)
        return GenerateResult(
            content=content, usage=usage, reported_model=data.get("model") or None, request_id=data.get("id") or request_id,
            latency_ms=latency_ms, finish_reason=(data["choices"][0].get("finish_reason") if data.get("choices") else None),
        )
