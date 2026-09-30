"""Reservas atomicas, reconciliacao e provisoes por bucket (cota comum e cotas por candidato)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.prices import Price, PriceTable, to_nano
from app.contracts.common import CostQuality
from app.providers.base import estimate_tokens
from app.storage.models import BudgetBucket, CallUsage, Run

COMMON_BUCKET = "common"


def candidate_bucket(candidate_id: str) -> str:
    return f"candidate:{candidate_id}"


@dataclass(frozen=True)
class ReservationPlan:
    amount_nano: int
    price_version: str
    price: Price | None
    est_input_tokens: int
    est_output_tokens: int


class BudgetDenied(Exception):
    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


class Ledger:
    """Todas as operacoes sao UPDATEs condicionais: a mesma transacao valida estado do job, prazo e saldo."""

    def __init__(self, prices: PriceTable, strict: bool) -> None:
        self.prices = prices
        self.strict = strict

    def plan(self, provider: str, option: str, prompt_chars: int, max_output_tokens: int, allowed_options: list[str]) -> ReservationPlan:
        est_in = estimate_tokens(prompt_chars)
        price = self.prices.get(provider, option)
        if price is None and option == "auto":
            price = self.prices.max_price(provider, allowed_options)
        if price is None:
            if self.strict:
                raise BudgetDenied(
                    f"preco desconhecido para {provider}/{option}: modo estrito nao pode limitar a cobranca", "price_unknown"
                )
            return ReservationPlan(0, self.prices.version, None, est_in, max_output_tokens)
        return ReservationPlan(to_nano(price.cost(est_in, max_output_tokens)), self.prices.version, price, est_in, max_output_tokens)

    async def init_buckets(self, session: AsyncSession, run_id: str, specs: list[tuple[str, int | None, int, int]]) -> None:
        for key, cap_nano, provision_nano, calls_provisioned in specs:
            session.add(
                BudgetBucket(
                    run_id=run_id, bucket_key=key, cap_nano=cap_nano, provision_nano=provision_nano,
                    calls_provisioned=calls_provisioned,
                )
            )

    async def reserve(
        self, session: AsyncSession, run_id: str, bucket_key: str, amount_nano: int, *, protected_stage: bool, deadline_ok: bool
    ) -> tuple[bool, str]:
        """Reserva saldo + slot de chamada. Retorna (ok, motivo). Chamador controla a transacao."""
        if not deadline_ok:
            return False, "prazo da execucao esgotado"
        run_stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status == "running", Run.cancel_requested_at.is_(None), Run.calls_used < Run.calls_cap)
            .values(calls_used=Run.calls_used + 1)
        )
        res = await session.execute(run_stmt)
        if res.rowcount != 1:
            run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
            if run is None:
                return False, "run inexistente"
            if run.status != "running":
                return False, f"job nao esta em execucao (status={run.status})"
            if run.cancel_requested_at is not None:
                return False, "cancelamento solicitado"
            return False, f"limite de chamadas atingido ({run.calls_cap})"

        bucket = (
            await session.execute(select(BudgetBucket).where(BudgetBucket.run_id == run_id, BudgetBucket.bucket_key == bucket_key))
        ).scalar_one()
        # Provisao para etapas protegidas vira reserva sem contar duas vezes.
        from_provision = min(bucket.provision_nano, amount_nano) if protected_stage else 0
        slot_from_provision = 1 if protected_stage and bucket.calls_provisioned > 0 else 0
        conditions = [
            BudgetBucket.run_id == run_id,
            BudgetBucket.bucket_key == bucket_key,
            BudgetBucket.provision_nano >= from_provision,
            BudgetBucket.calls_provisioned >= slot_from_provision,
        ]
        if self.strict:
            conditions.append(
                or_(
                    BudgetBucket.cap_nano.is_(None),
                    BudgetBucket.spent_nano + BudgetBucket.reserved_nano + BudgetBucket.pending_unknown_nano
                    + (BudgetBucket.provision_nano - from_provision) + amount_nano <= BudgetBucket.cap_nano,
                )
            )
        stmt = (
            update(BudgetBucket)
            .where(and_(*conditions))
            .values(
                reserved_nano=BudgetBucket.reserved_nano + amount_nano,
                provision_nano=BudgetBucket.provision_nano - from_provision,
                calls_used=BudgetBucket.calls_used + 1,
                calls_provisioned=BudgetBucket.calls_provisioned - slot_from_provision,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount != 1:
            # Compensa o slot de chamada na mesma transacao: negacao nao consome chamadas.
            await session.execute(update(Run).where(Run.id == run_id).values(calls_used=Run.calls_used - 1))
            return False, f"saldo insuficiente no bucket '{bucket_key}' para reservar a chamada (modo estrito)"
        return True, "ok"

    async def reconcile(
        self, session: AsyncSession, call: CallUsage, *, cost_nano: int | None, usage_known: bool, cost_quality: CostQuality
    ) -> bool:
        """Concilia uso informado. Retorna True se o uso real excedeu a reserva (limite excedido)."""
        exceeded = False
        bucket_where = (BudgetBucket.run_id == call.run_id, BudgetBucket.bucket_key == call.bucket_key)
        if not usage_known:
            await session.execute(
                update(BudgetBucket).where(*bucket_where).values(
                    reserved_nano=BudgetBucket.reserved_nano - call.reserved_nano,
                    pending_unknown_nano=BudgetBucket.pending_unknown_nano + call.reserved_nano,
                )
            )
            call.status = "pending_unknown"
        else:
            actual = cost_nano if cost_nano is not None else 0
            if cost_nano is None and self.prices.get(call.provider, call.requested_option) is None and not self.strict:
                # Custo desconhecido em modo indicativo: mantem a reserva (zero) e registra desconhecido.
                call.status = "reconciled_unknown_cost"
            else:
                exceeded = actual > call.reserved_nano
                await session.execute(
                    update(BudgetBucket).where(*bucket_where).values(
                        reserved_nano=BudgetBucket.reserved_nano - call.reserved_nano,
                        spent_nano=BudgetBucket.spent_nano + actual,
                    )
                )
                call.status = "reconciled"
        call.cost_nano = cost_nano
        call.cost_quality = str(cost_quality)
        call.finished_at = datetime.now(UTC)
        return exceeded

    async def release(self, session: AsyncSession, call: CallUsage, status: str) -> None:
        """Libera reserva de chamada que comprovadamente nao gerou cobranca (ex.: erro antes do envio)."""
        await session.execute(
            update(BudgetBucket)
            .where(BudgetBucket.run_id == call.run_id, BudgetBucket.bucket_key == call.bucket_key)
            .values(reserved_nano=BudgetBucket.reserved_nano - call.reserved_nano)
        )
        call.status = status
        call.cost_nano = 0
        call.cost_quality = str(CostQuality.PROVIDER_REPORTED)
        call.finished_at = datetime.now(UTC)

    async def release_provisions(self, session: AsyncSession, run_id: str) -> None:
        await session.execute(
            update(BudgetBucket).where(BudgetBucket.run_id == run_id).values(provision_nano=0, calls_provisioned=0)
        )


def split_caps(total_cap: Decimal | None, common_share_pct: Decimal, weights: dict[str, Decimal]) -> dict[str, int | None]:
    """Divide o teto em cota comum e cotas por candidato (iguais por padrao, ou por peso declarado)."""
    if total_cap is None:
        return {COMMON_BUCKET: None, **{candidate_bucket(c): None for c in weights}}
    common = total_cap * common_share_pct / Decimal("100")
    rest = total_cap - common
    total_w = sum(weights.values(), Decimal("0"))
    out: dict[str, int | None] = {COMMON_BUCKET: to_nano(common)}
    allocated = 0
    ids = list(weights)
    for i, cid in enumerate(ids):
        if i == len(ids) - 1:
            share_nano = to_nano(rest) - allocated
        else:
            share_nano = to_nano(rest * weights[cid] / total_w)
            allocated += share_nano
        out[candidate_bucket(cid)] = share_nano
    return out
