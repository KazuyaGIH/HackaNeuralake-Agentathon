"""Grafo LangGraph do fluxo. Estados/transicoes sao persistidos explicitamente pelas fases (sem checkpointer)."""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.contracts.artifacts import Report
from app.orchestration import phases
from app.orchestration.coordinator import RunContext


class ArenaState(TypedDict, total=False):
    ctx: RunContext
    report: Report | None
    final_status: str | None


PhaseFn = Callable[[RunContext], Awaitable[Any]]

ORDER = ["evidence", "plan", "delegate", "sync", "propose", "critique", "revise", "verify", "judge", "rank_report", "finalize"]
PHASES: dict[str, PhaseFn] = {
    "evidence": phases.phase_evidence,
    "plan": phases.phase_plan,
    "delegate": phases.phase_delegate,
    "sync": phases.phase_sync,
    "propose": phases.phase_propose,
    "critique": phases.phase_critique,
    "revise": phases.phase_revise,
    "verify": phases.phase_verify,
    "judge": phases.phase_judge,
}


def _node(name: str, fn: PhaseFn) -> Callable[[ArenaState], Awaitable[dict[str, Any]]]:
    async def run(state: ArenaState) -> dict[str, Any]:
        ctx = state["ctx"]
        if ctx.halt not in ("cancelled", "failed"):
            await ctx.check_cancel()
        try:
            await fn(ctx)
        except Exception as exc:  # noqa: BLE001 - falha inesperada: preserva artefatos e encerra honestamente
            ctx.set_halt("failed", f"{name}: {type(exc).__name__}: {exc}")
        return {}

    run.__name__ = f"node_{name}"
    return run


async def _rank_report(state: ArenaState) -> dict[str, Any]:
    ctx = state["ctx"]
    try:
        report = await phases.phase_rank_report(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.set_halt("failed", f"rank_report: {type(exc).__name__}: {exc}")
        report = None
    return {"report": report}


async def _finalize(state: ArenaState) -> dict[str, Any]:
    final = await phases.phase_finalize(state["ctx"], state.get("report"))
    return {"final_status": str(final)}


def _router(next_name: str) -> Callable[[ArenaState], str]:
    def route(state: ArenaState) -> str:
        ctx = state["ctx"]
        if ctx.halt in ("cancelled", "failed") and next_name not in ("verify", "judge", "rank_report", "finalize"):
            return "verify"
        return next_name

    return route


def build_graph():  # noqa: ANN201 - tipo do grafo compilado e interno ao LangGraph
    g: StateGraph = StateGraph(ArenaState)
    for name, fn in PHASES.items():
        g.add_node(name, _node(name, fn))
    g.add_node("rank_report", _rank_report)
    g.add_node("finalize", _finalize)
    g.add_edge(START, "evidence")
    for i, name in enumerate(ORDER[:-1]):
        nxt = ORDER[i + 1]
        if name in ("verify", "judge", "rank_report"):
            g.add_edge(name, nxt)
        else:
            g.add_conditional_edges(name, _router(nxt), {nxt: nxt, "verify": "verify"})
    g.add_edge("finalize", END)
    return g.compile()


async def run_arena(ctx: RunContext) -> str:
    graph = build_graph()
    result = await graph.ainvoke({"ctx": ctx, "report": None, "final_status": None})
    return result.get("final_status") or "failed"
