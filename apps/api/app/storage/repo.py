"""Consultas e escritas comuns (eventos, artefatos, estado do run)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.common import RunStatus
from app.storage.models import Artifact, BudgetBucket, CallUsage, Run, RunEvent


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunNotifier:
    """Acorda assinantes SSE quando um run recebe eventos novos (mesmo processo)."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def get(self, run_id: str) -> asyncio.Event:
        return self._events.setdefault(run_id, asyncio.Event())

    def notify(self, run_id: str) -> None:
        ev = self._events.get(run_id)
        if ev is not None:
            ev.set()

    async def wait(self, run_id: str, timeout: float) -> None:
        ev = self.get(run_id)
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except TimeoutError:
            return
        finally:
            ev.clear()


async def append_event(session: AsyncSession, run_id: str, type_: str, payload: dict[str, Any]) -> int:
    res = await session.execute(
        update(Run).where(Run.id == run_id).values(last_event_seq=Run.last_event_seq + 1).returning(Run.last_event_seq)
    )
    seq = res.scalar_one()
    session.add(RunEvent(run_id=run_id, seq=seq, type=type_, ts=utcnow(), payload=payload))
    return seq


async def list_events(session: AsyncSession, run_id: str, after_seq: int = 0, limit: int = 500) -> list[RunEvent]:
    res = await session.execute(
        select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after_seq).order_by(RunEvent.seq).limit(limit)
    )
    return list(res.scalars())


async def upsert_artifact(session: AsyncSession, run_id: str, kind: str, payload: dict[str, Any], *, candidate_id: str = "", version: int = 1, visibility: str = "public") -> None:
    existing = (
        await session.execute(
            select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == kind, Artifact.candidate_id == candidate_id, Artifact.version == version)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.payload = payload
        existing.visibility = visibility
        return
    session.add(Artifact(run_id=run_id, kind=kind, candidate_id=candidate_id, version=version, visibility=visibility, payload=payload, created_at=utcnow()))


async def list_artifacts(session: AsyncSession, run_id: str, *, public_only: bool = True) -> list[Artifact]:
    stmt = select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.id)
    if public_only:
        stmt = stmt.where(Artifact.visibility == "public")
    return list((await session.execute(stmt)).scalars())


async def get_run(session: AsyncSession, run_id: str) -> Run | None:
    return (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()


async def list_buckets(session: AsyncSession, run_id: str) -> list[BudgetBucket]:
    return list((await session.execute(select(BudgetBucket).where(BudgetBucket.run_id == run_id).order_by(BudgetBucket.id))).scalars())


async def list_calls(session: AsyncSession, run_id: str) -> list[CallUsage]:
    return list((await session.execute(select(CallUsage).where(CallUsage.run_id == run_id).order_by(CallUsage.created_at, CallUsage.id))).scalars())


async def finish_run(session: AsyncSession, run_id: str, status: RunStatus, decision_status: str, error: str | None) -> RunStatus | None:
    """Transicao terminal condicional: so sai de running; cancelamento pedido vira cancelled. Retorna status final."""
    now = utcnow()
    if status in (RunStatus.COMPLETED, RunStatus.PARTIAL):
        res = await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == RunStatus.RUNNING, Run.cancel_requested_at.is_(None))
            .values(status=str(status), decision_status=decision_status, finished_at=now, error=error)
        )
        if res.rowcount == 1:
            return status
        res = await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == RunStatus.RUNNING, Run.cancel_requested_at.is_not(None))
            .values(status=str(RunStatus.CANCELLED), decision_status=decision_status, finished_at=now, error=error)
        )
        return RunStatus.CANCELLED if res.rowcount == 1 else None
    res = await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == RunStatus.RUNNING)
        .values(status=str(status), decision_status=decision_status, finished_at=now, error=error)
    )
    return status if res.rowcount == 1 else None
