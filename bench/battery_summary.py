r"""Resumo da bateria de reteste (03/10/2026): sem avaliador por IA; aprovacao so por verificacoes em codigo + gabarito.

    .venv\Scripts\python.exe bench\battery_summary.py [fase=battery]   -> bench\out\battery_summary.md + battery_rows.json

Aprovacao (definida antes de executar): opcao correta (gabarito) E todas as metricas exigidas corretas (tolerancia 0,5%)
E zero referencias inexistentes E todas as restricoes numericas obrigatorias cumpridas pelas metricas declaradas.
Configuracoes: B do harness = "A generalista" do reteste (agente unico + 1 autorrevisao); C = arena completa.
"""

import json
import sqlite3
import statistics as st
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "out"
sys.path.insert(0, str(BENCH))
import harness as H  # noqa: E402,F401
from challenges import BY_ID  # noqa: E402
from evaluate import code_checks  # noqa: E402

LABEL = {"B": "A generalista (agente unico + 1 autorrevisao)", "C": "Arena completa (2 equipes, critica, juiz)"}


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def constraints_ok(ch: dict, d: dict | None) -> bool:
    if not d:
        return False
    metrics = d.get("metrics") or {}
    for c in ch["constraints"]:
        if not c.get("mandatory", True) or c["kind"] not in ("numeric_max", "numeric_min") or not c.get("metric_key"):
            continue
        m = metrics.get(c["metric_key"])
        if m is None:
            return False
        try:
            v, lim = Decimal(str(m["value"])), Decimal(str(c["limit"]))
        except Exception:  # noqa: BLE001
            return False
        if (c["kind"] == "numeric_max" and v > lim) or (c["kind"] == "numeric_min" and v < lim):
            return False
    return True


def calc_counts_single(r: dict) -> tuple[int, int, int]:
    plan = [t for t in (r.get("plan_tasks") or []) if t.get("kind") == "calculation"]
    done = [t for t in (r.get("tasks") or []) if t.get("kind") == "calculation" and t.get("status") == "completed"]
    return len(plan), len(done), sum(1 for t in (r.get("tasks") or []) if t.get("kind") == "calculation")


def calc_counts_arena(run_id: str | None) -> tuple[int, int, int]:
    if not run_id:
        return 0, 0, 0
    db = sqlite3.connect(str(BENCH / "data" / "agentathon.db"))
    req = exe = done = 0
    for kind, payload in db.execute("select kind, payload from artifacts where run_id=? and kind in ('task_plan','task_result')", (run_id,)):
        p = json.loads(payload)
        if kind == "task_plan":
            req += sum(1 for t in p.get("tasks", []) if t.get("kind") == "calculation")
            req += sum(1 for x in p.get("validation", {}).get("rejected", []) if x.get("reason", "").startswith(("calculo", "calculo invalido")))
        elif p.get("kind") == "calculation":
            exe += 1
            done += p.get("status") == "completed"
    db.close()
    return req, done, exe


def main(phase: str) -> None:
    runs = [r for r in jl(OUT / "runs.jsonl") if r["phase"] == phase]
    calls = defaultdict(list)
    for c in jl(OUT / "calls.jsonl"):
        calls[c.get("exec_id")].append(c)
    rows = []
    for r in runs:
        ch = BY_ID[r["challenge"]]
        cs = calls.get(r["exec_id"], [])
        d = r.get("deliverable")
        cc = code_checks(ch, d, r.get("pack"))
        cons = constraints_ok(ch, d)
        approved = bool(cc["opcao_correta"] and cc["metricas_corretas"] and cc["refs_inexistentes"] == 0 and cons)
        req, done, exe = calc_counts_arena(r.get("run_id")) if r["config"] == "C" else calc_counts_single(r)
        drv_metrics = sum(1 for m in ((d or {}).get("metrics") or {}).values() if any(str(e).startswith("drv-") for e in m.get("evidence_ids") or []))
        tin = [c["in_tok"] for c in cs]
        tout = [c["out_tok"] for c in cs]
        unknown = sum(1 for c in cs if c["usage_source"] != "api_usage")
        decision = r.get("decision_status") if r["config"] == "C" else "nao aplicavel"
        if r["config"] == "C" and r.get("error"):
            decision = "erro"
        rows.append({
            "exec_id": r["exec_id"], "config": r["config"], "challenge": r["challenge"], "complexity": r["complexity"], "rep": r["rep"],
            "model": "neuralake:text", "run_id": r.get("run_id"), "ok": r["ok"], "error": r.get("error"), "wall_s": r["wall_s"],
            "attempts": len(cs), "logical": sum(1 for c in cs if c["attempt"] == 1), "repairs": sum(1 for c in cs if c["repair"]),
            "plan_repairs": sum(1 for c in cs if c["stage"] == "plan_repair"), "failed_attempts": sum(1 for c in cs if c["error"]),
            "unknown_usage": unknown, "in": sum(x or 0 for x in tin), "out": sum(x or 0 for x in tout),
            "cost_pub": sum(c["cost_public_usd"] or 0 for c in cs), "cost_prov": sum(c["cost_provider_usd"] or 0 for c in cs),
            "calc_req": req, "calc_exec": exe, "calc_done": done, "metrics_from_calc": drv_metrics,
            "opcao": cc["opcao"], "opcao_correta": cc["opcao_correta"], "metricas": f"{cc['metricas_ok']}/{cc['metricas_total']}",
            "metricas_corretas": cc["metricas_corretas"], "refs_inexistentes": cc["refs_inexistentes"], "restricoes_ok": cons,
            "erros_metricas": cc["erros_metricas"], "entregue": cc["entregue"], "approved": approved, "decision": decision,
        })
        rows[-1]["total"] = rows[-1]["in"] + rows[-1]["out"]
    (OUT / f"{phase}_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    md = [f"# Bateria `{phase}` — avaliacao preliminar ({len(rows)} execucoes)\n"]
    md.append("| Execucao | Config | Desafio | Rep | Run | Chamadas (tent./reparos/falhas/plan_repair) | Uso desconhecido | Tokens in/out/total | Tempo s | Calculos pedidos/executados/concluidos | Metricas via calculo | Opcao | Metricas | Refs inexist. | Restricoes | Entregue | Aprovada | Decisao | Custo tabela US$ | Custo API US$ | Erro |")
    md.append("|" + "---|" * 21)
    for x in rows:
        md.append(f"| {x['exec_id']} | {x['config']} | {x['challenge']} | {x['rep']} | {x['run_id'] or '—'} | {x['attempts']}/{x['repairs']}/{x['failed_attempts']}/{x['plan_repairs']} | {x['unknown_usage']} | "
                  f"{x['in']}/{x['out']}/{x['total']} | {x['wall_s']} | {x['calc_req']}/{x['calc_exec']}/{x['calc_done']} | {x['metrics_from_calc']} | {x['opcao']} ({'ok' if x['opcao_correta'] else 'errada'}) | "
                  f"{x['metricas']} | {x['refs_inexistentes']} | {'ok' if x['restricoes_ok'] else 'nao'} | {x['entregue']} | {'SIM' if x['approved'] else 'nao'} | {x['decision']} | "
                  f"{x['cost_pub']:.4f} | {x['cost_prov']:.5f} | {(x['error'] or '')[:80]} |")
    md.append("\n## Por configuracao\n")
    md.append("| Config | Aprovadas/tentadas | Tokens totais | Media tokens/exec | Tempo medio s | Tempo mediano s | Tokens por aprovada | Custo tabela por aprovada | Custo API por aprovada | Calculos concluidos/pedidos | Uso desconhecido |")
    md.append("|" + "---|" * 11)
    tot = {}
    for cfg in ("B", "C"):
        rs = [x for x in rows if x["config"] == cfg]
        if not rs:
            continue
        n, ap = len(rs), sum(x["approved"] for x in rs)
        tt = sum(x["total"] for x in rs)
        tot[cfg] = tt
        cp, cv = sum(x["cost_pub"] for x in rs), sum(x["cost_prov"] for x in rs)
        na = "sem entrega aprovada; razao nao calculavel"
        md.append(f"| {cfg} — {LABEL[cfg]} | {ap}/{n} | {tt} | {tt / n:.0f} | {st.mean(x['wall_s'] for x in rs):.1f} | {st.median(x['wall_s'] for x in rs):.1f} | "
                  f"{(f'{tt / ap:.0f}' if ap else na)} | {(f'{cp / ap:.4f}' if ap else na)} | {(f'{cv / ap:.5f}' if ap else na)} | "
                  f"{sum(x['calc_done'] for x in rs)}/{sum(x['calc_req'] for x in rs)} | {sum(x['unknown_usage'] for x in rs)} |")
    pairs = {(x["challenge"], x["rep"]) for x in rows if x["config"] == "B"} & {(x["challenge"], x["rep"]) for x in rows if x["config"] == "C"}
    clean = [k for k in pairs if not any(x["unknown_usage"] for x in rows if (x["challenge"], x["rep"]) == k)]
    if clean:
        tb = sum(x["total"] for x in rows if x["config"] == "B" and (x["challenge"], x["rep"]) in clean)
        tc = sum(x["total"] for x in rows if x["config"] == "C" and (x["challenge"], x["rep"]) in clean)
        md.append(f"\nVariacao de tokens da arena (C) frente ao generalista (B), pares equivalentes com uso conhecido {sorted(clean)}: "
                  f"100 x ({tc}/{tb} - 1) = {100 * (tc / tb - 1):+.1f}% (positivo = arena consome mais).")
        excl = sorted(pairs - set(clean))
        if excl:
            md.append(f"Pares excluidos por uso desconhecido: {excl}")
    (OUT / f"{phase}_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "battery")
