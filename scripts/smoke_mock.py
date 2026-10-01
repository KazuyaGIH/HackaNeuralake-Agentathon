"""Smoke test do fluxo simulado ponta a ponta, sem servidor HTTP externo (usa ASGI in-process)."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="agentathon-smoke-"))
    settings = Settings(data_dir=tmp, executor_poll_s=0.05, _env_file=None)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            r = await c.get("/health")
            print("health", r.status_code, r.json())
            r = await c.get("/api/v1/catalog")
            print("catalog", r.status_code, [m["option"] for m in r.json()["model_options"]])
            r = await c.post("/api/v1/demo/prepare")
            print("demo", r.status_code)
            cfg = r.json()["challenge"]
            r = await c.post("/api/v1/runs", json=cfg, headers={"Idempotency-Key": "smoke-1"})
            print("create", r.status_code, r.json())
            run_id = r.json()["run_id"]
            for _ in range(600):
                await asyncio.sleep(0.1)
                d = (await c.get(f"/api/v1/runs/{run_id}")).json()
                if d["status"] in ("completed", "partial", "failed", "cancelled", "interrupted"):
                    break
            print("status", d["status"], d["decision_status"], d["error"])
            print("metrics", json.dumps(d["metrics"], indent=1))
            ev = (await c.get(f"/api/v1/runs/{run_id}/events/list")).json()
            print("events", [e["type"] for e in ev])
            r = await c.get(f"/api/v1/runs/{run_id}/report?format=md")
            print(r.status_code)
            print(r.text[:3000])


if __name__ == "__main__":
    asyncio.run(main())
