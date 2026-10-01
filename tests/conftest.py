import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers.base import ProviderAdapter  # noqa: E402

TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {"data_dir": tmp_path / "data", "executor_poll_s": 0.02, "_env_file": None}
    base.update(overrides)
    return Settings(**base)


@asynccontextmanager
async def app_client(settings: Settings, adapters: dict[str, ProviderAdapter] | None = None, headers: dict[str, str] | None = None) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    app = create_app(settings, adapters=adapters)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers or {}, timeout=30) as client:
            yield app, client


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(settings) as (_app, c):
        yield c


@pytest.fixture
async def app_and_client(settings: Settings) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    async with app_client(settings) as pair:
        yield pair


async def demo_config(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    r = await client.post("/api/v1/demo/prepare")
    assert r.status_code == 200, r.text
    cfg = r.json()["challenge"]
    cfg.update(overrides)
    return cfg


async def create_run(client: httpx.AsyncClient, cfg: dict[str, Any], **headers: str) -> str:
    r = await client.post("/api/v1/runs", json=cfg, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


async def wait_terminal(client: httpx.AsyncClient, run_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        d = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if d["status"] in TERMINAL:
            return d
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"run {run_id} nao terminou: status={d['status']}")
        await asyncio.sleep(0.05)


async def run_demo(client: httpx.AsyncClient, **overrides: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    cfg = await demo_config(client, **overrides)
    run_id = await create_run(client, cfg)
    detail = await wait_terminal(client, run_id)
    r = await client.get(f"/api/v1/runs/{run_id}/report")
    report = r.json() if r.status_code == 200 else {}
    return run_id, detail, report


async def events(client: httpx.AsyncClient, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    return (await client.get(f"/api/v1/runs/{run_id}/events/list", params={"after": after})).json()


Waiter = Callable[[httpx.AsyncClient, str], Any]
