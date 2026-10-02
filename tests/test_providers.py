"""Multiplos provedores (OpenAI, Gemini, Claude) sem rede: formato das requisicoes, leitura das respostas e uma
arena que mistura provedores (adaptadores substituidos pelo mock; nenhuma chamada paga)."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.providers.anthropic_adapter import AnthropicAdapter
from app.providers.base import GenerateRequest, ProviderError
from app.providers.mock import MockAdapter
from app.providers.openai_compat import GeminiAdapter, OpenAIAdapter
from tests.conftest import app_client, create_run, demo_config, make_settings, wait_terminal


def _req(**kw: Any) -> GenerateRequest:
    base = dict(role="thinker", stage="propose", option="x", system="sys", user="user", schema_name="proposal", json_schema={}, max_output_tokens=900, timeout_s=5, seed=1)
    base.update(kw)
    return GenerateRequest(**base)


def test_openai_and_gemini_payloads() -> None:
    o = OpenAIAdapter(api_key="k", base_url="https://api.openai.com/v1").build_payload(_req(option="gpt-6-luna"))
    assert o["max_completion_tokens"] == 900 and "max_tokens" not in o and "temperature" not in o
    g = GeminiAdapter(api_key="k", base_url="https://generativelanguage.googleapis.com/v1beta/openai").build_payload(_req(option="gemini-3.8-flash"))
    assert g["max_tokens"] == 900 and g["temperature"] == 0.2 and g["messages"][0]["role"] == "system"


class _FakeMessages:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> Any:
        self.params = params
        return self.reply


class _FakeAnthropic:
    def __init__(self, reply: Any) -> None:
        self.messages = _FakeMessages(reply)

    def with_options(self, **_: Any) -> "_FakeAnthropic":
        return self


def _msg(stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text='{"ok": true}')],
        usage=SimpleNamespace(input_tokens=120, output_tokens=40), model="claude-haiku-4-5", stop_reason=stop, id="msg_1", stop_details=None,
    )


async def test_anthropic_adapter_params_and_response() -> None:
    fake = _FakeAnthropic(_msg())
    out = await AnthropicAdapter(api_key="k", client=fake).generate(_req(option="claude-opus-5-5", repair_of="{ruim", repair_error="faltou campo"))
    p = fake.messages.params
    assert p["system"] == "sys" and p["max_tokens"] == 900 and p["output_config"] == {"effort": "low"}
    assert [m["role"] for m in p["messages"]] == ["user", "assistant", "user"] and "thinking" not in p
    assert out.content == '{"ok": true}' and out.usage.input_tokens == 120 and out.reported_model == "claude-haiku-4-5"
    # Haiku 4.5 nao recebe effort.
    fake2 = _FakeAnthropic(_msg())
    await AnthropicAdapter(api_key="k", client=fake2).generate(_req(option="claude-haiku-4-5"))
    assert "output_config" not in fake2.messages.params


async def test_anthropic_refusal_is_typed_error() -> None:
    with pytest.raises(ProviderError) as e:
        await AnthropicAdapter(api_key="k", client=_FakeAnthropic(_msg("refusal"))).generate(_req(option="claude-opus-5-5"))
    assert e.value.error_type == "refusal" and not e.value.retryable


async def test_arena_mixing_providers(tmp_path) -> None:  # noqa: ANN001
    settings = make_settings(tmp_path, openai_api_key="k1", gemini_api_key="k2", anthropic_api_key="k3")
    mock = MockAdapter()
    async with app_client(settings, adapters={"mock": mock, "openai": mock, "gemini": mock, "anthropic": mock}) as (_app, client):
        catalog = (await client.get("/api/v1/catalog")).json()
        assert {"openai", "gemini", "anthropic"} <= set(catalog["providers"]) and catalog["providers"]["anthropic"]["enabled"] is True
        assert any(o["provider"] == "anthropic" and o["option"] == "claude-opus-5-5" and o["price_known"] for o in catalog["model_options"])
        cfg = await demo_config(client, mode="real")
        cfg["budget"]["total_cap"] = "2.00"
        cfg["config_mode"] = "manual"
        cfg["candidates"] = [
            {"name": "Time OpenAI", "provider": "openai", "model_option": "gpt-6.1-sol", "secondary_model_option": "gpt-6-luna"},
            {"name": "Time Claude", "provider": "anthropic", "model_option": "claude-opus-5-5", "secondary_model_option": "claude-haiku-4-5"},
        ]
        cfg["real_provider"] = "gemini"  # juiz sem modelo escolhido usa o padrao do Gemini
        run_id = await create_run(client, cfg)
        detail = await wait_terminal(client, run_id)
        assert detail["status"] in ("completed", "partial"), detail["error"]
        calls = detail["artifacts"]["calls"]
        assert {c["provider"] for c in calls if c["candidate_id"] == "c1"} == {"openai"}
        assert {c["provider"] for c in calls if c["candidate_id"] == "c2"} == {"anthropic"}
        assert {(c["provider"], c["requested_option"]) for c in calls if c["role"] == "judge"} == {("gemini", "gemini-2.5-pro")}
        report = (await client.get(f"/api/v1/runs/{run_id}/report")).json()
        assert float(report["cost"]["total"]) > 0 and report["cost"]["quality"] == "estimated"
