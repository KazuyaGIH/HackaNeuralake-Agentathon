import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app import APP_VERSION
from app.api.deps import Owner, Session
from app.api.intake import IntakeError, payload_hash, persist_run, prepare_run
from app.api.report_md import render_markdown
from app.budget.ledger import Ledger
from app.budget.prices import from_nano
from app.config import REPO_DIR
from app.contracts.artifacts import Report
from app.contracts.challenge import ActionPlanSpec, ChallengeConfig, RefinementSpec, TeamFeedback
from app.contracts.common import TERMINAL_STATUSES, CostQuality, ExecutionMode, RunStatus
from app.contracts.runs import (
    BudgetBucketView,
    CallUsageView,
    CatalogResponse,
    RunCreateResponse,
    RunDetail,
    RunEventView,
    RunMetrics,
    RunSummary,
    SourceCreateResponse,
)
from app.evidence.extract import EXTRACTOR_VERSION, ExtractionError, extract
from app.storage.models import Artifact, BudgetBucket, CallUsage, IdempotencyKey, Run, RunEvent, Source
from app.storage.repo import append_event, get_run, list_artifacts, list_buckets, list_calls, list_events, utcnow

router = APIRouter()
api = APIRouter(prefix="/api/v1")
DEMO_DIR = REPO_DIR / "fixtures" / "demo"


def _err(status_code: int, code: str, message: str, hint: str | None = None) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if hint:
        detail["hint"] = hint
    return HTTPException(status_code, detail)


# --------------------------------------------------------------------------- health / catalog


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    ex = request.app.state.executor
    return {"status": "ok", "app_version": APP_VERSION, "executor": {"enabled": ex is not None, "current_run_id": ex.current_run_id if ex else None}}


@api.get("/catalog", response_model=CatalogResponse)
async def catalog(request: Request, _owner: Owner) -> CatalogResponse:
    return request.app.state.catalog.response(demo_available=(DEMO_DIR / "challenge.json").exists())


# --------------------------------------------------------------------------- sources


async def _store_source(request: Request, session: Session, owner: str, data: bytes, *, title: str, filename: str | None, declared: str | None) -> Source:
    settings = request.app.state.settings
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise _err(413, "too_large", f"arquivo excede {settings.max_upload_mb} MiB")
    if not data:
        raise _err(422, "empty", "conteudo vazio")
    try:
        ext = extract(data, filename=filename, declared_type=declared, max_pdf_pages=settings.max_pdf_pages)
    except ExtractionError as exc:
        raise _err(422, "extraction_failed", str(exc)) from exc
    sha = hashlib.sha256(data).hexdigest()
    existing = (await session.execute(select(Source).where(Source.owner_id == owner, Source.sha256 == sha, Source.extractor_version == EXTRACTOR_VERSION))).scalars().first()
    if existing is not None:
        return existing
    sid = f"src_{uuid.uuid4().hex[:16]}"
    stored_name = f"{sid}{'.pdf' if ext.media_type == 'application/pdf' else '.txt'}"
    (settings.uploads_dir / stored_name).write_bytes(data)
    src = Source(
        id=sid, owner_id=owner, title=title[:200], original_name=(filename or "")[:255] or None, stored_name=stored_name, media_type=ext.media_type,
        size_bytes=len(data), sha256=sha, extraction_status=ext.status, extracted_text=ext.text, pages=ext.pages, chars=len(ext.text),
        truncated=ext.truncated, warnings=ext.warnings, extractor_version=EXTRACTOR_VERSION, created_at=utcnow(),
    )
    session.add(src)
    await session.commit()
    return src


def _source_view(src: Source) -> SourceCreateResponse:
    return SourceCreateResponse(
        source_id=src.id, title=src.title, media_type=src.media_type, size_bytes=src.size_bytes, sha256=src.sha256,
        extraction_status=src.extraction_status, pages=src.pages, chars=src.chars, warnings=list(src.warnings or []),
    )


@api.post("/sources", response_model=SourceCreateResponse, status_code=201)
async def create_source(
    request: Request, session: Session, owner: Owner,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
) -> SourceCreateResponse:
    """Upload de TXT/Markdown/PDF (multipart `file`) ou texto colado (campo `text`)."""
    if file is not None:
        data = await file.read()
        src = await _store_source(request, session, owner, data, title=title or (file.filename or "fonte"), filename=file.filename, declared=file.content_type)
    elif text is not None:
        src = await _store_source(request, session, owner, text.encode("utf-8"), title=title or "texto colado", filename=None, declared="text/plain")
    else:
        raise _err(422, "missing_content", "envie `file` (multipart) ou `text`")
    return _source_view(src)


class TextSourceIn(BaseModel):
    title: str = Field(default="texto colado", max_length=200)
    text: str = Field(min_length=1)


@api.post("/sources/text", response_model=SourceCreateResponse, status_code=201)
async def create_text_source(request: Request, session: Session, owner: Owner, body: TextSourceIn) -> SourceCreateResponse:
    src = await _store_source(request, session, owner, body.text.encode("utf-8"), title=body.title, filename=None, declared="text/markdown")
    return _source_view(src)


@api.get("/sources", response_model=list[SourceCreateResponse])
async def list_sources(session: Session, owner: Owner) -> list[SourceCreateResponse]:
    rows = (await session.execute(select(Source).where(Source.owner_id == owner).order_by(Source.created_at.desc()).limit(200))).scalars()
    return [_source_view(r) for r in rows]


@api.get("/sources/{source_id}")
async def get_source(session: Session, owner: Owner, source_id: str, preview_chars: int = Query(default=1200, ge=0, le=20000)) -> dict[str, Any]:
    src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if src is None or src.owner_id != owner:
        raise _err(404, "not_found", "fonte nao encontrada")
    view = _source_view(src).model_dump()
    view["preview"] = src.extracted_text[:preview_chars]
    return view


# --------------------------------------------------------------------------- runs


def _links(request: Request, run_id: str) -> dict[str, str]:
    base = f"/api/v1/runs/{run_id}"
    return {"self": base, "events": f"{base}/events", "events_poll": f"{base}/events/list", "report_json": f"{base}/report?format=json", "report_md": f"{base}/report?format=md", "cancel": f"{base}/cancel"}


def _client_neuralake_key(request: Request) -> str | None:
    """Chave NeuraLake do proprio usuario, enviada pelo navegador. Usada so em memoria, para esta execucao."""
    key = request.headers.get("x-neuralake-key", "").strip()
    return key or None


def _require_real_access(request: Request, cfg: ChallengeConfig) -> None:
    """Modo real gasta creditos: com senha configurada, toda criacao de execucao real exige X-Agentathon-Key.
    Quem traz a propria chave NeuraLake gasta os proprios creditos e nao precisa da senha do servidor."""
    expected = request.app.state.settings.real_mode_password
    if cfg.mode != ExecutionMode.REAL or not expected or _client_neuralake_key(request):
        return
    given = request.headers.get("x-agentathon-key", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise _err(401, "real_mode_locked", "o modo real esta protegido por senha", "informe a senha do modo real na aba Orcamento e modo")


async def _create_run(request: Request, session: Session, owner: str, cfg: ChallengeConfig, *, idempotency_key: str | None, parent_run_id: str | None = None) -> tuple[Run, bool, list[str]]:
    st = request.app.state
    _require_real_access(request, cfg)
    body_hash = payload_hash(cfg.model_dump(mode="json"))
    if idempotency_key:
        existing = (await session.execute(select(IdempotencyKey).where(IdempotencyKey.owner_id == owner, IdempotencyKey.key == idempotency_key))).scalar_one_or_none()
        if existing is not None:
            if existing.payload_hash != body_hash:
                raise _err(409, "idempotency_conflict", "Idempotency-Key ja usada com payload diferente")
            run = await get_run(session, existing.run_id)
            assert run is not None
            return run, False, []
    client_key = _client_neuralake_key(request) if cfg.mode == ExecutionMode.REAL else None
    try:
        prepared = await prepare_run(cfg, owner_id=owner, session=session, settings=st.settings, catalog=st.catalog, prices=st.prices,
                                     client_neuralake_key=client_key is not None)
    except IntakeError as exc:
        raise _err(422, exc.code, exc.message, exc.hint) from exc
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    ledger = Ledger(st.prices, strict=prepared.snapshot.budget.strict)
    try:
        run = await persist_run(session, prepared, owner_id=owner, run_id=run_id, ledger=ledger, parent_run_id=parent_run_id)
        if idempotency_key:
            session.add(IdempotencyKey(owner_id=owner, key=idempotency_key, payload_hash=body_hash, run_id=run_id, created_at=utcnow()))
        await append_event(session, run_id, "run.queued", {"warnings": prepared.warnings, "parent_run_id": parent_run_id})
        await session.commit()
    except IntegrityError:
        # Corrida entre POSTs simultaneos com a mesma chave: a unicidade (owner_id, key) venceu; devolve o existente.
        await session.rollback()
        existing = (await session.execute(select(IdempotencyKey).where(IdempotencyKey.owner_id == owner, IdempotencyKey.key == idempotency_key))).scalar_one_or_none()
        if existing is None:
            raise
        if existing.payload_hash != body_hash:
            raise _err(409, "idempotency_conflict", "Idempotency-Key ja usada com payload diferente") from None
        run = await get_run(session, existing.run_id)
        assert run is not None
        return run, False, []
    # Despacho somente apos commit. A chave do usuario fica so na memoria do executor ate o run comecar.
    if st.executor is not None:
        if client_key:
            st.executor.run_keys[run_id] = client_key
        st.executor.wake()
    return run, True, prepared.warnings


@api.post("/runs", response_model=RunCreateResponse, status_code=202, responses={200: {"model": RunCreateResponse}, 409: {}, 422: {}})
async def create_run(request: Request, response: Response, session: Session, owner: Owner, cfg: ChallengeConfig, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> RunCreateResponse:
    run, created, warnings = await _create_run(request, session, owner, cfg, idempotency_key=idempotency_key)
    if not created:
        response.status_code = 200
    return RunCreateResponse(run_id=run.id, status=RunStatus(run.status), created=created, links={**_links(request, run.id), **({"warnings": json.dumps(warnings, ensure_ascii=False)} if warnings else {})})


@api.get("/runs", response_model=list[RunSummary])
async def list_runs(session: Session, owner: Owner, limit: int = Query(default=50, ge=1, le=200)) -> list[RunSummary]:
    rows = (await session.execute(select(Run).where(Run.owner_id == owner).order_by(Run.created_at.desc()).limit(limit))).scalars()
    return [
        RunSummary(run_id=r.id, title=r.title, status=RunStatus(r.status), decision_status=r.decision_status, mode=r.mode, created_at=r.created_at,
                   started_at=r.started_at, finished_at=r.finished_at, candidate_count=len(r.snapshot.get("candidates") or []), parent_run_id=r.parent_run_id, simulated=r.simulated)
        for r in rows
    ]


async def _owned_run(session: Session, owner: str, run_id: str) -> Run:
    run = await get_run(session, run_id)
    if run is None or run.owner_id != owner:
        raise _err(404, "not_found", "execucao nao encontrada")
    return run


def _plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {"candidate_id": payload["candidate_id"], "tasks": [{"task_id": t["task_id"], "kind": t["kind"], "competence": t.get("competence")} for t in payload["tasks"]], "validation": payload["validation"]}


@api.get("/runs/{run_id}", response_model=RunDetail)
async def run_detail(session: Session, owner: Owner, run_id: str) -> RunDetail:
    run = await _owned_run(session, owner, run_id)
    arts = await list_artifacts(session, run_id, public_only=False)
    grouped: dict[str, Any] = {}
    for a in arts:
        if a.kind == "task_plan":
            grouped.setdefault("task_plan_summary", []).append(_plan_summary(a.payload))
            continue
        if a.visibility != "public":
            continue
        if a.kind == "report":
            grouped["report"] = a.payload
        else:
            grouped.setdefault(a.kind, []).append(a.payload)
    buckets = await list_buckets(session, run_id)
    calls = await list_calls(session, run_id)
    zero = Decimal("0")
    spent = sum((from_nano(b.spent_nano) or zero for b in buckets), zero)
    reserved = sum((from_nano(b.reserved_nano) or zero for b in buckets), zero)
    pending = sum((from_nano(b.pending_unknown_nano) or zero for b in buckets), zero)
    snap = ChallengeConfig.model_validate(run.snapshot)
    qualities = {c.cost_quality for c in calls}
    quality = CostQuality.UNKNOWN if (pending > 0 or "unknown" in qualities) else (CostQuality.ESTIMATED if ("estimated" in qualities or not calls) else CostQuality.PROVIDER_REPORTED)
    elapsed = ((run.finished_at or utcnow()) - run.started_at).total_seconds() if run.started_at else None
    grouped["calls"] = [
        CallUsageView(
            call_id=c.id, logical_call_id=c.logical_call_id, attempt=c.attempt, stage=c.stage, role=c.role, candidate_id=c.candidate_id, provider=c.provider,
            requested_option=c.requested_option, reported_model=c.reported_model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, usage_quality=c.usage_quality,
            cost=from_nano(c.cost_nano), cost_quality=c.cost_quality, reserved=from_nano(c.reserved_nano) or zero, latency_ms=c.latency_ms, request_id=c.request_id,
            status=c.status, error_type=c.error_type, created_at=c.created_at,
        ).model_dump(mode="json")
        for c in calls
    ]
    return RunDetail(
        run_id=run.id, owner_id=run.owner_id, title=run.title, status=RunStatus(run.status), decision_status=run.decision_status, mode=run.mode, simulated=run.simulated,
        created_at=run.created_at, started_at=run.started_at, finished_at=run.finished_at, cancel_requested_at=run.cancel_requested_at, seed=run.seed, app_version=run.app_version,
        snapshot=snap, snapshot_hashes=run.snapshot_hashes, parent_run_id=run.parent_run_id, error=run.error,
        metrics=RunMetrics(calls_used=run.calls_used, calls_cap=run.calls_cap, spent=spent, reserved=reserved, pending_unknown=pending, cap=snap.budget.total_cap,
                           currency=snap.budget.currency, cost_quality=quality, elapsed_s=elapsed, deadline_s=snap.budget.run_deadline_s),
        budget_buckets=[
            BudgetBucketView(bucket_key=b.bucket_key, cap=from_nano(b.cap_nano), spent=from_nano(b.spent_nano) or zero, reserved=from_nano(b.reserved_nano) or zero,
                             provisioned=from_nano(b.provision_nano) or zero, pending_unknown=from_nano(b.pending_unknown_nano) or zero, calls_used=b.calls_used, calls_provisioned=b.calls_provisioned)
            for b in buckets
        ],
        artifacts=grouped, last_event_seq=run.last_event_seq,
    )


@api.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, session: Session, owner: Owner, run_id: str) -> dict[str, Any]:
    """Idempotente: bloqueia novas chamadas; chamadas em voo terminam e so atualizam uso/artefatos."""
    run = await _owned_run(session, owner, run_id)
    if run.status in TERMINAL_STATUSES:
        return {"run_id": run_id, "status": run.status, "changed": False}
    now = utcnow()
    res = await session.execute(update(Run).where(Run.id == run_id, Run.status == RunStatus.QUEUED).values(status=str(RunStatus.CANCELLED), cancel_requested_at=now, finished_at=now))
    if res.rowcount == 1:
        await append_event(session, run_id, "run.cancelled", {"status": "cancelled", "note": "cancelado antes do despacho"})
        final = str(RunStatus.CANCELLED)
    else:
        res = await session.execute(update(Run).where(Run.id == run_id, Run.status == RunStatus.RUNNING, Run.cancel_requested_at.is_(None)).values(cancel_requested_at=now))
        if res.rowcount == 1:
            await append_event(session, run_id, "run.cancel_requested", {"note": "novas chamadas bloqueadas; aguardando chamadas em voo"})
        final = "cancel_requested"
    await session.commit()
    request.app.state.notifier.notify(run_id)
    return {"run_id": run_id, "status": final, "changed": True}


@api.post("/runs/{run_id}/retry", response_model=RunCreateResponse, status_code=202)
async def retry_run(request: Request, session: Session, owner: Owner, run_id: str) -> RunCreateResponse:
    """Nova tentativa explicita: novo run_id vinculado ao anterior, com a mesma configuracao congelada."""
    run = await _owned_run(session, owner, run_id)
    if run.status not in TERMINAL_STATUSES:
        raise _err(409, "not_terminal", "so e possivel repetir execucoes encerradas")
    cfg = ChallengeConfig.model_validate(run.snapshot)
    new_run, _, _ = await _create_run(request, session, owner, cfg, idempotency_key=None, parent_run_id=run_id)
    return RunCreateResponse(run_id=new_run.id, status=RunStatus(new_run.status), created=True, links=_links(request, new_run.id))


class RefineIn(BaseModel):
    feedback: list[TeamFeedback] = Field(min_length=1, max_length=4)
    general_comment: str = Field(default="", max_length=4000)


class ActionPlanIn(BaseModel):
    candidate_id: str | None = Field(default=None, description="Equipe que monta o plano; padrao = vencedora.")
    instructions: str = Field(default="", max_length=4000)


async def _finished_report(session: Session, run: Run) -> Report:
    if run.status not in TERMINAL_STATUSES:
        raise _err(409, "not_terminal", "a arena ainda esta em execucao")
    arts = [a for a in await list_artifacts(session, run.id) if a.kind == "report"]
    if not arts:
        raise _err(409, "report_not_ready", "a arena terminou sem relatorio")
    return Report.model_validate(arts[-1].payload)


@api.post("/runs/{run_id}/refine", response_model=RunCreateResponse, status_code=202)
async def refine_run(request: Request, session: Session, owner: Owner, run_id: str, body: RefineIn) -> RunCreateResponse:
    """Rodada de melhoria: as equipes escolhidas revisam com o feedback do cliente; todas sao reavaliadas."""
    run = await _owned_run(session, owner, run_id)
    report = await _finished_report(session, run)
    cfg = ChallengeConfig.model_validate(run.snapshot)
    if cfg.action_plan is not None:
        raise _err(422, "invalid_parent", "nao e possivel pedir melhoria sobre um plano de acao")
    with_proposal = {p.candidate_id for p in report.proposals}
    ids = [f.candidate_id for f in body.feedback]
    if len(ids) != len(set(ids)):
        raise _err(422, "invalid_feedback", "cada equipe pode receber um unico comentario por rodada")
    missing = [i for i in ids if i not in with_proposal]
    if missing:
        raise _err(422, "invalid_feedback", f"equipes sem proposta nesta arena: {', '.join(missing)}")
    round_no = (cfg.refinement.round + 1) if cfg.refinement else 1
    try:
        spec = RefinementSpec(parent_run_id=run_id, round=round_no, feedback=body.feedback, general_comment=body.general_comment)
    except ValueError as exc:
        raise _err(422, "comment_required", "escreva um comentario geral ou um comentario para cada equipe escolhida") from exc
    new_cfg = cfg.model_copy(update={"refinement": spec, "action_plan": None})
    new_run, _, _ = await _create_run(request, session, owner, new_cfg, idempotency_key=None, parent_run_id=run_id)
    return RunCreateResponse(run_id=new_run.id, status=RunStatus(new_run.status), created=True, links=_links(request, new_run.id))


@api.post("/runs/{run_id}/action-plan", response_model=RunCreateResponse, status_code=202)
async def action_plan_run(request: Request, session: Session, owner: Owner, run_id: str, body: ActionPlanIn) -> RunCreateResponse:
    """Entrega final: a equipe escolhida (padrao: vencedora) transforma a proposta em plano de acao."""
    run = await _owned_run(session, owner, run_id)
    report = await _finished_report(session, run)
    cfg = ChallengeConfig.model_validate(run.snapshot)
    if cfg.action_plan is not None:
        # Sobre um plano pronto: nova versao mais detalhada, da mesma equipe.
        if report.action_plan is None:
            raise _err(422, "invalid_parent", "este plano nao foi produzido; peca um novo plano a partir da arena")
        if not body.instructions.strip():
            raise _err(422, "detail_required", "diga o que o plano deve detalhar")
        spec = ActionPlanSpec(parent_run_id=run_id, candidate_id=report.action_plan.candidate_id, instructions=body.instructions)
        new_run, _, _ = await _create_run(request, session, owner, cfg.model_copy(update={"action_plan": spec}), idempotency_key=None, parent_run_id=run_id)
        return RunCreateResponse(run_id=new_run.id, status=RunStatus(new_run.status), created=True, links=_links(request, new_run.id))
    cid = body.candidate_id or report.winner_candidate_id
    if not cid:
        raise _err(422, "no_winner", "sem vencedora nesta arena: escolha a equipe que vai montar o plano")
    if cid not in {p.candidate_id for p in report.proposals}:
        raise _err(422, "invalid_candidate", f"equipe '{cid}' nao tem proposta nesta arena")
    spec = ActionPlanSpec(parent_run_id=run_id, candidate_id=cid, instructions=body.instructions)
    new_cfg = cfg.model_copy(update={"action_plan": spec, "refinement": None})
    new_run, _, _ = await _create_run(request, session, owner, new_cfg, idempotency_key=None, parent_run_id=run_id)
    return RunCreateResponse(run_id=new_run.id, status=RunStatus(new_run.status), created=True, links=_links(request, new_run.id))


@api.delete("/runs/{run_id}", status_code=204)
async def delete_run(session: Session, owner: Owner, run_id: str) -> Response:
    """Exclui uma execucao encerrada e todos os seus registros (eventos, artefatos, chamadas, orcamento)."""
    run = await _owned_run(session, owner, run_id)
    if run.status not in TERMINAL_STATUSES:
        raise _err(409, "not_terminal", "cancele a execucao antes de excluir")
    for model in (RunEvent, Artifact, CallUsage, BudgetBucket, IdempotencyKey):
        await session.execute(delete(model).where(model.run_id == run_id))
    await session.execute(delete(Run).where(Run.id == run_id))
    await session.commit()
    return Response(status_code=204)


@api.get("/runs/{run_id}/report", responses={200: {"model": Report, "content": {"application/json": {}, "text/markdown": {"schema": {"type": "string"}}}}})
async def run_report(session: Session, owner: Owner, run_id: str, format: Literal["json", "md"] = "json") -> Response:
    run = await _owned_run(session, owner, run_id)
    arts = [a for a in await list_artifacts(session, run_id) if a.kind == "report"]
    if not arts:
        raise _err(404, "report_not_ready", f"relatorio ainda nao disponivel (status={run.status})")
    report = Report.model_validate(arts[-1].payload)
    if format == "md":
        return PlainTextResponse(render_markdown(report, ChallengeConfig.model_validate(run.snapshot)), media_type="text/markdown; charset=utf-8")
    return Response(content=report.model_dump_json(indent=2), media_type="application/json")


@api.get("/runs/{run_id}/events/list", response_model=list[RunEventView])
async def events_list(session: Session, owner: Owner, run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=2000)) -> list[RunEventView]:
    await _owned_run(session, owner, run_id)
    rows = await list_events(session, run_id, after, limit)
    return [RunEventView(seq=e.seq, type=e.type, ts=e.ts, run_id=e.run_id, payload=e.payload) for e in rows]


@api.get("/runs/{run_id}/events")
async def events_sse(request: Request, session: Session, owner: Owner, run_id: str, after: int = Query(default=0, ge=0), last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None) -> StreamingResponse:
    """SSE com IDs sequenciais. Reconexao via Last-Event-ID (ou ?after=). Transmite apenas estado/resultados publicos."""
    await _owned_run(session, owner, run_id)
    start = after
    if last_event_id and last_event_id.isdigit():
        start = max(start, int(last_event_id))
    db = request.app.state.db
    notifier = request.app.state.notifier

    async def gen() -> AsyncIterator[str]:
        last = start
        yield "retry: 2000\n\n"
        while True:
            async with db.session() as s:
                events = await list_events(s, run_id, last)
                run = await get_run(s, run_id)
            for e in events:
                last = e.seq
                yield f"id: {e.seq}\nevent: {e.type}\ndata: {json.dumps({'seq': e.seq, 'type': e.type, 'ts': e.ts.isoformat(), 'run_id': run_id, 'payload': e.payload}, ensure_ascii=False, default=str)}\n\n"
            if run is None or (run.status in TERMINAL_STATUSES and last >= run.last_event_seq):
                yield f"event: stream.end\ndata: {json.dumps({'status': run.status if run else 'unknown'})}\n\n"
                return
            if await request.is_disconnected():
                return
            await notifier.wait(run_id, timeout=1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --------------------------------------------------------------------------- demo


@api.post("/demo/prepare")
async def demo_prepare(request: Request, session: Session, owner: Owner) -> dict[str, Any]:
    """Cria as fontes SINTETICAS do cenario de demonstracao para o proprietario e devolve a configuracao pronta."""
    cfg_path = DEMO_DIR / "challenge.json"
    if not cfg_path.exists():
        raise _err(404, "demo_missing", "fixtures/demo/challenge.json nao encontrado")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    docs: list[str] = data.pop("documents", [])
    source_ids: list[str] = []
    for name in docs:
        p = Path(DEMO_DIR / name)
        if not p.exists():
            raise _err(500, "demo_missing", f"documento de demo ausente: {name}")
        src = await _store_source(request, session, owner, p.read_bytes(), title=p.stem.replace("_", " ") + " (SINTETICO)", filename=p.name, declared="text/markdown")
        source_ids.append(src.id)
    data["source_ids"] = source_ids
    cfg = ChallengeConfig.model_validate(data)
    return {"challenge": cfg.model_dump(mode="json"), "documents": docs, "note": "Dados sinteticos identificados como SIMULADO/SINTETICO; empresa e precos ficticios."}


router.include_router(api)
