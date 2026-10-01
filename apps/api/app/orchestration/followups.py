"""Execucoes derivadas de uma arena encerrada: rodada de melhoria (feedback do cliente) e plano de acao final.

Ambas partem dos artefatos congelados da execucao-mae (pacote de evidencias, propostas, avaliacoes) e nao
repetem as etapas anteriores: so as chamadas novas sao feitas e contabilizadas nesta execucao.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.agents import prompts as P
from app.budget.ledger import candidate_bucket
from app.budget.prices import from_nano
from app.contracts.artifacts import ActionPlan, ActionPlanOutput, EvidencePack, Report
from app.orchestration import phases
from app.orchestration.coordinator import CallDenied, CallFailed, RunContext
from app.storage.models import Run
from app.storage.repo import list_artifacts, list_buckets


async def load_parent(ctx: RunContext, parent_run_id: str) -> Report:
    """Carrega o estado final da execucao-mae no contexto (pacote, propostas finais, verificacoes, criticas)."""
    async with ctx.db.session() as s:
        arts = await list_artifacts(s, parent_run_id, public_only=False)
    reports = [a for a in arts if a.kind == "report"]
    packs = [a for a in arts if a.kind == "evidence_pack"]
    if not reports or not packs:
        raise ValueError("execucao-mae sem relatorio ou pacote de evidencias")
    report = Report.model_validate(reports[-1].payload)
    ctx.parent_report = report
    ctx.pack = EvidencePack.model_validate(max(packs, key=lambda a: a.version).payload)
    # So as equipes em disputa nesta execucao (na repescagem, as demais ficam de fora).
    active = {c.candidate_id for c in ctx.candidates}
    ctx.proposals = {p.candidate_id: p for p in report.proposals if p.candidate_id in active}
    ctx.verifications = {v.candidate_id: v for v in report.verifications if v.candidate_id in active}
    ctx.critiques = [c for c in report.critiques if c.author_candidate_id in active and c.target_candidate_id in active]
    return report


async def _chain_costs(ctx: RunContext, parent_run_id: str) -> None:
    """Soma o custo/cota de todas as rodadas anteriores da cadeia de melhorias (mae, avo, ...)."""
    seen: set[str] = set()
    current: str | None = parent_run_id
    totals: dict[str, tuple[Decimal, Decimal | None]] = {}
    while current and current not in seen:
        seen.add(current)
        async with ctx.db.session() as s:
            run = (await s.execute(select(Run).where(Run.id == current))).scalar_one_or_none()
            if run is None:
                break
            buckets = {b.bucket_key: b for b in await list_buckets(s, current)}
        for c in ctx.candidates:
            cid = c.candidate_id or ""
            b = buckets.get(candidate_bucket(cid))
            spent = (from_nano(b.spent_nano) if b else None) or Decimal("0")
            quota = from_nano(b.cap_nano) if b and b.cap_nano is not None else None
            prev_s, prev_q = totals.get(cid, (Decimal("0"), Decimal("0")))
            totals[cid] = (prev_s + spent, None if quota is None or prev_q is None else prev_q + quota)
        refinement = (run.snapshot or {}).get("refinement")
        current = refinement.get("parent_run_id") if refinement else None
    ctx.inherited_costs = totals


StepFn = Callable[[RunContext], Awaitable[Any]]


async def _step(ctx: RunContext, name: str, fn: StepFn, *, always: bool = False) -> None:
    if ctx.halt in ("cancelled", "failed") and not always:
        return
    if ctx.halt not in ("cancelled", "failed"):
        await ctx.check_cancel()
    try:
        await fn(ctx)
    except Exception as exc:  # noqa: BLE001 - falha inesperada: preserva artefatos e encerra honestamente
        ctx.set_halt("failed", f"{name}: {type(exc).__name__}: {exc}")


async def _start(ctx: RunContext, kind: str) -> None:
    await ctx.emit("run.started", {"mode": str(ctx.snapshot.mode), "simulated": ctx.simulated, "kind": kind, "candidates": [
        {"candidate_id": c.candidate_id, "name": c.name, "provider": str(c.provider), "model_option": c.model_option, "color": c.color}
        for c in ctx.candidates
    ], "seed": ctx.seed})
    assert ctx.pack is not None
    await ctx.save_artifact("evidence_pack", ctx.pack, version=ctx.pack.version)
    await ctx.emit("evidence.ready", {"version": ctx.pack.version, "items": len(ctx.pack.items), "derived": 0, "frozen": True, "gaps": ctx.pack.gaps, "inherited": True})
    await ctx.emit_budget()


# --------------------------------------------------------------------------- rodada de melhoria


async def phase_feedback(ctx: RunContext) -> None:
    spec = ctx.snapshot.refinement
    assert spec is not None
    wanted = {f.candidate_id: f for f in spec.feedback}

    async def one(cid: str) -> None:
        f = wanted[cid]
        await phases._propose_one(ctx, cid, None, feedback={"comment": f.comment, "general_comment": spec.general_comment, "round": spec.round})

    await asyncio.gather(*(one(cid) for cid in sorted(wanted) if cid in ctx.proposals))


async def run_refinement(ctx: RunContext) -> str:
    spec = ctx.snapshot.refinement
    assert spec is not None
    report: Report | None = None
    try:
        await load_parent(ctx, spec.parent_run_id)
        await _chain_costs(ctx, spec.parent_run_id)
    except Exception as exc:  # noqa: BLE001
        ctx.set_halt("failed", f"carregar rodada anterior: {type(exc).__name__}: {exc}")
    if ctx.pack is not None:
        await _step(ctx, "start", lambda c: _start(c, "refinement"))
        await _step(ctx, "feedback", phase_feedback)
        await _step(ctx, "verify", phases.phase_verify, always=True)
        await _step(ctx, "judge", phases.phase_judge, always=True)
        try:
            report = await phases.phase_rank_report(ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.set_halt("failed", f"rank_report: {type(exc).__name__}: {exc}")
    final = await phases.phase_finalize(ctx, report)
    return str(final)


# --------------------------------------------------------------------------- plano de acao


async def phase_action_plan(ctx: RunContext) -> None:
    spec = ctx.snapshot.action_plan
    assert spec is not None and ctx.pack is not None and ctx.parent_report is not None
    cid = spec.candidate_id
    cand = ctx.candidate(cid)
    proposal = ctx.proposals[cid]
    rep = ctx.parent_report
    review = {
        "verificacao": next((v.model_dump(mode="json") for v in rep.verifications if v.candidate_id == cid), None),
        "objecoes_dos_juizes": [o for e in rep.evaluations if e.candidate_id == cid for o in e.objections],
        "criticas_recebidas": [c.model_dump(mode="json", exclude={"call_ids"}) for c in rep.critiques if c.target_candidate_id == cid],
        "nota_final": next((str(r.score_0_100) for r in rep.ranking if r.candidate_id == cid), None),
    }
    # Pedido sobre um plano ja pronto: a equipe detalha a versao anterior em vez de comecar do zero.
    previous = rep.action_plan if rep.action_plan and rep.action_plan.candidate_id == cid else None
    version = previous.version + 1 if previous else 1
    prev_json = previous.model_dump(mode="json", exclude={"call_ids", "invalid_evidence_ids"}) if previous else None
    await ctx.emit("action_plan.started", {"candidate_id": cid, "version": version})
    try:
        out, call_ids = await ctx.call(
            role="thinker", stage="action_plan", candidate_id=cid, provider=str(cand.provider), option=cand.model_option,
            system=P.THINKER_SYSTEM,
            user=P.action_plan_user(ctx.snapshot.model_dump(mode="json"), cand.model_dump(mode="json"), ctx.pack.model_dump(mode="json"),
                                    proposal.model_dump(mode="json", exclude={"call_ids"}), review, spec.instructions, previous_plan=prev_json),
            schema=ActionPlanOutput, max_output_tokens=max(cand.max_output_tokens, 4000 if previous else 3000), protected=True,
            metadata={**phases._base_meta(ctx, cid), "proposal": proposal.model_dump(mode="json"), "review": review, "plan_instructions": spec.instructions,
                      "previous_plan": prev_json},
        )
    except (CallDenied, CallFailed) as exc:
        reason = getattr(exc, "reason", str(exc))
        ctx.partial_reasons.append(f"{cand.name}: plano de acao nao produzido ({reason})")
        await ctx.emit("action_plan.failed", {"candidate_id": cid, "reason": reason})
        return
    known = ctx.pack.ids()
    data = out.model_dump()
    data["evidence_ids"] = [e for e in out.evidence_ids if e in known]
    plan = ActionPlan(**data, candidate_id=cid, proposal_version=proposal.version, version=version, detail_request=spec.instructions if previous else "",
                      invalid_evidence_ids=sorted({e for e in out.evidence_ids if e not in known}), call_ids=call_ids)
    ctx.action_plan = plan
    await ctx.save_artifact("action_plan", plan, candidate_id=cid, version=version)
    await ctx.emit("action_plan.ready", {"candidate_id": cid, "title": plan.title, "phases": len(plan.phases), "version": version})


async def _action_report(ctx: RunContext) -> Report:
    """O ranking e o da arena-mae (o plano nao reavalia ninguem); custo e status sao desta execucao."""
    assert ctx.parent_report is not None
    costs = await ctx.costs()
    limitations = list(ctx.parent_report.limitations) + ctx.partial_reasons
    report = ctx.parent_report.model_copy(update={
        "run_id": ctx.run_id, "generated_at": datetime.now(UTC), "status": phases._intended_status(ctx), "replay": False,
        "cost": await phases.cost_breakdown(ctx, costs), "action_plan": ctx.action_plan, "limitations": limitations,
        "next_steps": (ctx.action_plan.next_steps if ctx.action_plan else ctx.parent_report.next_steps),
    })
    await ctx.save_artifact("report", report)
    await ctx.emit("report.ready", {"decision_status": str(report.decision_status), "winner_candidate_id": report.winner_candidate_id, "action_plan": ctx.action_plan is not None})
    return report


async def run_action_plan(ctx: RunContext) -> str:
    spec = ctx.snapshot.action_plan
    assert spec is not None
    report: Report | None = None
    try:
        await load_parent(ctx, spec.parent_run_id)
    except Exception as exc:  # noqa: BLE001
        ctx.set_halt("failed", f"carregar arena: {type(exc).__name__}: {exc}")
    if ctx.pack is not None and ctx.parent_report is not None:
        await _step(ctx, "start", lambda c: _start(c, "action_plan"))
        await _step(ctx, "action_plan", phase_action_plan)
        try:
            report = await _action_report(ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.set_halt("failed", f"report: {type(exc).__name__}: {exc}")
    final = await phases.phase_finalize(ctx, report)
    return str(final)
