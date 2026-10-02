"""NeuraLakeAdapter e caminho do modo real sem rede: transporte HTTP falso (nenhuma chamada paga em testes)."""

import json
import re
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.agents.prompts import CRITIC_SYSTEM, JUDGE_SYSTEM, SPECIALIST_SYSTEM
from app.budget.prices import load_price_table
from app.config import REPO_DIR
from app.contracts.common import UsageQuality
from app.providers.base import GenerateRequest, ProviderError
from app.providers.neuralake import NeuraLakeAdapter
from tests.conftest import app_client, create_run, demo_config, make_settings, wait_terminal

PRICES = REPO_DIR / "fixtures" / "prices" / "neuralake.public-2026-09-30.json"


def _req(**kw: Any) -> GenerateRequest:
    base = dict(role="thinker", stage="propose", option="auto", system="sys", user="user", schema_name="proposal", json_schema={}, max_output_tokens=100, timeout_s=5, seed=1)
    base.update(kw)
    return GenerateRequest(**base)


def _adapter(handler, **kw: Any) -> NeuraLakeAdapter:  # noqa: ANN001
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return NeuraLakeAdapter(api_key="k", base_url="https://api.example.test/v1", client=client, **kw)


async def test_success_parses_usage_model_and_request_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "chatcmpl-1", "model": "router/text-v9", "choices": [{"message": {"role": "assistant", "content": "{\"a\": 1}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 120, "completion_tokens": 7}})

    out = await _adapter(handler).generate(_req())
    assert seen["auth"] == "Bearer k" and seen["payload"]["model"] == "auto" and seen["payload"]["stream"] is False
    assert "response_format" not in seen["payload"]
    assert out.content == '{"a": 1}' and out.usage.input_tokens == 120 and out.usage.output_tokens == 7
    assert out.usage.quality == UsageQuality.PROVIDER_REPORTED and out.reported_model == "router/text-v9" and out.request_id == "chatcmpl-1"


async def test_repair_adds_assistant_and_user_messages_and_json_mode_flag() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    out = await _adapter(handler, json_mode=True).generate(_req(repair_of="nao json", repair_error="JSON invalido", attempt=2))
    roles = [m["role"] for m in seen["payload"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"] and "JSON invalido" in seen["payload"]["messages"][-1]["content"]
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    assert out.usage.quality == UsageQuality.UNKNOWN  # usage ausente nao vira zero


@pytest.mark.parametrize(
    ("status", "error_type", "retryable", "usage_known"),
    [(401, "auth", False, True), (403, "auth", False, True), (429, "rate_limit", True, True), (503, "server_error", True, False), (400, "bad_request", False, True)],
)
async def test_http_errors_are_typed(status: int, error_type: str, retryable: bool, usage_known: bool) -> None:
    adapter = _adapter(lambda r: httpx.Response(status, json={"error": "x"}))
    with pytest.raises(ProviderError) as exc:
        await adapter.generate(_req())
    assert exc.value.error_type == error_type and exc.value.retryable is retryable and exc.value.usage_known is usage_known


async def test_timeout_means_unknown_usage_and_bad_body_is_invalid_response() -> None:
    def timeout(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderError) as exc:
        await _adapter(timeout).generate(_req())
    assert exc.value.error_type == "timeout" and exc.value.usage_known is False
    with pytest.raises(ProviderError) as exc2:
        await _adapter(lambda r: httpx.Response(200, content=b"<html>")).generate(_req())
    assert exc2.value.error_type == "invalid_response"
    with pytest.raises(ValueError):
        NeuraLakeAdapter(api_key="", base_url="x")


def test_public_price_table_and_auto_ceiling() -> None:
    table = load_price_table(PRICES)
    assert table.known("neuralake", "text") and not table.known("neuralake", "auto")
    ceiling = table.max_price("neuralake", ["auto", "text", "code", "reasoning", "reasoning-pro", "multimodal"])
    assert ceiling is not None and ceiling.input_per_1m == Decimal("2.00") and ceiling.output_per_1m == Decimal("4.50")
    assert "public-page" in table.version


# --------------------------------------------------------------------------- caminho real com servidor falso


class FakeNeuraLake:
    """Servidor HTTP falso OpenAI-compatible: responde JSON valido por papel, sem se ancorar em metadata."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.calls.append(payload)
        system = payload["messages"][0]["content"]
        user = payload["messages"][1]["content"]
        ev_ids = list(dict.fromkeys(re.findall(r"\[(ev-[0-9a-f]{6}-\d{3})\]", user)))
        if system == JUDGE_SYSTEM:
            labels = re.findall(r'"label": "(P\d+)"', user)
            crit = re.findall(r'"criterion_id": "([a-z_]+)"', user.split("PACOTE DE EVIDENCIAS")[0])
            content = {"evaluations": [{"label": lb, "grades": [{"criterion_id": c, "grade": "7", "justification": "ok", "evidence_ids": ev_ids[:1]} for c in dict.fromkeys(crit)], "objections": [], "assumptions": [], "uncertainties": ["fake"]} for lb in dict.fromkeys(labels)]}
        elif system == CRITIC_SYSTEM:
            content = {"objections": [{"point": "premissa fragil", "severity": "low", "evidence_ids": ev_ids[:1]}], "strengths": ["cita evidencias"]}
        elif system == SPECIALIST_SYSTEM:
            content = {"findings": [{"claim": "achado", "evidence_ids": ev_ids[:1]}], "gaps": []}
        elif "PLANEJE" in user:
            content = {"strategy_summary": "plano fake", "tasks": [{"task_id": "t1", "kind": "document_research", "query": "custo mensal"}]}
        else:
            content = {"title": "Proposta fake", "recommendation": "recomendacao fake", "steps": ["s1"], "metrics": {}, "evidence_ids": ev_ids[:3]}
        text = json.dumps(content, ensure_ascii=False)
        return httpx.Response(200, json={"id": f"chatcmpl-{len(self.calls)}", "model": f"router/{payload['model']}-v1", "choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": len(system + user) // 4, "completion_tokens": len(text) // 4}})


async def test_real_mode_end_to_end_with_fake_neuralake(tmp_path) -> None:  # noqa: ANN001
    fake = FakeNeuraLake()
    adapter = NeuraLakeAdapter(api_key="k", base_url="https://api.example.test/v1", client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    settings = make_settings(tmp_path, neuralake_api_key="k", neuralake_prices_file=PRICES)
    async with app_client(settings, adapters={"mock": __import__("app.providers.mock", fromlist=["MockAdapter"]).MockAdapter(), "neuralake": adapter}) as (_app, client):
        catalog = (await client.get("/api/v1/catalog")).json()
        assert catalog["modes"] == ["mock", "real"]
        assert next(m for m in catalog["model_options"] if m["option"] == "reasoning")["price_known"] is True
        assert next(m for m in catalog["model_options"] if m["option"] == "auto")["price_known"] is False
        cfg = await demo_config(client, mode="real", config_mode="manual")
        cfg["budget"]["total_cap"] = "2.00"
        cfg["candidates"] = [{"name": "Texto", "provider": "neuralake", "model_option": "text"}, {"name": "Auto", "provider": "neuralake", "model_option": "auto"}]
        cfg["judge"] = {"provider": "neuralake", "model_option": "reasoning"}
        run_id = await create_run(client, cfg)
        detail = await wait_terminal(client, run_id)
        assert detail["status"] == "completed", detail["error"]
        assert detail["simulated"] is False and detail["mode"] == "real"
        calls = detail["artifacts"]["calls"]
        assert calls and all(c["provider"] == "neuralake" and c["usage_quality"] == "provider_reported" and c["cost_quality"] == "estimated" for c in calls)
        assert all(c["reported_model"].startswith("router/") for c in calls)
        assert {c["requested_option"] for c in calls} == {"text", "auto", "reasoning"}
        auto_call = next(c for c in calls if c["requested_option"] == "auto")
        assert Decimal(auto_call["reserved"]) > Decimal(auto_call["cost"])  # reservado pelo teto das rotas; conciliado pelo uso informado
        report = (await client.get(f"/api/v1/runs/{run_id}/report")).json()
        assert report["simulated"] is False and report["decision_status"] == "inconclusive"  # sem metricas provadas -> pendente
        assert report["diversity_observed"]["neuralake"] == sorted({c["reported_model"] for c in calls})
        assert Decimal(report["cost"]["total"]) > 0 and report["cost"]["quality"] == "estimated"
        assert all("Bearer" not in json.dumps(c) for c in fake.calls)


async def test_real_mode_strict_requires_known_prices(tmp_path) -> None:  # noqa: ANN001
    settings = make_settings(tmp_path, neuralake_api_key="k", neuralake_prices_file=tmp_path / "nao-existe.json", executor_enabled=False)
    async with app_client(settings) as (_app, client):
        cfg = await demo_config(client, mode="real")
        cfg["budget"]["total_cap"] = "2.00"
        r = await client.post("/api/v1/runs", json=cfg)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "price_unknown"
        cfg["budget"]["strict"] = False
        r = await client.post("/api/v1/runs", json=cfg)
        assert r.status_code == 202 and "indicativo" in r.json()["links"]["warnings"]


async def test_client_brings_own_neuralake_key_kept_only_in_memory(tmp_path) -> None:  # noqa: ANN001
    # Servidor SEM chave e com senha: quem traz a propria chave roda o modo real sem a senha do servidor.
    settings = make_settings(tmp_path, neuralake_prices_file=PRICES, real_mode_password="s3nha", executor_enabled=False)
    secret = "nlk-cliente-123"
    async with app_client(settings) as (app, client):
        catalog = (await client.get("/api/v1/catalog")).json()
        assert catalog["providers"]["neuralake"]["enabled"] is False and catalog["providers"]["neuralake"]["accepts_client_key"] is True
        real = await demo_config(client, mode="real")
        real["budget"]["total_cap"] = "2.00"
        assert (await client.post("/api/v1/runs", json=real)).json()["detail"]["code"] in ("provider_unavailable", "real_mode_locked")
        r = await client.post("/api/v1/runs", json=real, headers={"X-NeuraLake-Key": secret})
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        detail = await client.get(f"/api/v1/runs/{run_id}")
        events = await client.get(f"/api/v1/runs/{run_id}/events/list")
        assert secret not in detail.text and secret not in events.text
        executor = app.state.executor
        assert executor.run_keys[run_id] == {"neuralake": secret}
        ctx = await executor.build_context(run_id)
        assert ctx.adapters["neuralake"]._api_key == secret and run_id not in executor.run_keys  # consumida
        # Simulado nao guarda chave nenhuma.
        r2 = await client.post("/api/v1/runs", json=await demo_config(client), headers={"X-NeuraLake-Key": secret})
        assert r2.status_code == 202 and r2.json()["run_id"] not in executor.run_keys


async def test_real_mode_password_locks_only_real_runs(tmp_path) -> None:  # noqa: ANN001
    settings = make_settings(tmp_path, neuralake_api_key="k", neuralake_prices_file=PRICES, real_mode_password="s3nha", executor_enabled=False)
    async with app_client(settings) as (_app, client):
        catalog = (await client.get("/api/v1/catalog")).json()
        assert catalog["providers"]["neuralake"]["requires_password"] is True
        assert "s3nha" not in json.dumps(catalog)
        real = await demo_config(client, mode="real")
        real["budget"]["total_cap"] = "2.00"
        assert (await client.post("/api/v1/runs", json=real)).status_code == 401
        assert (await client.post("/api/v1/runs", json=real, headers={"X-Agentathon-Key": "errada"})).json()["detail"]["code"] == "real_mode_locked"
        assert (await client.post("/api/v1/runs", json=real, headers={"X-Agentathon-Key": "s3nha"})).status_code == 202
        # Simulado continua aberto, sem senha.
        assert (await client.post("/api/v1/runs", json=await demo_config(client))).status_code == 202
