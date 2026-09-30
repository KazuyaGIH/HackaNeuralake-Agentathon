r"""Smoke test REAL da integracao NeuraLake. Gasta tokens: exige credencial e confirmacao explicita.

Uso (PowerShell):
    $env:AGENTATHON_NEURALAKE_API_KEY = "..."
    .venv\Scripts\python scripts/smoke_real.py --confirm-spend --cap 0.20

Faz uma unica chamada minima (capacidade `text`) e registra: status HTTP, modelo informado, usage, request id,
latencia e custo estimado pela tabela publica. Em seguida, opcionalmente (--full), executa uma arena real
minima (2 candidatos, sem rodada de critica) pela API in-process e grava o relatorio em data/real-smoke-<run>.md.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.budget.prices import load_price_table  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.providers.base import GenerateRequest, ProviderError  # noqa: E402
from app.providers.neuralake import NeuraLakeAdapter  # noqa: E402


async def single_call(adapter: NeuraLakeAdapter, prices) -> None:  # noqa: ANN001
    req = GenerateRequest(
        role="thinker", stage="smoke", option="text", system="Responda somente JSON valido.",
        user='Retorne exatamente {"ok": true, "lang": "pt-BR"}', schema_name="smoke", json_schema={}, max_output_tokens=50, timeout_s=30, seed=1,
    )
    t0 = time.monotonic()
    try:
        out = await adapter.generate(req)
    except ProviderError as exc:
        print(f"[FALHA] {exc.error_type}: {exc} (retryable={exc.retryable}, usage_known={exc.usage_known})")
        raise SystemExit(2) from exc
    price = prices.get("neuralake", "text")
    cost = price.cost(out.usage.input_tokens or 0, out.usage.output_tokens or 0) if price and out.usage.input_tokens is not None else None
    print(json.dumps({
        "ok": True, "latency_ms": out.latency_ms, "wall_ms": int((time.monotonic() - t0) * 1000), "reported_model": out.reported_model,
        "request_id": out.request_id, "usage": out.usage.model_dump(), "content": out.content[:200],
        "estimated_cost_usd": str(cost) if cost is not None else None, "price_version": prices.version,
    }, ensure_ascii=False, indent=1))


async def full_arena(cap: str) -> None:
    import httpx

    from app.main import create_app

    settings = get_settings()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke", timeout=600) as c:
            cfg = (await c.post("/api/v1/demo/prepare")).json()["challenge"]
            cfg.update({"mode": "real", "config_mode": "manual", "critique_rounds": 0, "mock_scenario": "default", "title": "[REAL] smoke NeuraLake"})
            cfg["budget"].update({"total_cap": cap, "strict": True, "max_total_calls": 8})
            cfg["candidates"] = [
                {"name": "Texto", "provider": "neuralake", "model_option": "text", "max_specialist_tasks": 0, "max_output_tokens": 900},
                {"name": "Raciocinio", "provider": "neuralake", "model_option": "reasoning", "max_specialist_tasks": 0, "max_output_tokens": 900},
            ]
            cfg["judge"] = {"provider": "neuralake", "model_option": "reasoning", "max_output_tokens": 1200}
            r = await c.post("/api/v1/runs", json=cfg)
            print("create", r.status_code, r.text[:400])
            if r.status_code != 202:
                raise SystemExit(3)
            run_id = r.json()["run_id"]
            while True:
                await asyncio.sleep(1)
                d = (await c.get(f"/api/v1/runs/{run_id}")).json()
                print("  status", d["status"], "calls", d["metrics"]["calls_used"], "spent", d["metrics"]["spent"])
                if d["status"] in ("completed", "partial", "failed", "cancelled", "interrupted"):
                    break
            md = (await c.get(f"/api/v1/runs/{run_id}/report", params={"format": "md"})).text
            out = settings.data_dir / f"real-smoke-{run_id}.md"
            out.write_text(md, encoding="utf-8")
            print(f"relatorio salvo em {out}")
            for call in d["artifacts"]["calls"]:
                print("  call", call["stage"], call["requested_option"], "->", call["reported_model"], call["input_tokens"], call["output_tokens"], call["cost"], call["status"], call["error_type"])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-spend", action="store_true", help="confirma que tokens pagos podem ser consumidos")
    ap.add_argument("--cap", default="0.20", help="teto em USD para a arena completa (--full)")
    ap.add_argument("--full", action="store_true", help="executa arena real minima alem da chamada unica")
    args = ap.parse_args()
    settings = get_settings()
    if not settings.neuralake_api_key:
        print("AGENTATHON_NEURALAKE_API_KEY nao configurada: teste real PENDENTE (nenhuma chamada feita).")
        raise SystemExit(1)
    if not args.confirm_spend:
        print("Use --confirm-spend para autorizar consumo de tokens pagos.")
        raise SystemExit(1)
    prices = load_price_table(settings.neuralake_prices_file)
    adapter = NeuraLakeAdapter(api_key=settings.neuralake_api_key, base_url=settings.neuralake_base_url, json_mode=settings.neuralake_json_mode)
    await single_call(adapter, prices)
    if args.full:
        await full_arena(args.cap)


if __name__ == "__main__":
    asyncio.run(main())
