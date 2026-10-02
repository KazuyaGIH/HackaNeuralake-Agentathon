"""Executor limitado: um processo, uma execucao ativa por instancia, fila persistida no banco."""

import asyncio
import logging
import socket
import uuid

from sqlalchemy import select, update

from app.budget.ledger import Ledger
from app.budget.prices import PriceTable
from app.config import Settings
from app.contracts.challenge import ChallengeConfig
from app.contracts.common import RunStatus
from app.orchestration.coordinator import RunContext, make_adapters
from app.orchestration.graph import run_arena
from app.providers.base import ProviderAdapter
from app.providers.catalog import Catalog
from app.storage.db import Database
from app.storage.models import Run
from app.storage.repo import RunNotifier, append_event, finish_run, utcnow

log = logging.getLogger("agentathon.executor")


class Executor:
    def __init__(self, db: Database, settings: Settings, catalog: Catalog, prices: PriceTable, notifier: RunNotifier, adapters: dict[str, ProviderAdapter] | None = None) -> None:
        self.db = db
        self.settings = settings
        self.catalog = catalog
        self.prices = prices
        self.notifier = notifier
        self.adapters = adapters if adapters is not None else make_adapters(settings, catalog)
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self.current_run_id: str | None = None
        # Chaves trazidas pelo navegador (X-<Provedor>-Key), por run e provedor: so em memoria, consumidas quando o
        # run comeca. Nunca vao para snapshot, banco, eventos ou logs; se o servidor reiniciar antes, o run fica sem elas.
        self.run_keys: dict[str, dict[str, str]] = {}

    async def mark_interrupted(self) -> list[str]:
        """Reinicio do servidor: trabalho ativo vira `interrupted`; nenhuma chamada e repetida."""
        async with self.db.session() as s, s.begin():
            ids = list((await s.execute(select(Run.id).where(Run.status == RunStatus.RUNNING))).scalars())
            if ids:
                await s.execute(
                    update(Run).where(Run.id.in_(ids), Run.status == RunStatus.RUNNING)
                    .values(status=str(RunStatus.INTERRUPTED), finished_at=utcnow(), error="servidor reiniciado durante a execucao; artefatos preservados, chamadas nao repetidas")
                )
                for rid in ids:
                    await append_event(s, rid, "run.interrupted", {"reason": "servidor reiniciado durante a execucao"})
        return ids

    def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="agentathon-executor")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while not self._stopping:
            run_id = await self.claim_next()
            if run_id is None:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.settings.executor_poll_s)
                except TimeoutError:
                    pass
                self._wake.clear()
                continue
            await self.run_one(run_id)

    async def claim_next(self) -> str | None:
        async with self.db.session() as s, s.begin():
            rid = (await s.execute(select(Run.id).where(Run.status == RunStatus.QUEUED).order_by(Run.created_at, Run.id).limit(1))).scalar_one_or_none()
            if rid is None:
                return None
            res = await s.execute(
                update(Run).where(Run.id == rid, Run.status == RunStatus.QUEUED)
                .values(status=str(RunStatus.RUNNING), started_at=utcnow(), worker_id=self.worker_id)
            )
            if res.rowcount != 1:
                return None
        return rid

    async def build_context(self, run_id: str) -> RunContext:
        async with self.db.session() as s:
            run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
        snapshot = ChallengeConfig.model_validate(run.snapshot)
        ledger = Ledger(self.prices, strict=snapshot.budget.strict)
        adapters = dict(self.adapters)
        client_keys = self.run_keys.pop(run_id, None) or {}
        if client_keys:
            from app.providers.registry import build_adapter

            for prov, key in client_keys.items():
                adapters[prov] = build_adapter(prov, key, self.settings)
        return RunContext(
            run_id=run.id, owner_id=run.owner_id, snapshot=snapshot, seed=run.seed, hashes=dict(run.snapshot_hashes),
            settings=self.settings, db=self.db, catalog=self.catalog, adapters=adapters, ledger=ledger, notifier=self.notifier,
        )

    async def run_one(self, run_id: str) -> str:
        self.current_run_id = run_id
        try:
            ctx = await self.build_context(run_id)
            final = await run_arena(ctx)
        except Exception as exc:  # noqa: BLE001
            log.exception("falha inesperada no run %s", run_id)
            async with self.db.session() as s, s.begin():
                await finish_run(s, run_id, RunStatus.FAILED, "not_evaluated", f"{type(exc).__name__}: {exc}")
                await append_event(s, run_id, "run.failed", {"error": f"{type(exc).__name__}: {exc}"})
            self.notifier.notify(run_id)
            final = str(RunStatus.FAILED)
        finally:
            self.current_run_id = None
        return final
