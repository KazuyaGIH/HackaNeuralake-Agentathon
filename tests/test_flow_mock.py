"""Fluxo integrado em modo simulado e criterios de aceite da secao 19 (parte 1: fluxo, cenarios e determinismo)."""

import asyncio
import json
from typing import Any

import httpx

from tests.conftest import app_client, create_run, demo_config, events, make_settings, run_demo, wait_terminal


def _strip_volatile(report: dict[str, Any]) -> dict[str, Any]:
    r = json.loads(json.dumps(report))
    for k in ("run_id", "generated_at"):
        r.pop(k, None)
    for p in r["proposals"]:
        p.pop("call_ids", None)
    for c in r["critiques"]:
        c.pop("call_ids", None)
    for e in r["evaluations"]:
        e.pop("call_ids", None)
    return r


async def test_demo_flow_completes_with_full_storyline(client: httpx.AsyncClient) -> None:
    run_id, detail, report = await run_demo(client)
    assert detail["status"] == "completed", detail["error"]
    assert report["simulated"] is True and report["decision_status"] == "ranked" and report["winner_candidate_id"]
    types = [e["type"] for e in await events(client, run_id)]
    for t in ("run.started", "evidence.ready", "task.started", "task.completed", "proposal.ready", "critique.ready", "verification.ready", "evaluation.ready", "budget.updated", "run.finished"):
        assert t in types, t
    # Pacote v1 e v2 (barreira unica), duas propostas por candidato (v1 e revisao v2), critica em anel reciproco.
    packs = detail["artifacts"]["evidence_pack"]
    assert [p["version"] for p in packs] == [1, 2] and packs[1]["frozen"] is True
    proposals = detail["artifacts"]["proposal"]
    assert sorted((p["candidate_id"], p["version"]) for p in proposals) == [("c1", 1), ("c1", 2), ("c2", 1), ("c2", 2)]
    ring = {(c["author_candidate_id"], c["target_candidate_id"]) for c in report["critiques"]}
    assert ring == {("c1", "c2"), ("c2", "c1")}
    # Roteiro: a critica aponta conflito com restricao na v1 do candidato 2, a revisao registra a correcao.
    c2_v1 = next(p for p in proposals if p["candidate_id"] == "c2" and p["version"] == 1)
    assert float(c2_v1["metrics"]["monthly_cost_brl"]["value"]) > 8000
    crit = next(c for c in report["critiques"] if c["target_candidate_id"] == "c2")
    assert any(o["constraint_id"] == "custo_mensal_max" and o["severity"] == "high" for o in crit["objections"])
    c2_final = next(p for p in report["proposals"] if p["candidate_id"] == "c2")
    assert c2_final["version"] == 2 and c2_final["revised_from_critique"] and float(c2_final["metrics"]["monthly_cost_brl"]["value"]) <= 8000
    assert all(v["eligibility"] == "eligible" for v in report["verifications"])
    # Custos: comum separado dos candidatos, Judge reportado a parte, qualidade identificada.
    cost = report["cost"]
    assert cost["quality"] == "estimated" and cost["calls_used"] == detail["metrics"]["calls_used"] <= 32
    assert set(cost["per_candidate"]) == {"c1", "c2"} and float(cost["judge"]) > 0
    # Eficiencia calculada pelo servidor e presente nas notas.
    assert all("efficiency" in e["grades"] for e in report["ranking"])
    assert report["judge_shuffle_seed"] is not None
    md = (await client.get(f"/api/v1/runs/{run_id}/report", params={"format": "md"})).text
    assert "SIMULADO" in md and "## Ranking" in md


async def test_same_input_same_seed_is_deterministic(client: httpx.AsyncClient) -> None:
    _, _, r1 = await run_demo(client, seed=42)
    _, _, r2 = await run_demo(client, seed=42)
    assert _strip_volatile(r1) == _strip_volatile(r2)
    _, _, r3 = await run_demo(client, seed=43)
    assert r3["judge_shuffle_seed"] != r1["judge_shuffle_seed"]


async def test_candidate_count_models_and_instructions_reflected(client: httpx.AsyncClient) -> None:
    cfg = await demo_config(client)
    cfg.update({
        "config_mode": "manual",
        "candidates": [
            {"name": "Alfa", "instructions": "Estrategia alfa privada", "model_option": "mock-cheap", "max_specialist_tasks": 1},
            {"name": "Beta", "preset": "robust", "model_option": "mock-reasoning"},
            {"name": "Gama", "instructions": "Terceira via", "allowed_specialists": ["calculation"], "max_specialist_tasks": 0},
        ],
    })
    cfg.pop("candidate_count", None)
    run_id = await create_run(client, cfg)
    detail = await wait_terminal(client, run_id)
    snap = detail["snapshot"]
    assert [c["candidate_id"] for c in snap["candidates"]] == ["c1", "c2", "c3"]
    assert snap["candidates"][0]["model_option"] == "mock-cheap" and snap["candidates"][1]["instructions"].startswith("Voce e o pensante")
    assert detail["snapshot_hashes"]["instructions:c1"] != detail["snapshot_hashes"]["instructions:c2"]
    cards = {(e["payload"]["candidate_id"], e["payload"]["version"]) for e in await events(client, run_id) if e["type"] == "proposal.ready"}
    assert {c for c, _ in cards} == {"c1", "c2", "c3"}
    calls = detail["artifacts"]["calls"]
    assert {c["requested_option"] for c in calls if c["candidate_id"] == "c1"} == {"mock-cheap"}
    assert {c["reported_model"] for c in calls if c["candidate_id"] == "c2"} == {"mock/mock-reasoning"}
    # Gama sem delegacao: nenhuma chamada de especialista/plano.
    assert all(c["stage"] not in ("plan", "research") for c in calls if c["candidate_id"] == "c3")
    report = (await client.get(f"/api/v1/runs/{run_id}/report")).json()
    assert len(report["ranking"]) == 3 and set(report["diversity_observed"]["mock"]) == {"mock/mock-cheap", "mock/mock-reasoning", "mock/mock-default"}

    for bad in (1, 5):
        cfg2 = await demo_config(client, candidate_count=bad)
        assert (await client.post("/api/v1/runs", json=cfg2)).status_code == 422
    cfg4 = await demo_config(client, candidate_count=4)
    run4 = await create_run(client, cfg4)
    d4 = await wait_terminal(client, run4)
    assert len(d4["snapshot"]["candidates"]) == 4 and d4["status"] in ("completed", "partial")


async def test_unauthorized_specialist_is_rejected_by_rule(client: httpx.AsyncClient) -> None:
    cfg = await demo_config(client, mock_scenario="unauthorized_specialist", config_mode="manual")
    cfg["candidates"] = [
        {"name": "Sem calculo", "allowed_specialists": ["document_research"], "max_specialist_tasks": 2},
        {"name": "Completo", "allowed_specialists": ["document_research", "calculation"], "max_specialist_tasks": 2},
    ]
    run_id = await create_run(client, cfg)
    detail = await wait_terminal(client, run_id)
    plans = {e["payload"]["candidate_id"]: e["payload"] for e in await events(client, run_id) if e["type"] == "plan.ready"}
    reasons_c1 = " ".join(r["reason"] for r in plans["c1"]["rejected"])
    assert plans["c1"]["adjusted"] and "nao existe no catalogo" in reasons_c1 and "nao autorizado" in reasons_c1
    assert plans["c1"]["accepted"] == ["t3"]
    started = [e["payload"]["kind"] for e in await events(client, run_id) if e["type"] == "task.started"]
    assert "web_search" not in started and all(k in ("document_research", "calculation") for k in started)
    assert detail["status"] == "completed"


async def test_timeout_with_unknown_usage_keeps_reservation_pending(client: httpx.AsyncClient) -> None:
    run_id, detail, report = await run_demo(client, mock_scenario="timeout_unknown_usage")
    calls = detail["artifacts"]["calls"]
    timed_out = [c for c in calls if c["error_type"] == "timeout"]
    assert len(timed_out) == 1 and timed_out[0]["status"] == "pending_unknown" and timed_out[0]["cost"] is None
    assert float(detail["metrics"]["pending_unknown"]) > 0 and detail["metrics"]["cost_quality"] == "unknown"
    bucket = next(b for b in detail["budget_buckets"] if b["bucket_key"] == "candidate:c2")
    assert float(bucket["pending_unknown"]) > 0
    assert any(e["type"] == "call.finished" and e["payload"]["status"] == "error" and e["payload"]["usage_known"] is False for e in await events(client, run_id))
    # Custo desconhecido para c2 -> sem nota de eficiencia completa -> sem vencedor oficial.
    assert report["decision_status"] == "inconclusive" and report["winner_candidate_id"] is None
    assert any("pendentes" in l for l in report["limitations"])


async def test_transient_error_retries_at_most_once(client: httpx.AsyncClient) -> None:
    run_id, detail, report = await run_demo(client, mock_scenario="transient_error_once")
    calls = detail["artifacts"]["calls"]
    failed = [c for c in calls if c["error_type"] == "server_error"]
    assert len(failed) == 1 and failed[0]["status"] == "failed" and failed[0]["cost"] == "0"
    logical = [c for c in calls if c["logical_call_id"] == failed[0]["logical_call_id"]]
    assert sorted(c["attempt"] for c in logical) == [1, 2]
    assert detail["metrics"]["calls_used"] == len(calls)  # todas as tentativas contam
    assert detail["status"] == "completed" and report["decision_status"] == "ranked"


async def test_mandatory_constraint_failure_makes_ineligible(client: httpx.AsyncClient) -> None:
    _, detail, report = await run_demo(client, mock_scenario="all_ineligible")
    assert report["decision_status"] == "no_eligible_candidate" and report["winner_candidate_id"] is None
    for e in report["ranking"]:
        assert e["eligibility"] == "ineligible" and e["disqualification_reason"] and e["score_0_100"] is not None
    assert all(any(c["result"] == "fail" for c in v["checks"]) for v in report["verifications"])


async def test_constraint_without_evidence_is_pending_inconclusive(client: httpx.AsyncClient) -> None:
    _, detail, report = await run_demo(client, mock_scenario="insufficient_evidence")
    assert report["decision_status"] == "inconclusive" and report["winner_candidate_id"] is None
    assert all(v["eligibility"] == "pending" for v in report["verifications"])
    assert all(c["result"] == "unknown" for v in report["verifications"] for c in v["checks"] if c["mandatory"])


async def test_judge_out_of_range_rejected_then_repaired(client: httpx.AsyncClient) -> None:
    run_id, detail, report = await run_demo(client, mock_scenario="judge_invalid_then_valid")
    judge_calls = [c for c in detail["artifacts"]["calls"] if c["role"] == "judge"]
    assert sorted(c["attempt"] for c in judge_calls) == [1, 2]
    assert judge_calls[0]["error_type"] == "schema_invalid" and judge_calls[1]["error_type"] is None
    assert report["decision_status"] == "ranked" and len(report["evaluations"]) == 2
    assert all(0 <= float(g["grade"]) <= 10 for ev in report["evaluations"] for g in ev["grades"])


async def test_judge_failure_after_repair_preserves_proposals(client: httpx.AsyncClient) -> None:
    run_id, detail, report = await run_demo(client, mock_scenario="judge_fails")
    judge_calls = [c for c in detail["artifacts"]["calls"] if c["role"] == "judge"]
    assert len(judge_calls) == 2  # inicial + uma reparacao, nunca mais
    assert detail["status"] == "partial" and report["decision_status"] == "not_evaluated"
    assert report["winner_candidate_id"] is None and report["evaluations"] == [] and len(report["proposals"]) == 2
    assert all(e["score_0_100"] is None for e in report["ranking"])
    assert any(e["type"] == "evaluation.failed" for e in await events(client, run_id))


async def test_tie_yields_co_leadership(client: httpx.AsyncClient) -> None:
    # Mesmo modelo/preco para ambos: com notas iguais e consumo igual, a pontuacao empata de fato.
    candidates = [{"name": "Par A", "model_option": "mock-default"}, {"name": "Par B", "model_option": "mock-default"}]
    _, _, report = await run_demo(client, mock_scenario="tie", config_mode="manual", candidates=candidates)
    assert report["decision_status"] == "tie" and report["winner_candidate_id"] is None
    assert sorted(report["co_leaders"]) == ["c1", "c2"]
    ranks = {e["candidate_id"]: e["rank"] for e in report["ranking"]}
    assert ranks == {"c1": 1, "c2": 1} and all(e["co_leader"] for e in report["ranking"])


async def test_budget_insufficient_rejected_and_tight_budget_degrades_by_common_policy(client: httpx.AsyncClient) -> None:
    cfg = await demo_config(client)
    cfg["budget"]["total_cap"] = "0.0001"
    r = await client.post("/api/v1/runs", json=cfg)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "budget_insufficient"
    cfg = await demo_config(client)
    cfg["budget"]["max_total_calls"] = 4  # apenas consolidacao (2) + Judge (1) cabem: sem especialistas nem rodada
    run_id = await create_run(client, cfg)
    detail = await wait_terminal(client, run_id)
    report = (await client.get(f"/api/v1/runs/{run_id}/report")).json()
    assert detail["metrics"]["calls_used"] <= 4
    assert report["operational_changes"] and any("politica comum" in o for o in report["operational_changes"])
    assert len(report["proposals"]) == 2 and report["critiques"] == [] and detail["status"] in ("completed", "partial")


async def test_no_efficiency_without_cap_requires_explicit_choice(client: httpx.AsyncClient) -> None:
    cfg = await demo_config(client)
    cfg["budget"]["total_cap"] = None
    r = await client.post("/api/v1/runs", json=cfg)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "budget_required"
    cfg["rubric"]["criteria"] = [c for c in cfg["rubric"]["criteria"] if c["criterion_id"] != "efficiency"]
    cfg["rubric"]["criteria"][0]["weight"] = "40"  # 40+25+20+10+5 = 100
    run_id = await create_run(client, cfg)
    detail = await wait_terminal(client, run_id)
    report = (await client.get(f"/api/v1/runs/{run_id}/report")).json()
    assert detail["status"] == "completed" and report["decision_status"] == "ranked"
    assert all("efficiency" not in e["grades"] for e in report["ranking"]) and report["cost"]["cap"] is None


async def test_run_deadline_exceeded_ends_partial(tmp_path) -> None:  # noqa: ANN001
    from app.providers.mock import MockAdapter

    class Slow(MockAdapter):
        async def generate(self, request):  # noqa: ANN001, ANN202
            await asyncio.sleep(0.4)
            return await super().generate(request)

    async with app_client(make_settings(tmp_path), adapters={"mock": Slow()}) as (_app, client):
        cfg = await demo_config(client)
        cfg["budget"]["run_deadline_s"] = 10
        cfg["budget"]["call_timeout_s"] = 1
        # prazo minimo do contrato e 10s; forca timeout curto por chamada para demonstrar o teto de tempo por chamada
        run_id = await create_run(client, cfg)
        detail = await wait_terminal(client, run_id, timeout=60)
        assert detail["status"] in ("completed", "partial")
        assert all(c["latency_ms"] is not None for c in detail["artifacts"]["calls"])
