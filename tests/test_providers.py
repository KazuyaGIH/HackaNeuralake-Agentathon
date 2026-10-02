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
    assert g["reasoning_effort"] == "low" and o["reasoning_effort"] == "low"


def test_real_models_receive_the_json_schema() -> None:
    # Sem o schema no prompt, os modelos reais inventavam os nomes dos campos (proposta rejeitada).
    from app.contracts.artifacts import Proposal

    req = _req(json_schema=Proposal.model_json_schema())
    system = OpenAIAdapter(api_key="k", base_url="https://x").build_payload(req)["messages"][0]["content"]
    assert system.startswith("sys") and '"recommendation"' in system and "FORMATO OBRIGATORIO" in system
    assert '"title":"Proposal"' not in system  # titulos do Pydantic removidos; o campo "title" continua
    assert '"title":{' in system
    assert req.prompt_chars() > len("sys") + len("user") + len(req.schema_text())


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
    assert p["system"] == "sys" and p["max_tokens"] == 900  # sem schema no pedido, o sistema fica igual and p["output_config"] == {"effort": "low"}
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


def test_extra_fields_are_dropped_instead_of_failing() -> None:
    # NeuraLake real devolveu "evidence_ids" dentro de uma tarefa do plano: antes o plano inteiro era rejeitado.
    from pydantic import BaseModel, ConfigDict

    from app.orchestration.coordinator import _parse

    class Task(BaseModel):
        model_config = ConfigDict(extra="forbid")
        task_id: str

    class Plan(BaseModel):
        model_config = ConfigDict(extra="forbid")
        tasks: list[Task]

    parsed, err = _parse('{"tasks": [{"task_id": "t1"}, {"task_id": "t2", "evidence_ids": ["ev-1"]}], "extra": 1}', Plan)
    assert err == "" and parsed is not None and [t.task_id for t in parsed.tasks] == ["t1", "t2"]
    parsed, err = _parse('{"tasks": [{"evidence_ids": []}]}', Plan)
    assert parsed is None and "task_id" in err


def test_thinking_headroom_is_reserved_and_shown(tmp_path) -> None:  # noqa: ANN001
    # Modelos que pensam ganham espaco extra de saida, e a reserva do teto cobre esse espaco; Claude e mock nao.
    from app.budget.ledger import Ledger
    from app.budget.prices import load_price_table
    from app.providers.registry import thinking_headroom

    assert thinking_headroom("openai", "gpt-5-mini") == 2048 and thinking_headroom("gemini", "gemini-2.5-flash-lite") == 1024
    assert thinking_headroom("anthropic", "claude-opus-5-5") == 0 and thinking_headroom("mock", "mock-default") == 0
    assert thinking_headroom("neuralake", "reasoning") == 2048 and thinking_headroom("neuralake", "text") == 0
    ledger = Ledger(load_price_table(make_settings(tmp_path).neuralake_prices_file), strict=True)
    assert ledger.plan("openai", "gpt-5-mini", 3500, 2000, []).est_output_tokens == 4048
    assert ledger.plan("anthropic", "claude-haiku-4-5", 3500, 2000, []).est_output_tokens == 2000
