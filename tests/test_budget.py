"""Controles de orcamento: reserva atomica, reconciliacao, pendencias e limites."""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.budget.ledger import COMMON_BUCKET, Ledger, split_caps
from app.budget.prices import from_nano, load_price_table, to_nano
from app.contracts.common import CostQuality, RunStatus
from app.storage.db import Database
from app.storage.models import BudgetBucket, CallUsage, Run
from app.storage.repo import finish_run, utcnow


async def _db(tmp_path):  # noqa: ANN001, ANN202
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    await db.migrate()
    return db


async def _seed_run(db: Database, ledger: Ledger, cap_nano: int | None, calls_cap: int = 32, status: str = "running") -> str:
    run_id = "run_test"
    async with db.session() as s, s.begin():
        s.add(Run(id=run_id, owner_id="local", status=status, decision_status="not_evaluated", mode="mock", simulated=True, snapshot={}, snapshot_hashes={}, seed=1, app_version="t", created_at=utcnow(), calls_cap=calls_cap))
        await s.flush()
        await ledger.init_buckets(s, run_id, [(COMMON_BUCKET, cap_nano, 0, 0)])
    return run_id


async def test_parallel_reservations_cannot_exceed_balance(tmp_path) -> None:  # noqa: ANN001
    db = await _db(tmp_path)
    ledger = Ledger(load_price_table(None), strict=True)
    cap = to_nano(Decimal("0.010"))
    run_id = await _seed_run(db, ledger, cap)
    amount = to_nano(Decimal("0.006"))  # duas reservas somariam 0.012 > 0.010

    async def attempt() -> bool:
        async with db.session() as s, s.begin():
            ok, _ = await ledger.reserve(s, run_id, COMMON_BUCKET, amount, protected_stage=False, deadline_ok=True)
            return ok

    results = await asyncio.gather(*(attempt() for _ in range(4)))
    assert results.count(True) == 1, results
    async with db.session() as s:
        b = (await s.execute(select(BudgetBucket).where(BudgetBucket.run_id == run_id))).scalar_one()
        run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert b.reserved_nano == amount and b.spent_nano == 0
    # Reservas negadas nao consomem slots de chamada: o contador de chamadas foi revertido pela transacao.
    assert run.calls_used == 1
    await db.dispose()


async def test_reserve_denied_when_not_running_or_calls_exhausted_or_deadline(tmp_path) -> None:  # noqa: ANN001
    db = await _db(tmp_path)
    ledger = Ledger(load_price_table(None), strict=True)
    run_id = await _seed_run(db, ledger, None, calls_cap=1)
    async with db.session() as s, s.begin():
        ok, _ = await ledger.reserve(s, run_id, COMMON_BUCKET, 10, protected_stage=False, deadline_ok=True)
        assert ok
    async with db.session() as s, s.begin():
        ok, reason = await ledger.reserve(s, run_id, COMMON_BUCKET, 10, protected_stage=False, deadline_ok=True)
        assert not ok and "limite de chamadas" in reason
    async with db.session() as s, s.begin():
        ok, reason = await ledger.reserve(s, run_id, COMMON_BUCKET, 10, protected_stage=False, deadline_ok=False)
        assert not ok and "prazo" in reason
    async with db.session() as s, s.begin():
        run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
        run.cancel_requested_at = utcnow()
        run.calls_cap = 10
    async with db.session() as s, s.begin():
        ok, reason = await ledger.reserve(s, run_id, COMMON_BUCKET, 10, protected_stage=False, deadline_ok=True)
        assert not ok and "cancelamento" in reason
    await db.dispose()


async def test_reconcile_known_unknown_and_release(tmp_path) -> None:  # noqa: ANN001
    db = await _db(tmp_path)
    ledger = Ledger(load_price_table(None), strict=True)
    run_id = await _seed_run(db, ledger, to_nano(Decimal("1")))

    def call(cid: str, reserved: int) -> CallUsage:
        return CallUsage(id=cid, run_id=run_id, logical_call_id="l", attempt=1, stage="s", role="thinker", candidate_id=None, bucket_key=COMMON_BUCKET, provider="mock",
                         requested_option="mock-default", usage_quality="unknown", price_version="v", cost_quality="unknown", reserved_nano=reserved, status="reserved", created_at=utcnow())

    for cid in ("a", "b", "c"):
        async with db.session() as s, s.begin():
            ok, _ = await ledger.reserve(s, run_id, COMMON_BUCKET, 1000, protected_stage=False, deadline_ok=True)
            assert ok
            s.add(call(cid, 1000))
    async with db.session() as s, s.begin():
        a = (await s.execute(select(CallUsage).where(CallUsage.id == "a"))).scalar_one()
        exceeded = await ledger.reconcile(s, a, cost_nano=600, usage_known=True, cost_quality=CostQuality.ESTIMATED)
        assert not exceeded and a.status == "reconciled"
        b = (await s.execute(select(CallUsage).where(CallUsage.id == "b"))).scalar_one()
        await ledger.reconcile(s, b, cost_nano=None, usage_known=False, cost_quality=CostQuality.UNKNOWN)
        assert b.status == "pending_unknown" and b.cost_nano is None
        c = (await s.execute(select(CallUsage).where(CallUsage.id == "c"))).scalar_one()
        await ledger.release(s, c, status="failed")
    async with db.session() as s:
        bucket = (await s.execute(select(BudgetBucket).where(BudgetBucket.run_id == run_id))).scalar_one()
    assert bucket.spent_nano == 600 and bucket.reserved_nano == 0 and bucket.pending_unknown_nano == 1000
    # Timeout com consumo desconhecido: a reserva permanece pendente e continua contando contra o teto.
    assert from_nano(bucket.pending_unknown_nano) == Decimal("0.000001")
    await db.dispose()


async def test_reconcile_flags_exceeded_reservation(tmp_path) -> None:  # noqa: ANN001
    db = await _db(tmp_path)
    ledger = Ledger(load_price_table(None), strict=True)
    run_id = await _seed_run(db, ledger, to_nano(Decimal("1")))
    async with db.session() as s, s.begin():
        ok, _ = await ledger.reserve(s, run_id, COMMON_BUCKET, 100, protected_stage=False, deadline_ok=True)
        assert ok
        c = CallUsage(id="x", run_id=run_id, logical_call_id="l", attempt=1, stage="s", role="thinker", candidate_id=None, bucket_key=COMMON_BUCKET, provider="mock",
                      requested_option="mock-default", usage_quality="unknown", price_version="v", cost_quality="unknown", reserved_nano=100, status="reserved", created_at=utcnow())
        s.add(c)
        exceeded = await ledger.reconcile(s, c, cost_nano=250, usage_known=True, cost_quality=CostQuality.ESTIMATED)
    assert exceeded
    await db.dispose()


def test_split_caps_equal_and_weighted() -> None:
    caps = split_caps(Decimal("1"), Decimal("30"), {"c1": Decimal(1), "c2": Decimal(1)})
    assert from_nano(caps["common"]) == Decimal("0.3")
    assert from_nano(caps["candidate:c1"]) == Decimal("0.35") == from_nano(caps["candidate:c2"])
    weighted = split_caps(Decimal("1"), Decimal("30"), {"c1": Decimal(3), "c2": Decimal(1)})
    assert from_nano(weighted["candidate:c1"]) == Decimal("0.525") and from_nano(weighted["candidate:c2"]) == Decimal("0.175")
    assert split_caps(None, Decimal("30"), {"c1": Decimal(1)}) == {"common": None, "candidate:c1": None}


def test_price_unknown_blocks_strict_mode() -> None:
    import pytest

    from app.budget.ledger import BudgetDenied

    ledger = Ledger(load_price_table(None), strict=True)
    with pytest.raises(BudgetDenied):
        ledger.plan("neuralake", "auto", 1000, 500, ["auto", "text"])
    lenient = Ledger(load_price_table(None), strict=False)
    plan = lenient.plan("neuralake", "auto", 1000, 500, ["auto", "text"])
    assert plan.amount_nano == 0 and plan.price is None


async def test_late_result_does_not_reopen_terminal_run(tmp_path) -> None:  # noqa: ANN001
    db = await _db(tmp_path)
    ledger = Ledger(load_price_table(None), strict=True)
    run_id = await _seed_run(db, ledger, None, status="interrupted")
    async with db.session() as s, s.begin():
        assert await finish_run(s, run_id, RunStatus.COMPLETED, "ranked", None) is None
    async with db.session() as s:
        run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.status == "interrupted"
    # Cancelamento pedido durante a execucao: a finalizacao vira cancelled, nunca completed.
    async with db.session() as s, s.begin():
        run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
        run.status = "running"
        run.cancel_requested_at = utcnow()
    async with db.session() as s, s.begin():
        assert await finish_run(s, run_id, RunStatus.COMPLETED, "ranked", None) == RunStatus.CANCELLED
    await db.dispose()
