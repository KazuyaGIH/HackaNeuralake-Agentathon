"""Coordenador em codigo: unico componente que autoriza chamadas, aplica limites, persiste e emite eventos."""

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.budget.ledger import COMMON_BUCKET, BudgetDenied, Ledger, candidate_bucket
from app.budget.prices import NEURALAKE_OPTIONS, from_nano, to_nano
from app.config import Settings
from app.contracts.artifacts import ActionPlan, Critique, Evaluation, EvidencePack, Proposal, Report, TaskPlan, TaskResult, Verification
from app.contracts.challenge import CandidateConfig, ChallengeConfig, JudgeConfig
from app.contracts.common import CostQuality, Provider, UsageQuality
from app.providers.base import GenerateRequest, GenerateResult, ProviderAdapter, ProviderError
from app.providers.catalog import Catalog
from app.storage.db import Database
from app.storage.models import BudgetBucket, CallUsage, Run
from app.storage.repo import RunNotifier, append_event, list_buckets, upsert_artifact, utcnow

T = TypeVar("T", bound=BaseModel)


class CallDenied(Exception):
    """Gate negou a chamada (limite, orcamento, prazo, cancelamento)."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


class CallFailed(Exception):
    """Todas as tentativas permitidas falharam."""

    def __init__(self, reason: str, error_type: str, call_ids: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_type = error_type
        self.call_ids = call_ids


@dataclass
class RunContext:
    run_id: str
    owner_id: str
    snapshot: ChallengeConfig
    seed: int
    hashes: dict[str, str]
    settings: Settings
    db: Database
    catalog: Catalog
    adapters: dict[str, ProviderAdapter]
    ledger: Ledger
    notifier: RunNotifier
    started_monotonic: float = field(default_factory=time.monotonic)
    semaphore: asyncio.Semaphore = field(init=False)
    halt: str | None = None  # None | "cancelled" | "limit" | "failed"
    halt_reason: str | None = None
    partial_reasons: list[str] = field(default_factory=list)
    operational_changes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    pack: EvidencePack | None = None
    plans: dict[str, TaskPlan] = field(default_factory=dict)
    task_results: dict[str, list[TaskResult]] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    critiques: list[Critique] = field(default_factory=list)
    verifications: dict[str, Verification] = field(default_factory=dict)
    evaluations: dict[str, dict[str, Evaluation]] = field(default_factory=dict)  # judge_id -> candidate_id -> Evaluation
    judge_shuffle_seed: int | None = None
    judge_error: str | None = None
    # Rodadas derivadas (melhoria/plano): custo e cota acumulados das rodadas anteriores, por candidato.
    inherited_costs: dict[str, tuple[Decimal, Decimal | None]] = field(default_factory=dict)
    parent_report: Report | None = None
    action_plan: ActionPlan | None = None
    reported_models: dict[str, set[str]] = field(default_factory=dict)
    _call_counter: int = 0

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(self.snapshot.budget.max_concurrent_calls)

    # ------------------------------------------------------------------ propriedades

    @property
    def candidates(self) -> list[CandidateConfig]:
        """Equipes em disputa. Na repescagem (rodada de melhoria) so seguem as que receberam feedback."""
        everyone = list(self.snapshot.candidates or [])
        if self.snapshot.refinement is not None:
            keep = {f.candidate_id for f in self.snapshot.refinement.feedback}
            return [c for c in everyone if c.candidate_id in keep]
        return everyone

    @property
    def judges(self) -> list[JudgeConfig]:
        """Painel resolvido no intake; snapshots antigos (juiz unico) caem no juiz legado com a rubrica do desafio."""
        if self.snapshot.judges:
            return list(self.snapshot.judges)
        legacy = self.snapshot.judge or JudgeConfig()
        return [legacy.model_copy(update={"judge_id": legacy.judge_id or "j1", "rubric": legacy.rubric or self.snapshot.rubric})]

    def candidate(self, cid: str) -> CandidateConfig:
        return next(c for c in (self.snapshot.candidates or []) if c.candidate_id == cid)

    def candidate_index(self, cid: str) -> int:
        # Posicao na arena original (estavel entre rodadas, mesmo quando equipes saem da disputa).
        return next(i for i, c in enumerate(self.snapshot.candidates or []) if c.candidate_id == cid)

    @property
    def simulated(self) -> bool:
        return self.snapshot.mode == "mock"

    def remaining_s(self) -> float:
        return self.snapshot.budget.run_deadline_s - (time.monotonic() - self.started_monotonic)

    @property
    def halted(self) -> bool:
        return self.halt is not None

    def set_halt(self, kind: str, reason: str) -> None:
        if self.halt is None or kind == "cancelled":
            self.halt = kind
            self.halt_reason = reason

    async def cancel_requested(self) -> bool:
        async with self.db.session() as s:
            row = (await s.execute(select(Run.cancel_requested_at, Run.status).where(Run.id == self.run_id))).one()
        return row[0] is not None or row[1] != "running"

    async def check_cancel(self) -> bool:
        if await self.cancel_requested():
            self.set_halt("cancelled", "cancelamento solicitado")
            return True
        return False

    # ------------------------------------------------------------------ persistencia

    async def emit(self, type_: str, payload: dict[str, Any]) -> None:
        async with self.db.session() as s, s.begin():
            await append_event(s, self.run_id, type_, _sanitize(payload))
        self.notifier.notify(self.run_id)

    async def save_artifact(self, kind: str, model: BaseModel, *, candidate_id: str = "", version: int = 1, visibility: str = "public") -> None:
        async with self.db.session() as s, s.begin():
            await upsert_artifact(s, self.run_id, kind, model.model_dump(mode="json"), candidate_id=candidate_id, version=version, visibility=visibility)

    async def budget_snapshot(self) -> dict[str, Any]:
        async with self.db.session() as s:
            buckets = await list_buckets(s, self.run_id)
            run = (await s.execute(select(Run).where(Run.id == self.run_id))).scalar_one()
        return {
            "calls_used": run.calls_used,
            "calls_cap": run.calls_cap,
            "buckets": [_bucket_view(b) for b in buckets],
        }

    async def emit_budget(self) -> None:
        await self.emit("budget.updated", await self.budget_snapshot())

    async def costs(self) -> dict[str, Any]:
        """Custos por bucket em Decimal, com qualidade agregada."""
        async with self.db.session() as s:
            buckets = await list_buckets(s, self.run_id)
            calls = list((await s.execute(select(CallUsage).where(CallUsage.run_id == self.run_id))).scalars())
        qualities = {c.cost_quality for c in calls}
        if any(c.status == "pending_unknown" for c in calls) or CostQuality.UNKNOWN in qualities:
            quality = CostQuality.UNKNOWN
        elif CostQuality.ESTIMATED in qualities or not calls:
            quality = CostQuality.ESTIMATED
        else:
            quality = CostQuality.PROVIDER_REPORTED
        per_bucket = {b.bucket_key: b for b in buckets}
        judge_nano = sum((c.cost_nano or 0) for c in calls if c.role == "judge")
        bucket_quality: dict[str, CostQuality] = {}
        for b in buckets:
            bc = [c for c in calls if c.bucket_key == b.bucket_key]
            if any(c.status == "pending_unknown" or c.cost_quality == CostQuality.UNKNOWN for c in bc):
                bucket_quality[b.bucket_key] = CostQuality.UNKNOWN
            elif any(c.cost_quality == CostQuality.ESTIMATED for c in bc) or not bc:
                bucket_quality[b.bucket_key] = CostQuality.ESTIMATED
            else:
                bucket_quality[b.bucket_key] = CostQuality.PROVIDER_REPORTED
        return {
            "buckets": per_bucket,
            "bucket_quality": bucket_quality,
            "quality": quality,
            "judge": from_nano(judge_nano) or Decimal("0"),
            "calls_used": len(calls),
            "pending_unknown": from_nano(sum(b.pending_unknown_nano for b in buckets)) or Decimal("0"),
        }

    async def secondary_usage(self) -> tuple[dict[str, int], dict[str, Decimal]]:
        """Chamadas no modelo economico por candidato e economia estimada vs. o mesmo uso no modelo principal."""
        async with self.db.session() as s:
            calls = list((await s.execute(select(CallUsage).where(CallUsage.run_id == self.run_id))).scalars())
        counts: dict[str, int] = {}
        savings: dict[str, Decimal] = {}
        for c in calls:
            cand = next((x for x in self.candidates if x.candidate_id == c.candidate_id), None)
            if cand is None or not cand.secondary_model_option or c.requested_option != cand.secondary_model_option or c.requested_option == cand.model_option:
                continue
            cid = cand.candidate_id or ""
            counts[cid] = counts.get(cid, 0) + 1
            main = self.ledger.prices.get(c.provider, cand.model_option)
            if main is None and cand.model_option == "auto":
                main = self.ledger.prices.max_price(c.provider, NEURALAKE_OPTIONS)
            if main is None or c.input_tokens is None or c.output_tokens is None or c.cost_nano is None:
                continue
            diff = main.cost(c.input_tokens, c.output_tokens) - (from_nano(c.cost_nano) or Decimal("0"))
            savings[cid] = savings.get(cid, Decimal("0")) + max(Decimal("0"), diff)
        return counts, savings

    # ------------------------------------------------------------------ gate + chamada logica

    def _adapter_for(self, provider: str) -> ProviderAdapter:
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise CallDenied(f"provedor '{provider}' indisponivel nesta instancia (sem credencial ou nao habilitado)", "provider_unavailable")
        return adapter

    async def call(
        self,
        *,
        role: str,
        stage: str,
        candidate_id: str | None,
        provider: str,
        option: str,
        system: str,
        user: str,
        schema: type[T],
        max_output_tokens: int,
        metadata: dict[str, Any],
        protected: bool = False,
        validator: Callable[[T], None] | None = None,
    ) -> tuple[T, list[str]]:
        """Chamada logica com no maximo `max_attempts_per_call` tentativas (inicial + repeticao/reparacao)."""
        adapter = self._adapter_for(provider)
        bucket_key = candidate_bucket(candidate_id) if candidate_id else COMMON_BUCKET
        self._call_counter += 1
        logical_id = f"{stage}:{candidate_id or 'common'}:{self._call_counter}"
        max_attempts = self.snapshot.budget.max_attempts_per_call
        call_ids: list[str] = []
        repair_of: str | None = None
        repair_error: str | None = None
        last_error = ("unknown", "sem tentativas")
        json_schema = schema.model_json_schema()
        metadata = {**metadata, "scenario": self.snapshot.mock_scenario, "seed": self.seed}

        for attempt in range(1, max_attempts + 1):
            if await self.check_cancel():
                raise CallDenied("cancelamento solicitado", "cancelled")
            req = GenerateRequest(
                role=role, stage=stage, candidate_id=candidate_id, option=option, system=system, user=user,
                schema_name=_schema_name(schema), json_schema=json_schema, max_output_tokens=max_output_tokens,
                timeout_s=min(self.snapshot.budget.call_timeout_s, max(1.0, self.remaining_s())), seed=self.seed,
                attempt=attempt, repair_of=repair_of, repair_error=repair_error, metadata=metadata,
            )
            try:
                plan = self.ledger.plan(provider, option, req.prompt_chars(), max_output_tokens, NEURALAKE_OPTIONS)
            except BudgetDenied as exc:
                raise CallDenied(exc.reason, exc.code) from exc
            call_id = uuid.uuid4().hex[:20]
            async with self.db.session() as s, s.begin():
                ok, reason = await self.ledger.reserve(
                    s, self.run_id, bucket_key, plan.amount_nano, protected_stage=protected, deadline_ok=self.remaining_s() > 0
                )
                if not ok:
                    raise CallDenied(reason, "gate_denied")
                call = CallUsage(
                    id=call_id, run_id=self.run_id, logical_call_id=logical_id, attempt=attempt, stage=stage, role=role,
                    candidate_id=candidate_id, bucket_key=bucket_key, provider=provider, requested_option=option,
                    usage_quality=str(UsageQuality.UNKNOWN), price_version=plan.price_version, cost_quality=str(CostQuality.UNKNOWN),
                    reserved_nano=plan.amount_nano, status="reserved", created_at=utcnow(),
                )
                s.add(call)
            call_ids.append(call_id)
            started = time.monotonic()
            result: GenerateResult | None = None
            error: ProviderError | None = None
            try:
                async with self.semaphore:
                    result = await asyncio.wait_for(adapter.generate(req), timeout=req.timeout_s)
            except TimeoutError:
                error = ProviderError("timeout", f"timeout apos {req.timeout_s:.0f}s (consumo desconhecido)", retryable=True, usage_known=False)
            except ProviderError as exc:
                error = exc
            except Exception as exc:  # noqa: BLE001 - erro inesperado do adaptador
                error = ProviderError("adapter_error", f"{type(exc).__name__}: {exc}", retryable=False, usage_known=False)
            latency_ms = int((time.monotonic() - started) * 1000)

            if error is not None:
                await self._settle_error(call_id, error, latency_ms, plan.price)
                last_error = (error.error_type, str(error))
                await self.emit("call.finished", {"call_id": call_id, "stage": stage, "candidate_id": candidate_id, "attempt": attempt, "status": "error", "error_type": error.error_type, "usage_known": error.usage_known})
                await self.emit_budget()
                if error.retryable and attempt < max_attempts and self.remaining_s() > 0:
                    continue
                raise CallFailed(str(error), error.error_type, call_ids)

            assert result is not None
            exceeded = await self._settle_success(call_id, result, latency_ms, plan.price)
            self.reported_models.setdefault(provider, set()).add(result.reported_model or "unknown")
            parsed, schema_error = _parse(result.content, schema)
            if parsed is not None and validator is not None:
                try:
                    validator(parsed)
                except ValueError as exc:
                    parsed, schema_error = None, f"validacao semantica: {exc}"
            await self.emit("call.finished", {
                "call_id": call_id, "stage": stage, "candidate_id": candidate_id, "attempt": attempt,
                "status": "ok" if parsed is not None else "schema_invalid", "reported_model": result.reported_model or "unknown",
                "input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens, "latency_ms": latency_ms,
            })
            await self.emit_budget()
            if exceeded:
                self.operational_changes.append(f"uso real excedeu a reserva na chamada {call_id}; novas chamadas bloqueadas")
                self.set_halt("limit", "uso real excedeu a reserva (limite excedido)")
            if parsed is not None:
                return parsed, call_ids
            await self._mark_schema_invalid(call_id, schema_error)
            last_error = ("schema_invalid", schema_error)
            if attempt < max_attempts and not self.halted:
                repair_of = result.content[:6000]
                repair_error = schema_error[:500]
                continue
            raise CallFailed(f"resposta invalida: {schema_error}", "schema_invalid", call_ids)
        raise CallFailed(last_error[1], last_error[0], call_ids)

    async def _settle_success(self, call_id: str, result: GenerateResult, latency_ms: int, price) -> bool:  # noqa: ANN001
        async with self.db.session() as s, s.begin():
            call = (await s.execute(select(CallUsage).where(CallUsage.id == call_id))).scalar_one()
            call.reported_model = result.reported_model
            call.request_id = result.request_id
            call.latency_ms = latency_ms
            call.input_tokens = result.usage.input_tokens
            call.output_tokens = result.usage.output_tokens
            call.usage_quality = str(result.usage.quality)
            if price is not None and result.usage.input_tokens is not None and result.usage.output_tokens is not None:
                cost_nano = to_nano(price.cost(result.usage.input_tokens, result.usage.output_tokens))
                quality = CostQuality.ESTIMATED
            else:
                cost_nano = None
                quality = CostQuality.UNKNOWN
            usage_known = result.usage.quality != UsageQuality.UNKNOWN
            return await self.ledger.reconcile(s, call, cost_nano=cost_nano, usage_known=usage_known, cost_quality=quality)

    async def _settle_error(self, call_id: str, error: ProviderError, latency_ms: int, price) -> None:  # noqa: ANN001
        async with self.db.session() as s, s.begin():
            call = (await s.execute(select(CallUsage).where(CallUsage.id == call_id))).scalar_one()
            call.latency_ms = latency_ms
            call.error_type = error.error_type
            call.error_message = str(error)[:2000]
            if error.usage_known:
                call.usage_quality = str(UsageQuality.PROVIDER_REPORTED)
                await self.ledger.release(s, call, status="failed")
            else:
                call.usage_quality = str(UsageQuality.UNKNOWN)
                await self.ledger.reconcile(s, call, cost_nano=None, usage_known=False, cost_quality=CostQuality.UNKNOWN)
                call.status = "pending_unknown"

    async def _mark_schema_invalid(self, call_id: str, message: str) -> None:
        async with self.db.session() as s, s.begin():
            call = (await s.execute(select(CallUsage).where(CallUsage.id == call_id))).scalar_one()
            call.error_type = "schema_invalid"
            call.error_message = message[:2000]


def _schema_name(schema: type[BaseModel]) -> str:
    return {
        "ThinkerPlanOutput": "thinker_plan",
        "ResearchOutput": "research",
        "ProposalOutput": "proposal",
        "CritiqueOutput": "critique",
        "JudgeOutput": "judge",
        "ActionPlanOutput": "action_plan",
    }.get(schema.__name__, schema.__name__.lower())


def _parse(content: str, schema: type[T]) -> tuple[T | None, str]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None, f"JSON invalido: {exc}"
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc2:
            return None, f"JSON invalido: {exc2}"
    try:
        return schema.model_validate(data), ""
    except ValidationError as exc:
        return None, "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:6])


def _bucket_view(b: BudgetBucket) -> dict[str, Any]:
    return {
        "bucket_key": b.bucket_key,
        "cap": str(from_nano(b.cap_nano)) if b.cap_nano is not None else None,
        "spent": str(from_nano(b.spent_nano)),
        "reserved": str(from_nano(b.reserved_nano)),
        "provisioned": str(from_nano(b.provision_nano)),
        "pending_unknown": str(from_nano(b.pending_unknown_nano)),
        "calls_used": b.calls_used,
        "calls_provisioned": b.calls_provisioned,
    }


_SECRET_MARKERS = ("api_key", "apikey", "authorization", "secret", "token")


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Eventos publicos nunca carregam chaves/segredos: remove campos com nomes suspeitos."""
    def clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: ("[redacted]" if any(m in k.lower() for m in _SECRET_MARKERS) else clean(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if isinstance(obj, Decimal):
            return str(obj)
        return obj
    return clean(payload)


def make_adapters(settings: Settings, catalog: Catalog) -> dict[str, ProviderAdapter]:
    from app.providers.mock import MockAdapter

    from app.contracts.common import REAL_PROVIDERS
    from app.providers.registry import build_adapter, server_key

    adapters: dict[str, ProviderAdapter] = {Provider.MOCK: MockAdapter()}
    for prov in REAL_PROVIDERS:
        key = server_key(prov, settings)
        if key and catalog.provider_enabled(prov):
            adapters[prov] = build_adapter(prov, key, settings)
    return adapters
