from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite nao guarda fuso: persiste em UTC naive e devolve sempre timezone-aware (UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON, datetime: UTCDateTime}


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extraction_status: Mapped[str] = mapped_column(String(20))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    extractor_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    decision_status: Mapped[str] = mapped_column(String(30))
    mode: Mapped[str] = mapped_column(String(10))
    simulated: Mapped[bool] = mapped_column(Boolean)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_hashes: Mapped[dict[str, Any]] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(Integer)
    app_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    calls_cap: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    owner_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "kind", "candidate_id", "version", name="uq_artifact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    candidate_id: Mapped[str] = mapped_column(String(40), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    visibility: Mapped[str] = mapped_column(String(10), default="public")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class BudgetBucket(Base):
    __tablename__ = "budget_buckets"
    __table_args__ = (UniqueConstraint("run_id", "bucket_key", name="uq_bucket"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True)
    bucket_key: Mapped[str] = mapped_column(String(60))
    cap_nano: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spent_nano: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_nano: Mapped[int] = mapped_column(BigInteger, default=0)
    provision_nano: Mapped[int] = mapped_column(BigInteger, default=0)
    pending_unknown_nano: Mapped[int] = mapped_column(BigInteger, default=0)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    calls_provisioned: Mapped[int] = mapped_column(Integer, default=0)


class CallUsage(Base):
    __tablename__ = "call_usages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True)
    logical_call_id: Mapped[str] = mapped_column(String(80))
    attempt: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(20))
    candidate_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bucket_key: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(20))
    requested_option: Mapped[str] = mapped_column(String(64))
    reported_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_quality: Mapped[str] = mapped_column(String(20))
    price_version: Mapped[str] = mapped_column(String(40))
    cost_nano: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost_quality: Mapped[str] = mapped_column(String(20))
    reserved_nano: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    error_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


Index("ix_call_usages_logical", CallUsage.run_id, CallUsage.logical_call_id)
