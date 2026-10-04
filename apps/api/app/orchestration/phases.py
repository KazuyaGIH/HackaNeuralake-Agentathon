"""Fases do fluxo. Regras, limites e validacoes ficam aqui e no coordenador, nunca nos modelos."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.agents import prompts as P
from app.budget.ledger import candidate_bucket
from app.budget.prices import NEURALAKE_OPTIONS, from_nano
from app.contracts.artifacts import (
    CostBreakdown,
    Critique,
    CritiqueOutput,
    Evaluation,
    EvidenceItem,
    EvidenceLocator,
    Finding,
    JudgeOutput,
    PlanRejection,
    PlanValidation,
    Proposal,
    ProposalOutput,
    Report,
    ResearchOutput,
    SpecialistTask,
    TaskPlan,
    TaskResult,
    ThinkerPlanOutput,
    Verification,
)
from app.contracts.challenge import CandidateConfig, JudgeConfig
from app.contracts.common import CostQuality, DecisionStatus, EvidenceType, RunStatus, SpecialistKind
from app.evaluation.judge import JudgeOutputError, anonymize, judge_criteria, parse_judge_output
from app.evaluation.ranking import CandidateInput, PanelJudge, compute_ranking
from app.evaluation.verifiers import verify_proposal
from app.evidence.calc import CalculationError, MissingInputError, run_calculation
from app.evidence.pack import SourceText, brief_items, build_pack, freeze_with_derivations
from app.evidence.retrieval import retrieve
from app.orchestration.coordinator import CallDenied, CallFailed, RunContext
from app.storage.models import Source
from app.storage.repo import finish_run


def _evidence_meta(ctx: RunContext, max_items: int = 80) -> list[dict[str, Any]]:
    assert ctx.pack is not None
    return [{"evidence_id": i.evidence_id, "excerpt": i.excerpt[:400], "type": str(i.type)} for i in ctx.pack.items[:max_items]]


def _base_meta(ctx: RunContext, cid: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "objective": ctx.snapshot.objective,
        "constraints": [c.model_dump(mode="json") for c in ctx.snapshot.constraints],
        "evidence": _evidence_meta(ctx),
    }
    if cid is not None:
        cand = ctx.candidate(cid)
        meta.update({
            "candidate_index": ctx.candidate_index(cid), "candidate_id": cid, "candidate_name": cand.name,
            "instructions": cand.instructions, "allowed_specialists": [str(k) for k in cand.allowed_specialists],
            "max_tasks": cand.max_specialist_tasks,
        })
    return meta


def research_model(cand: CandidateConfig, t: SpecialistTask) -> tuple[str, str]:
    """(tier, opcao) da pesquisa: o economico quando existe e o pensante nao pediu o principal explicitamente."""
    if not cand.secondary_model_option:
        return "main", cand.model_option
    if t.model_tier == "main" or (t.model_tier is None and "research" not in cand.secondary_for):
        return "main", cand.model_option
    return "secondary", cand.secondary_model_option


def critique_model(cand: CandidateConfig) -> tuple[str, str]:
    if cand.secondary_model_option and "critique" in cand.secondary_for:
        return "secondary", cand.secondary_model_option
    return "main", cand.model_option


# --------------------------------------------------------------------------- 1. evidencias


async def phase_evidence(ctx: RunContext) -> None:
    await ctx.emit("run.started", {"mode": str(ctx.snapshot.mode), "simulated": ctx.simulated, "candidates": [
        {"candidate_id": c.candidate_id, "name": c.name, "provider": str(c.provider), "model_option": c.model_option, "color": c.color}
        for c in ctx.candidates
    ], "critique_rounds": ctx.snapshot.critique_rounds, "seed": ctx.seed})
    texts: list[SourceText] = []
    if ctx.snapshot.source_ids:
        async with ctx.db.session() as s:
            rows = list((await s.execute(select(Source).where(Source.id.in_(ctx.snapshot.source_ids)))).scalars())
        by_id = {r.id: r for r in rows}
        for sid in ctx.snapshot.source_ids:
            r = by_id.get(sid)
            if r is None:
                ctx.limitations.append(f"fonte {sid} nao encontrada na execucao")
                continue
            texts.append(SourceText(r.id, r.title, r.media_type, r.extracted_text, r.sha256, r.pages, r.truncated, list(r.warnings or [])))
    brief = brief_items(ctx.snapshot.objective, ctx.snapshot.context, list(ctx.snapshot.constraints))
    ctx.pack = build_pack(texts, brief)
    await ctx.save_artifact("evidence_pack", ctx.pack, version=1)
    await ctx.emit("evidence.ready", {"version": 1, "items": len(ctx.pack.items), "sources": len(ctx.pack.sources), "gaps": ctx.pack.gaps})


# --------------------------------------------------------------------------- 2. planejamento


def validate_plan(ctx: RunContext, cid: str, out: ThinkerPlanOutput) -> TaskPlan:
    cand = ctx.candidate(cid)
    allowed = {str(k) for k in cand.allowed_specialists}
    catalog_kinds = ctx.catalog.specialist_kinds()
    accepted: list[SpecialistTask] = []
    rejected: list[PlanRejection] = []
    seen: set[str] = set()
    for t in out.tasks:
        if t.task_id in seen:
            rejected.append(PlanRejection(task_id=t.task_id, reason="task_id duplicado"))
            continue
        seen.add(t.task_id)
        if t.kind not in catalog_kinds:
            rejected.append(PlanRejection(task_id=t.task_id, reason=f"especialista '{t.kind}' nao existe no catalogo"))
            continue
        if t.kind not in allowed:
            rejected.append(PlanRejection(task_id=t.task_id, reason=f"especialista '{t.kind}' nao autorizado para este candidato"))
            continue
        if t.kind == SpecialistKind.DOCUMENT_RESEARCH and not t.query:
            rejected.append(PlanRejection(task_id=t.task_id, reason="pesquisa sem query"))
            continue
        if t.kind == SpecialistKind.CALCULATION and t.calculation is None:
            rejected.append(PlanRejection(task_id=t.task_id, reason="calculo sem especificacao tipada"))
            continue
        if any(d not in {a.task_id for a in accepted} for d in t.depends_on):
            rejected.append(PlanRejection(task_id=t.task_id, reason="dependencia invalida (sem recursao/ordem)"))
            continue
        if len(accepted) >= cand.max_specialist_tasks:
            rejected.append(PlanRejection(task_id=t.task_id, reason=f"excede o limite de {cand.max_specialist_tasks} tarefas"))
            continue
        accepted.append(t)
    return TaskPlan(
        candidate_id=cid, strategy_summary=out.strategy_summary, tasks=accepted,
        validation=PlanValidation(accepted_task_ids=[t.task_id for t in accepted], rejected=rejected, adjusted=bool(rejected)),
    )


async def phase_plan(ctx: RunContext) -> None:
    if ctx.halted or ctx.pack is None:
        return
    pack = ctx.pack.model_dump(mode="json")

    async def one(cid: str) -> None:
        cand = ctx.candidate(cid)
        if cand.max_specialist_tasks == 0:
            ctx.plans[cid] = TaskPlan(candidate_id=cid, strategy_summary="(sem delegacao configurada)", tasks=[], validation=PlanValidation(accepted_task_ids=[], rejected=[], adjusted=False))
            return
        allowed = [str(k) for k in cand.allowed_specialists]
        try:
            out, call_ids = await ctx.call(
                role="thinker", stage="plan", candidate_id=cid, provider=str(cand.provider), option=cand.model_option,
                system=P.THINKER_SYSTEM, user=P.plan_user(ctx.snapshot.model_dump(mode="json"), cand.model_dump(mode="json"), pack, allowed, cand.max_specialist_tasks),
                schema=ThinkerPlanOutput, max_output_tokens=min(cand.max_output_tokens, 1500),
                metadata={**_base_meta(ctx, cid), "secondary_model_option": cand.secondary_model_option},
            )
            plan = validate_plan(ctx, cid, out)
        except (CallDenied, CallFailed) as exc:
            reason = getattr(exc, "reason", str(exc))
            plan = TaskPlan(candidate_id=cid, strategy_summary="(planejamento indisponivel)", tasks=[], validation=PlanValidation(accepted_task_ids=[], rejected=[], adjusted=True))
            ctx.operational_changes.append(f"{cand.name}: planejamento sem especialistas ({reason})")
        ctx.plans[cid] = plan
        await ctx.save_artifact("task_plan", plan, candidate_id=cid, visibility="private")
        await ctx.emit("plan.ready", {"candidate_id": cid, "accepted": plan.validation.accepted_task_ids,
                                      "rejected": [r.model_dump() for r in plan.validation.rejected], "adjusted": plan.validation.adjusted})

    await asyncio.gather(*(one(c.candidate_id) for c in ctx.candidates if c.candidate_id))


# --------------------------------------------------------------------------- 3. delegacao


def _fair_task_limit(ctx: RunContext) -> int:
    """Politica comum: tarefas por candidato limitadas pelos slots livres apos proteger consolidacao, rodada e Judge."""
    n = len(ctx.candidates)
    protected = n + len(ctx.judges) + (2 * n if ctx.snapshot.critique_rounds else 0)
    used = ctx._call_counter  # chamadas logicas ja iniciadas nesta execucao
    free = ctx.snapshot.budget.max_total_calls - used - protected
    return max(0, free // max(1, n))


async def phase_delegate(ctx: RunContext) -> None:
    if ctx.halted or ctx.pack is None:
        return
    limit = _fair_task_limit(ctx)
    if any(len(p.tasks) > limit for p in ctx.plans.values()):
        ctx.operational_changes.append(f"tarefas especializadas limitadas a {limit} por candidato para proteger consolidacao, rodada e Judge (politica comum)")
    known = ctx.pack.ids()

    async def one(cid: str) -> None:
        plan = ctx.plans.get(cid)
        results: list[TaskResult] = []
        cand = ctx.candidate(cid)
        for t in (plan.tasks[:limit] if plan else []):
            tier, option = research_model(cand, t) if t.kind == SpecialistKind.DOCUMENT_RESEARCH else ("none", None)
            await ctx.emit("task.started", {"candidate_id": cid, "task_id": t.task_id, "kind": t.kind, "model_tier": tier, "model_option": option})
            results.append(await _run_task(ctx, cid, t, known))
            await ctx.emit("task.completed", {"candidate_id": cid, "task_id": t.task_id, "kind": t.kind, "status": results[-1].status, "error": results[-1].error,
                                              "model_tier": tier, "model_option": option})
        ctx.task_results[cid] = results
        for r in results:
            await ctx.save_artifact("task_result", r, candidate_id=f"{cid}:{r.task_id}")

    await asyncio.gather(*(one(c.candidate_id) for c in ctx.candidates if c.candidate_id))


async def _run_task(ctx: RunContext, cid: str, t: SpecialistTask, known: set[str]) -> TaskResult:
    cand = ctx.candidate(cid)
    if t.kind == SpecialistKind.CALCULATION:
        assert t.calculation is not None
        try:
            d = run_calculation(t.calculation, known, {i.evidence_id: i for i in ctx.pack.items} if ctx.pack else None)
        except MissingInputError as exc:
            return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.CALCULATION, status="skipped", error=f"pendencia: {exc}")
        except CalculationError as exc:
            return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.CALCULATION, status="failed", error=str(exc))
        item = EvidenceItem(
            evidence_id=f"drv-{cid}-{t.task_id}", source_id=None, type=EvidenceType.DERIVED_CALCULATION,
            excerpt=f"{d.formula} = {d.result} {d.unit} (entradas: " + ", ".join(f"{i.name}={i.value}" for i in d.inputs) + ")",
            locator=EvidenceLocator(section="derivacao"), provenance=f"specialist:calculation:{cid}:{t.task_id}", derivation=d,
        )
        return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.CALCULATION, status="completed",
                          findings=[Finding(claim=f"{d.formula} = {d.result} {d.unit}", evidence_ids=[item.evidence_id], confidence="high")],
                          derived_evidence=[item], model_tier="none")
    assert ctx.pack is not None
    tier, option = research_model(cand, t)
    used = {"model_tier": tier, "model_option": option}
    excerpts = retrieve(t.query or "", ctx.pack.items, k=6)
    ex_meta = [{"evidence_id": e.evidence_id, "excerpt": e.excerpt[:900]} for e in excerpts]
    try:
        out, call_ids = await ctx.call(
            role="specialist", stage="research", candidate_id=cid, provider=str(cand.provider), option=option,
            system=P.SPECIALIST_SYSTEM, user=P.research_user(t.query or "", ex_meta), schema=ResearchOutput,
            max_output_tokens=800, metadata={**_base_meta(ctx, cid), "query": t.query, "excerpts": ex_meta},
        )
    except CallDenied as exc:
        ctx.operational_changes.append(f"{cand.name}: tarefa {t.task_id} nao admitida ({exc.reason})")
        return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.DOCUMENT_RESEARCH, status="skipped", error=exc.reason, **used)
    except CallFailed as exc:
        return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.DOCUMENT_RESEARCH, status="failed", error=exc.reason, call_ids=exc.call_ids, **used)
    findings = []
    for f in out.findings:
        valid = [e for e in f.evidence_ids if e in known]
        if valid:
            findings.append(Finding(claim=f.claim, evidence_ids=valid, confidence=f.confidence))
    return TaskResult(task_id=t.task_id, candidate_id=cid, kind=SpecialistKind.DOCUMENT_RESEARCH, status="completed", findings=findings, call_ids=call_ids, **used)


# --------------------------------------------------------------------------- 4. sincronizacao (barreira unica)


async def phase_sync(ctx: RunContext) -> None:
    if ctx.pack is None:
        return
    derived: list[EvidenceItem] = []
    gaps: list[str] = []
    for cid, results in ctx.task_results.items():
        for r in results:
            if r.shareable and r.status == "completed":
                derived.extend(r.derived_evidence)
            elif r.kind == SpecialistKind.CALCULATION and r.status == "skipped" and r.error:
                gaps.append(f"{ctx.candidate(cid).name}, calculo {r.task_id}: {r.error}")
    if not ctx.halted:
        ctx.pack = freeze_with_derivations(ctx.pack, derived, gaps)
        await ctx.save_artifact("evidence_pack", ctx.pack, version=ctx.pack.version)
        await ctx.emit("evidence.ready", {"version": ctx.pack.version, "items": len(ctx.pack.items), "derived": len(derived), "frozen": True, "gaps": ctx.pack.gaps})


# --------------------------------------------------------------------------- 5/7. proposta e revisao


def _sanitize_proposal(ctx: RunContext, cid: str, out: ProposalOutput, version: int, revised: bool, call_ids: list[str]) -> Proposal:
    assert ctx.pack is not None
    known = ctx.pack.ids()
    invalid = sorted({e for e in out.evidence_ids if e not in known} | {e for m in out.metrics.values() for e in m.evidence_ids if e not in known})
    data = out.model_dump()
    data["evidence_ids"] = [e for e in out.evidence_ids if e in known]
    for m in data["metrics"].values():
        m["evidence_ids"] = [e for e in m["evidence_ids"] if e in known]
    return Proposal(**data, candidate_id=cid, version=version, invalid_evidence_ids=invalid, revised_from_critique=revised, call_ids=call_ids)


async def _propose_one(ctx: RunContext, cid: str, critique: Critique | None, feedback: dict[str, Any] | None = None) -> None:
    """Proposta inicial, revisao apos critica ou revisao com feedback do cliente (rodada de melhoria)."""
    assert ctx.pack is not None
    cand = ctx.candidate(cid)
    previous = ctx.proposals.get(cid)
    version = (previous.version + 1) if previous else 1
    revising = critique is not None or feedback is not None
    stage = "revise" if revising else "propose"
    task_results = [r.model_dump(mode="json") for r in ctx.task_results.get(cid, [])]
    critique_json = critique.model_dump(mode="json") if critique else None
    meta = {**_base_meta(ctx, cid), "task_results": task_results, "version": version,
            "critique": critique_json, "human_feedback": feedback, "previous": previous.model_dump(mode="json") if previous else None}
    try:
        out, call_ids = await ctx.call(
            role="thinker", stage=stage, candidate_id=cid, provider=str(cand.provider), option=cand.model_option,
            system=P.THINKER_SYSTEM,
            user=P.propose_user(ctx.snapshot.model_dump(mode="json"), cand.model_dump(mode="json"), ctx.pack.model_dump(mode="json"), task_results,
                                critique_json, previous.model_dump(mode="json") if previous else None, feedback=feedback),
            schema=ProposalOutput, max_output_tokens=cand.max_output_tokens, metadata=meta, protected=not revising or feedback is not None,
        )
    except (CallDenied, CallFailed) as exc:
        reason = getattr(exc, "reason", str(exc))
        if not revising:
            ctx.partial_reasons.append(f"{cand.name}: proposta nao produzida ({reason})")
            await ctx.emit("proposal.failed", {"candidate_id": cid, "version": version, "reason": reason})
        else:
            ctx.operational_changes.append(f"{cand.name}: revisao nao realizada ({reason}); mantida a versao {previous.version if previous else 1}")
        return
    proposal = _sanitize_proposal(ctx, cid, out, version, revised=critique is not None, call_ids=call_ids)
    proposal.revised_from_feedback = feedback is not None
    ctx.proposals[cid] = proposal
    await ctx.save_artifact("proposal", proposal, candidate_id=cid, version=version)
    await ctx.emit("proposal.ready", {"candidate_id": cid, "version": version, "title": proposal.title, "invalid_evidence_ids": proposal.invalid_evidence_ids,
                                      "from_feedback": feedback is not None})


async def phase_propose(ctx: RunContext) -> None:
    if ctx.halted or ctx.pack is None:
        return
    await asyncio.gather(*(_propose_one(ctx, c.candidate_id, None) for c in ctx.candidates if c.candidate_id))
    if len(ctx.proposals) < len(ctx.candidates):
        ctx.partial_reasons.append(f"apenas {len(ctx.proposals)} de {len(ctx.candidates)} propostas produzidas")


# --------------------------------------------------------------------------- 6. critica cruzada (anel deterministico)


async def _round_affordable(ctx: RunContext, cids: list[str]) -> bool:
    n = len(cids)
    free_calls = ctx.snapshot.budget.max_total_calls - ctx._call_counter - len(ctx.judges)
    if free_calls < 2 * n:
        return False
    if ctx.snapshot.budget.total_cap is None or not ctx.ledger.strict:
        return True
    snap = await ctx.budget_snapshot()
    by_key = {b["bucket_key"]: b for b in snap["buckets"]}
    for cid in cids:
        cand = ctx.candidate(cid)
        b = by_key[candidate_bucket(cid)]
        cap = Decimal(b["cap"]) if b["cap"] is not None else None
        if cap is None:
            continue
        committed = Decimal(b["spent"]) + Decimal(b["reserved"]) + Decimal(b["pending_unknown"]) + Decimal(b["provisioned"])
        try:
            # Rodada = uma critica (modelo da critica) + uma revisao (modelo principal). uto (preco desconhecido)
            # usa o teto dos modelos NeuraLake, como nas chamadas; antes a rodada era sempre desabilitada.
            crit = ctx.ledger.plan(str(cand.provider), critique_model(cand)[1], 12000, cand.max_output_tokens, NEURALAKE_OPTIONS).amount_nano
            est = ctx.ledger.plan(str(cand.provider), cand.model_option, 12000, cand.max_output_tokens, NEURALAKE_OPTIONS).amount_nano
        except Exception:  # noqa: BLE001
            return False
        if committed + (from_nano(est) or Decimal("0")) + (from_nano(crit) or Decimal("0")) > cap:
            return False
    return True


async def phase_critique(ctx: RunContext) -> None:
    if ctx.halted or ctx.pack is None or ctx.snapshot.critique_rounds == 0:
        return
    cids = sorted(ctx.proposals)
    if len(cids) < 2:
        ctx.operational_changes.append("rodada de critica desabilitada: menos de duas propostas")
        return
    if not await _round_affordable(ctx, cids):
        ctx.operational_changes.append("rodada de critica/revisao desabilitada para todos os candidatos por falta de saldo/chamadas (politica comum)")
        return
    ring = [(cids[i], cids[(i + 1) % len(cids)]) for i in range(len(cids))]
    await ctx.emit("critique.order", {"ring": [{"author": a, "target": t} for a, t in ring]})

    async def one(author: str, target: str) -> None:
        assert ctx.pack is not None
        cand = ctx.candidate(author)
        tp = ctx.proposals[target]
        anon = tp.model_dump(mode="json", exclude={"candidate_id", "call_ids", "invalid_evidence_ids", "revised_from_critique"})
        try:
            out, call_ids = await ctx.call(
                role="critic", stage="critique", candidate_id=author, provider=str(cand.provider), option=critique_model(cand)[1],
                system=P.CRITIC_SYSTEM, user=P.critique_user(ctx.snapshot.model_dump(mode="json"), ctx.pack.model_dump(mode="json"), anon),
                schema=CritiqueOutput, max_output_tokens=min(cand.max_output_tokens, 1500),
                metadata={**_base_meta(ctx, author), "target_proposal": anon},
            )
        except (CallDenied, CallFailed) as exc:
            ctx.operational_changes.append(f"{cand.name}: critica nao emitida ({getattr(exc, 'reason', exc)})")
            return
        known = ctx.pack.ids()
        objections = [o.model_copy(update={"evidence_ids": [e for e in o.evidence_ids if e in known]}) for o in out.objections]
        valid_constraints = {c.constraint_id for c in ctx.snapshot.constraints}
        objections = [o.model_copy(update={"constraint_id": o.constraint_id if o.constraint_id in valid_constraints else None}) for o in objections]
        critique = Critique(objections=objections, strengths=out.strengths, author_candidate_id=author, target_candidate_id=target, target_version=tp.version, call_ids=call_ids)
        ctx.critiques.append(critique)
        await ctx.save_artifact("critique", critique, candidate_id=author)
        await ctx.emit("critique.ready", {"author_candidate_id": author, "target_candidate_id": target, "target_version": tp.version, "objections": len(objections)})

    await asyncio.gather(*(one(a, t) for a, t in ring))


async def phase_revise(ctx: RunContext) -> None:
    if ctx.halted or ctx.snapshot.critique_rounds == 0 or not ctx.critiques:
        return
    by_target = {c.target_candidate_id: c for c in ctx.critiques}
    await asyncio.gather(*(_propose_one(ctx, cid, crit) for cid, crit in sorted(by_target.items())))


# --------------------------------------------------------------------------- 8. verificacoes objetivas (codigo)


async def phase_verify(ctx: RunContext) -> None:
    if ctx.pack is None:
        return
    for cid, proposal in sorted(ctx.proposals.items()):
        v = verify_proposal(proposal, ctx.snapshot.constraints, ctx.pack)
        ctx.verifications[cid] = v
        await ctx.save_artifact("verification", v, candidate_id=cid, version=proposal.version)
        await ctx.emit("verification.ready", {"candidate_id": cid, "proposal_version": proposal.version, "eligibility": str(v.eligibility), "reasons": v.reasons})


# --------------------------------------------------------------------------- 9. Judge


async def phase_judge(ctx: RunContext) -> None:
    if ctx.pack is None or not ctx.proposals:
        ctx.judge_error = "sem propostas para avaliar"
        return
    if ctx.halt in ("cancelled", "failed"):
        ctx.judge_error = f"Judge nao executado ({ctx.halt_reason})"
        return
    judges = ctx.judges
    proposals = sorted(ctx.proposals.values(), key=lambda p: p.candidate_id)
    ctx.judge_shuffle_seed = (ctx.seed * 7919 + 17) % (2**31)
    anon, anon_ver, label_map = anonymize(proposals, ctx.verifications, ctx.judge_shuffle_seed, names={c.candidate_id or "": c.name for c in ctx.candidates})
    by_cid = {p.candidate_id: p for p in proposals}
    many = len(judges) > 1
    errors: list[str] = []

    async def one(j: JudgeConfig) -> None:
        assert ctx.pack is not None and j.rubric is not None
        jid, rubric = j.judge_id or "j1", j.rubric
        criteria = judge_criteria(rubric)
        rubric_hash = ctx.hashes.get(f"rubric:{jid}", ctx.hashes["rubric"])
        who = f"Juiz {j.name}" if many else "Judge"

        def validator(out: Any) -> None:
            parse_judge_output(out.model_dump(mode="json"), rubric, label_map, by_cid, rubric_hash, ctx.pack.version, [])  # type: ignore[union-attr]

        try:
            out, call_ids = await ctx.call(
                role="judge", stage="judge", candidate_id=None, provider=str(j.provider), option=j.model_option or "",
                system=P.JUDGE_SYSTEM,
                user=P.judge_user(ctx.snapshot.model_dump(mode="json"), ctx.pack.model_dump(mode="json"), criteria, anon, anon_ver, persona={"name": j.name, "instructions": j.instructions}),
                schema=JudgeOutput, max_output_tokens=j.max_output_tokens, protected=True,
                metadata={**_base_meta(ctx, None), "judge_id": jid, "judge_name": j.name, "persona": j.persona, "criteria": [c["criterion_id"] for c in criteria],
                          "criteria_names": {c["criterion_id"]: c["name"] for c in criteria},
                          "proposals": anon, "verifications": anon_ver, "labels": list(label_map)},
                validator=validator,
            )
            evaluations = parse_judge_output(out.model_dump(mode="json"), rubric, label_map, by_cid, rubric_hash, ctx.pack.version, call_ids, judge_id=jid, judge_name=j.name)
        except (CallDenied, CallFailed) as exc:
            errors.append(f"{who} falhou: {getattr(exc, 'reason', exc)}")
            await ctx.emit("evaluation.failed", {"reason": errors[-1], "judge_id": jid})
            return
        except (JudgeOutputError, ValueError) as exc:
            errors.append(f"saida do {who} invalida: {exc}")
            await ctx.emit("evaluation.failed", {"reason": errors[-1], "judge_id": jid})
            return
        ctx.evaluations[jid] = {ev.candidate_id: ev for ev in evaluations}
        for ev in evaluations:
            await ctx.save_artifact("evaluation", ev, candidate_id=f"{ev.candidate_id}:{jid}" if many else ev.candidate_id, version=ev.proposal_version)

    await asyncio.gather(*(one(j) for j in judges))
    ctx.partial_reasons.extend(errors)
    if not ctx.evaluations:
        ctx.judge_error = "; ".join(errors) or "sem avaliacao"
        return
    evaluated = sorted({cid for evs in ctx.evaluations.values() for cid in evs})
    await ctx.emit("evaluation.ready", {"candidates": evaluated, "judges": [j.judge_id for j in judges if j.judge_id in ctx.evaluations], "shuffle_seed": ctx.judge_shuffle_seed, "labels": label_map})


# --------------------------------------------------------------------------- 10. ranking + relatorio


def _intended_status(ctx: RunContext) -> RunStatus:
    if ctx.halt == "cancelled":
        return RunStatus.CANCELLED
    if ctx.halt == "failed":
        return RunStatus.FAILED
    # No plano de acao nao ha disputa: equipes que sairam em repescagens anteriores nao contam como propostas faltando.
    missing_proposals = ctx.snapshot.action_plan is None and len(ctx.proposals) < len(ctx.candidates)
    if ctx.halt == "limit" or ctx.partial_reasons or ctx.judge_error or missing_proposals:
        return RunStatus.PARTIAL
    return RunStatus.COMPLETED


async def cost_breakdown(ctx: RunContext, costs: dict[str, Any]) -> CostBreakdown:
    """Consumo DESTA execucao (rodadas derivadas reportam so o proprio gasto)."""
    buckets = costs["buckets"]
    common = buckets.get("common")
    per_candidate = {
        c.candidate_id or "": (from_nano(buckets[candidate_bucket(c.candidate_id or "")].spent_nano) or Decimal("0"))
        if candidate_bucket(c.candidate_id or "") in buckets else Decimal("0")
        for c in ctx.candidates
    }
    common_spent = (from_nano(common.spent_nano) if common else None) or Decimal("0")
    secondary_calls, secondary_savings = await ctx.secondary_usage()
    return CostBreakdown(
        currency=ctx.snapshot.budget.currency, common=common_spent, judge=costs["judge"], per_candidate=per_candidate,
        total=common_spent + sum(per_candidate.values(), Decimal("0")), pending_unknown_reserved=costs["pending_unknown"], quality=costs["quality"],
        calls_used=costs["calls_used"], calls_cap=ctx.snapshot.budget.max_total_calls, cap=ctx.snapshot.budget.total_cap, strict=ctx.snapshot.budget.strict,
        secondary_calls=secondary_calls, secondary_savings=secondary_savings,
    )


async def phase_rank_report(ctx: RunContext) -> Report:
    costs = await ctx.costs()
    buckets = costs["buckets"]
    inputs: list[CandidateInput] = []
    for c in ctx.candidates:
        cid = c.candidate_id or ""
        b = buckets.get(candidate_bucket(cid))
        spent = from_nano(b.spent_nano) if b else None
        quota = from_nano(b.cap_nano) if b and b.cap_nano is not None else None
        quality = costs["bucket_quality"].get(candidate_bucket(cid), CostQuality.UNKNOWN)
        if b and b.pending_unknown_nano > 0:
            quality = CostQuality.UNKNOWN
        if cid in ctx.inherited_costs:
            # Rodada de melhoria: eficiencia sobre o consumo acumulado (rodadas anteriores + esta), nao so o desta rodada.
            prev_spent, prev_quota = ctx.inherited_costs[cid]
            spent = None if spent is None else spent + prev_spent
            quota = None if quota is None or prev_quota is None else quota + prev_quota
        p = ctx.proposals.get(cid)
        evals = {jid: evs[cid] for jid, evs in ctx.evaluations.items() if cid in evs}
        inputs.append(CandidateInput(cid, c.name, p.version if p else None, ctx.verifications.get(cid), evals or None, spent, quota, quality))
    panel = [PanelJudge(j.judge_id or "j1", j.name, Decimal(j.weight), j.rubric or ctx.snapshot.rubric) for j in ctx.judges]
    ranking = compute_ranking(panel, inputs)
    if not ctx.evaluations:
        ranking.decision_status = DecisionStatus.NOT_EVALUATED
        ranking.winner_candidate_id = None
        ranking.reasons = [ctx.judge_error or "sem avaliacao"] + ranking.reasons
    cost = await cost_breakdown(ctx, costs)
    status = _intended_status(ctx)
    limitations = list(ctx.limitations)
    if ctx.simulated:
        limitations.append("Execucao SIMULADA: conteudo, modelos e custos sao ficticios e nao comprovam a integracao real de inferencia.")
    if ctx.halt_reason:
        limitations.append(f"execucao encerrada antecipadamente: {ctx.halt_reason}")
    limitations += ctx.partial_reasons
    if costs["pending_unknown"] > 0:
        limitations.append(f"reservas pendentes com consumo desconhecido: {costs['pending_unknown']} {ctx.snapshot.budget.currency}")
    next_steps = ["Revisar as evidencias citadas e as lacunas antes de decidir."]
    if ranking.decision_status in (DecisionStatus.INCONCLUSIVE, DecisionStatus.NO_ELIGIBLE_CANDIDATE, DecisionStatus.NOT_EVALUATED):
        next_steps.append("Considerar nova execucao com evidencias adicionais ou restricoes ajustadas (novo orcamento).")
    report = Report(
        run_id=ctx.run_id, title=ctx.snapshot.title, status=status, decision_status=ranking.decision_status, simulated=ctx.simulated,
        generated_at=datetime.now(UTC), winner_candidate_id=ranking.winner_candidate_id, co_leaders=ranking.co_leaders,
        decision_reasons=ranking.reasons, ranking=ranking.entries, proposals=sorted(ctx.proposals.values(), key=lambda p: p.candidate_id),
        critiques=sorted(ctx.critiques, key=lambda c: c.author_candidate_id), verifications=sorted(ctx.verifications.values(), key=lambda v: v.candidate_id),
        evaluations=[ctx.evaluations[jid][cid] for cid in sorted({c for evs in ctx.evaluations.values() for c in evs})
                     for jid in (j.judge_id for j in ctx.judges) if jid in ctx.evaluations and cid in ctx.evaluations[jid]],
        evidence_pack_version=ctx.pack.version if ctx.pack else None, evidence_gaps=list(ctx.pack.gaps) if ctx.pack else [],
        limitations=limitations, operational_changes=list(ctx.operational_changes), cost=cost, next_steps=next_steps, judge_shuffle_seed=ctx.judge_shuffle_seed,
        diversity_observed={k: sorted(v) for k, v in ctx.reported_models.items()},
    )
    await ctx.save_artifact("report", report)
    await ctx.emit("report.ready", {"decision_status": str(report.decision_status), "winner_candidate_id": report.winner_candidate_id, "co_leaders": report.co_leaders})
    return report


async def phase_finalize(ctx: RunContext, report: Report | None) -> RunStatus:
    async with ctx.db.session() as s, s.begin():
        await ctx.ledger.release_provisions(s, ctx.run_id)
    status = _intended_status(ctx)
    decision = str(report.decision_status) if report else str(DecisionStatus.NOT_EVALUATED)
    error = ctx.halt_reason if ctx.halt in ("failed", "limit") else None
    async with ctx.db.session() as s, s.begin():
        final = await finish_run(s, ctx.run_id, status, decision, error)
    if final is None:
        # Job ja estava em estado terminal (ex.: interrompido/cancelado externamente): nao reabrir nem sobrescrever.
        await ctx.emit("run.late_result", {"note": "resultado tardio registrado; status terminal preservado"})
        return status
    if report is not None and final != report.status:
        report.status = final
        await ctx.save_artifact("report", report)
    await ctx.emit_budget()
    if final == RunStatus.CANCELLED:
        await ctx.emit("run.cancelled", {"status": str(final), "decision_status": decision})
    elif final == RunStatus.FAILED:
        await ctx.emit("run.failed", {"status": str(final), "error": error, "decision_status": decision})
    else:
        await ctx.emit("run.finished", {"status": str(final), "decision_status": decision, "partial_reasons": ctx.partial_reasons})
    return final
