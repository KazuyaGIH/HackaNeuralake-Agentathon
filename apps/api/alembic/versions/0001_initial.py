"""schema inicial

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("stored_name", sa.String(120), nullable=True),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=False, server_default=""),
        sa.Column("pages", sa.Integer, nullable=True),
        sa.Column("chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("warnings", sa.JSON, nullable=False),
        sa.Column("extractor_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"])
    op.create_index("ix_sources_sha256", "sources", ["sha256"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decision_status", sa.String(30), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("simulated", sa.Boolean, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("snapshot_hashes", sa.JSON, nullable=False),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("app_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_run_id", sa.String(40), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("calls_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("calls_cap", sa.Integer, nullable=False),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("last_event_seq", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_runs_owner_id", "runs", ["owner_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("owner_id", sa.String(80), primary_key=True),
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("candidate_id", sa.String(40), nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("visibility", sa.String(10), nullable=False, server_default="public"),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "kind", "candidate_id", "version", name="uq_artifact"),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    op.create_table(
        "budget_buckets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("bucket_key", sa.String(60), nullable=False),
        sa.Column("cap_nano", sa.BigInteger, nullable=True),
        sa.Column("spent_nano", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("reserved_nano", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("provision_nano", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("pending_unknown_nano", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("calls_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("calls_provisioned", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "bucket_key", name="uq_bucket"),
    )
    op.create_index("ix_budget_buckets_run_id", "budget_buckets", ["run_id"])

    op.create_table(
        "call_usages",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("logical_call_id", sa.String(80), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("candidate_id", sa.String(40), nullable=True),
        sa.Column("bucket_key", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("requested_option", sa.String(64), nullable=False),
        sa.Column("reported_model", sa.String(120), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("usage_quality", sa.String(20), nullable=False),
        sa.Column("price_version", sa.String(40), nullable=False),
        sa.Column("cost_nano", sa.BigInteger, nullable=True),
        sa.Column("cost_quality", sa.String(20), nullable=False),
        sa.Column("reserved_nano", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("request_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_type", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_call_usages_run_id", "call_usages", ["run_id"])
    op.create_index("ix_call_usages_logical", "call_usages", ["run_id", "logical_call_id"])


def downgrade() -> None:
    for t in ("call_usages", "budget_buckets", "run_events", "artifacts", "idempotency_keys", "runs", "sources"):
        op.drop_table(t)
