r"""Agrega runs.jsonl + calls.jsonl + evals.jsonl em tabelas Markdown (analysis.md) e summary.json.

    .venv\Scripts\python.exe <bench>\analyze.py main
"""

import json
import math
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "out"
sys.path.insert(0, str(BENCH))
import harness as H  # noqa: E402,F401
from challenges import BY_ID, CHALLENGES  # noqa: E402
from evaluate import code_checks  # noqa: E402

CRIT = ["aderencia", "evidencias", "consistencia", "incertezas", "utilidade"]
QUALITY_MIN = 6.0


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    xs = [x for x in xs if x is not None]
    return st.stdev(xs) if len(xs) > 1 else None


def f(x, nd=2, pct=False):
    if x is None:
        return "—"
    if pct:
        return f"{100 * x:.0f}%"
    return f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def binom_two_sided(k: int, n: int) -> float | None:
    if n == 0:
        return None
    pk = [math.comb(n, i) / 2**n for i in range(n + 1)]
    obs = pk[k]
    return min(1.0, sum(p for p in pk if p <= obs + 1e-12))


def load(phase: str):
    runs = [r for r in jl(OUT / "runs.jsonl") if r["phase"] == phase]
    calls = jl(OUT / "calls.jsonl")
    evals = [e for e in jl(OUT / "evals.jsonl") if e.get("items") and e["group"].startswith(phase + "-")]
    by_exec_calls = defaultdict(list)
    for c in calls:
        by_exec_calls[c.get("exec_id")].append(c)
    scores = defaultdict(list)  # exec_id -> list of per-pass dicts
    pos = []
    for e in evals:
        for it in e["items"]:
            scores[it["exec_id"]].append(it)
            pos.append((it["label"], mean([it[c] for c in CRIT])))
    rows = []
    for r in runs:
        ch = BY_ID[r["challenge"]]
        cs = by_exec_calls.get(r["exec_id"], [])
        cc = code_checks(ch, r.get("deliverable"), r.get("pack"))
        sc = scores.get(r["exec_id"], [])
        q = mean([mean([s[c] for c in CRIT]) for s in sc]) if sc else (0.0 if not r.get("deliverable") else None)
        crit_means = {c: mean([s[c] for s in sc]) for c in CRIT} if sc else {c: None for c in CRIT}
        pass_q = [mean([s[c] for c in CRIT]) for s in sc]
        tok_in = sum(c["in_tok"] or 0 for c in cs)
        tok_out = sum(c["out_tok"] or 0 for c in cs)
        unknown = sum(1 for c in cs if c["usage_source"] != "api_usage")
        approved = bool(cc["opcao_correta"] and cc["metricas_corretas"] and cc["refs_inexistentes"] == 0 and q is not None and q >= QUALITY_MIN)
        row = {
            "exec_id": r["exec_id"], "challenge": r["challenge"], "complexity": r["complexity"], "config": r["config"], "rep": r["rep"],
            "order": r["order_in_block"], "ok": r["ok"], "error": r.get("error"), "wall_s": r["wall_s"],
            "attempts": len(cs), "logical": sum(1 for c in cs if c["attempt"] == 1), "repairs": sum(1 for c in cs if c["repair"]),
            "failed_attempts": sum(1 for c in cs if c["error"]), "unknown_usage": unknown,
            "in": tok_in, "out": tok_out, "total": tok_in + tok_out,
            "cost_pub": sum(c["cost_public_usd"] or 0 for c in cs), "cost_prov": sum(c["cost_provider_usd"] or 0 for c in cs),
            "cached": [c["cached_tok"] for c in cs if c["cached_tok"] is not None], "reasoning": [c["reasoning_tok"] for c in cs if c["reasoning_tok"] is not None],
            "reported_models": sorted({str(c["reported_model"]) for c in cs}), "latency_sum_s": sum(c["latency_ms"] for c in cs) / 1000,
            "quality": q, "quality_passes": pass_q, "n_passes": len(sc), **{f"q_{c}": crit_means[c] for c in CRIT}, **cc, "approved": approved,
            "reserved_engine": sum(float(c.get("reserved") or 0) for c in (r.get("engine_calls") or [])) if r["config"].startswith("C") else None,
            "decision_status": r.get("decision_status"), "deliverable_rule": r.get("deliverable_rule"), "run_status": r.get("status"),
            "self_review_rounds": r.get("self_review_rounds_done"), "cap": r.get("cap"),
            "evaluator_errors": [x for s in sc for x in s.get("erros", [])],
        }
        if r["config"].startswith("C"):
            stage = defaultdict(lambda: {"attempts": 0, "in": 0, "out": 0, "cost_pub": 0.0, "lat": 0.0})
            for c in cs:
                s = stage[c["stage"]]
                s["attempts"] += 1
                s["in"] += c["in_tok"] or 0
                s["out"] += c["out_tok"] or 0
                s["cost_pub"] += c["cost_public_usd"] or 0
                s["lat"] += c["latency_ms"] / 1000
            row["stages"] = dict(stage)
            props = r.get("all_proposals") or []
            row["c_props"] = [{"cid": p["candidate_id"], **code_checks(ch, p, r.get("pack"))} for p in props]
            row["winner_cid"] = (r.get("deliverable") or {}).get("candidate_id")
        rows.append(row)
    return runs, rows, pos


def proposal_versions(run_id: str) -> list[dict]:
    db = sqlite3.connect(str(BENCH / "data" / "agentathon.db"))
    cur = db.execute("select candidate_id, version, payload from artifacts where run_id=? and kind='proposal' order by candidate_id, version", (run_id,))
    out = [{"cid": cid, "version": v, "payload": json.loads(p) if isinstance(p, str) else p} for cid, v, p in cur.fetchall()]
    db.close()
    return out


def table(headers, rows):
    s = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    for r in rows:
        s += "| " + " | ".join(str(x) for x in r) + " |\n"
    return s


def summarize(rows, cfg):
    rs = [r for r in rows if r["config"] == cfg]
    if not rs:
        return None
    n = len(rs)
    appr = sum(r["approved"] for r in rs)
    tot_cost = sum(r["cost_pub"] for r in rs)
    tot_prov = sum(r["cost_prov"] for r in rs)
    return {
        "n": n, "entregues": sum(r["entregue"] for r in rs), "aprovadas": appr, "taxa_aprov": appr / n,
        "qual": mean([r["quality"] for r in rs]), "qual_sd": sd([r["quality"] for r in rs]),
        "opcao_correta": mean([r["opcao_correta"] for r in rs]), "opcao_valida": mean([r["opcao_valida"] for r in rs]),
        "metricas_corretas": mean([r["metricas_corretas"] for r in rs]), "metricas_ok_frac": mean([r["metricas_ok"] / r["metricas_total"] for r in rs]),
        "refs_inex": sum(r["refs_inexistentes"] or 0 for r in rs), "runs_refs_inex": sum(1 for r in rs if (r["refs_inexistentes"] or 0) > 0),
        "suporte": mean([r["suporte_metricas"] for r in rs]), "completude": mean([r["completude"] for r in rs]),
        "attempts": mean([r["attempts"] for r in rs]), "logical": mean([r["logical"] for r in rs]), "repairs": sum(r["repairs"] for r in rs),
        "failed_attempts": sum(r["failed_attempts"] for r in rs), "unknown_usage": sum(r["unknown_usage"] for r in rs),
        "in": mean([r["in"] for r in rs]), "out": mean([r["out"] for r in rs]), "total": mean([r["total"] for r in rs]),
        "cost_pub": mean([r["cost_pub"] for r in rs]), "cost_prov": mean([r["cost_prov"] for r in rs]),
        "cost_pub_total": tot_cost, "cost_prov_total": tot_prov,
        "cost_per_appr_pub": tot_cost / appr if appr else None, "cost_per_appr_prov": tot_prov / appr if appr else None,
        "wall": mean([r["wall_s"] for r in rs]), "wall_med": st.median([r["wall_s"] for r in rs]), "wall_max": max(r["wall_s"] for r in rs),
        "chars": mean([r["chars"] for r in rs]), "reserved": mean([r["reserved_engine"] for r in rs]) if rs[0]["reserved_engine"] is not None else None,
        **{f"q_{c}": mean([r[f"q_{c}"] for r in rs]) for c in CRIT},
    }


def paired(rows, a, b, key="quality"):
    """Diferenca pareada b - a por (desafio, repeticao)."""
    ia = {(r["challenge"], r["rep"]): r for r in rows if r["config"] == a}
    ib = {(r["challenge"], r["rep"]): r for r in rows if r["config"] == b}
    diffs = []
    for k in sorted(set(ia) & set(ib)):
        va, vb = ia[k][key], ib[k][key]
        if va is None or vb is None:
            continue
        diffs.append((k, float(vb) - float(va)))
    wins = sum(1 for _, d in diffs if d > 1e-9)
    losses = sum(1 for _, d in diffs if d < -1e-9)
    ties = len(diffs) - wins - losses
    p = binom_two_sided(min(wins, losses), wins + losses) if wins + losses else None
    return {"n": len(diffs), "mean_diff": mean([d for _, d in diffs]), "wins": wins, "losses": losses, "ties": ties, "p_sign": p, "diffs": diffs}


def main(phase: str) -> None:
    runs, rows, pos = load(phase)
    cfgs = [c for c in ["A", "B", "C", "B+", "C$"] if any(r["config"] == c for r in rows)]
    md = []
    S = {c: summarize(rows, c) for c in cfgs}
    md.append(f"## Cobertura ({phase})\n")
    md.append(table(["Config", "Execuções", "Com entrega", "Falhas de execução", "Avaliadas (passadas)"],
                    [[c, S[c]["n"], S[c]["entregues"], sum(1 for r in rows if r["config"] == c and not r["ok"]),
                      f"{sum(1 for r in rows if r['config'] == c and r['n_passes'] > 0)} ({sum(r['n_passes'] for r in rows if r['config'] == c)})"] for c in cfgs]))
    md.append("\n## Tabela comparativa geral\n")
    keys = [("Entregas aprovadas (patamar)", lambda s: f"{s['aprovadas']}/{s['n']} ({f(s['taxa_aprov'], pct=True)})"),
            ("Qualidade externa média (0–10) ± dp", lambda s: f"{f(s['qual'])} ± {f(s['qual_sd'])}"),
            ("Opção correta", lambda s: f(s["opcao_correta"], pct=True)),
            ("Opção escolhida atende às restrições obrigatórias", lambda s: f(s["opcao_valida"], pct=True)),
            ("Todas as métricas exigidas corretas", lambda s: f(s["metricas_corretas"], pct=True)),
            ("Métricas exigidas corretas (fração)", lambda s: f(s["metricas_ok_frac"], pct=True)),
            ("Referências inexistentes (total / execuções afetadas)", lambda s: f"{s['refs_inex']} / {s['runs_refs_inex']}"),
            ("Métricas comprovadas pela evidência citada", lambda s: f(s["suporte"], pct=True)),
            ("Completude (7 itens)", lambda s: f(s["completude"], pct=True)),
            ("Chamadas HTTP por execução (tentativas)", lambda s: f(s["attempts"], 1)),
            ("Reparos de JSON (total)", lambda s: s["repairs"]),
            ("Tentativas com erro (total) / uso desconhecido", lambda s: f"{s['failed_attempts']} / {s['unknown_usage']}"),
            ("Tokens de entrada por execução", lambda s: f(s["in"], 0)),
            ("Tokens de saída por execução", lambda s: f(s["out"], 0)),
            ("Tokens totais por execução", lambda s: f(s["total"], 0)),
            ("Custo calculado por execução (tabela pública, US$)", lambda s: f(s["cost_pub"], 4)),
            ("Custo informado pela API por execução (estimated_cost, US$)", lambda s: f(s["cost_prov"], 5)),
            ("Custo total incl. falhas ÷ entregas aprovadas (tabela pública, US$)", lambda s: f(s["cost_per_appr_pub"], 4)),
            ("Custo total incl. falhas ÷ entregas aprovadas (API, US$)", lambda s: f(s["cost_per_appr_prov"], 5)),
            ("Tempo até a entrega: média / mediana / máx (s)", lambda s: f"{f(s['wall'], 0)} / {f(s['wall_med'], 0)} / {f(s['wall_max'], 0)}"),
            ("Tamanho da entrega (caracteres)", lambda s: f(s["chars"], 0)),
            ]
    md.append(table(["Métrica"] + cfgs, [[k] + [fn(S[c]) for c in cfgs] for k, fn in keys]))
    md.append("\nNotas por critério do avaliador externo (média):\n")
    md.append(table(["Critério"] + cfgs, [[c] + [f(S[x][f"q_{c}"]) for x in cfgs] for c in CRIT]))

    # por complexidade
    md.append("\n## Por complexidade\n")
    hdr = ["Complexidade", "Config", "Aprovadas", "Qualidade", "Opção correta", "Métricas corretas", "Tokens totais", "Custo pub. (US$)", "Tempo médio (s)"]
    body = []
    for cx in ["simples", "intermediario", "complexo"]:
        sub = [r for r in rows if r["complexity"] == cx]
        for c in cfgs:
            s = summarize(sub, c)
            if s:
                body.append([cx, c, f"{s['aprovadas']}/{s['n']}", f(s["qual"]), f(s["opcao_correta"], pct=True), f(s["metricas_corretas"], pct=True),
                             f(s["total"], 0), f(s["cost_pub"], 4), f(s["wall"], 0)])
    md.append(table(hdr, body))

    # por desafio
    md.append("\n## Por desafio\n")
    hdr = ["Desafio", "Config", "Aprovadas", "Qualidade (por repetição)", "Opções escolhidas", "Erros de métrica (exemplos)", "Custo pub. médio", "Tempo médio (s)"]
    body = []
    for ch in CHALLENGES:
        for c in cfgs:
            rs = sorted([r for r in rows if r["challenge"] == ch["id"] and r["config"] == c], key=lambda r: r["rep"])
            if not rs:
                continue
            errs = sorted({e for r in rs for e in r["erros_metricas"]})[:3]
            body.append([f"{ch['id']} ({ch['complexity']})", c, f"{sum(r['approved'] for r in rs)}/{len(rs)}", " / ".join(f(r["quality"], 1) for r in rs),
                         ", ".join(str(r["opcao"]) for r in rs), "; ".join(errs) or "—", f(mean([r["cost_pub"] for r in rs]), 4), f(mean([r["wall_s"] for r in rs]), 0)])
    md.append(table(hdr, body))

    # pareados
    md.append("\n## Comparações pareadas (mesmo desafio e repetição)\n")
    body = []
    for a, b in [("A", "B"), ("B", "C"), ("A", "C"), ("B+", "C$")]:
        if a in cfgs and b in cfgs:
            for key, name in [("quality", "qualidade"), ("approved", "aprovação"), ("cost_pub", "custo pub."), ("total", "tokens"), ("wall_s", "tempo")]:
                p = paired(rows, a, b, key)
                body.append([f"{b} − {a}", name, p["n"], f(p["mean_diff"], 4 if key == "cost_pub" else 2), f"{p['wins']}/{p['ties']}/{p['losses']}", f(p["p_sign"], 3)])
    md.append(table(["Comparação", "Medida", "Pares", "Diferença média", f"{'Vitórias/empates/derrotas do segundo'}", "p (teste do sinal)"], body))
    for cx in ["simples", "intermediario", "complexo"]:
        sub = [r for r in rows if r["complexity"] == cx]
        line = []
        for a, b in [("B", "C"), ("A", "B")]:
            if a in cfgs and b in cfgs:
                p = paired(sub, a, b, "quality")
                line.append(f"{b}−{a}: {f(p['mean_diff'])} ({p['wins']}/{p['ties']}/{p['losses']})")
        if line:
            md.append(f"- Qualidade pareada em **{cx}**: " + "; ".join(line) + "\n")

    # etapas de C
    cs = [r for r in rows if r["config"] in ("C", "C$") and r.get("stages")]
    if cs:
        md.append("\n## Consumo por etapa do Agentathon (C)\n")
        stages = sorted({k for r in cs for k in r["stages"]}, key=lambda s: ["plan", "research", "propose", "critique", "revise", "judge"].index(s) if s in ["plan", "research", "propose", "critique", "revise", "judge"] else 9)
        tot_all = sum(r["total"] for r in cs)
        cost_all = sum(r["cost_pub"] for r in cs)
        body = []
        for s in stages:
            att = sum(r["stages"].get(s, {}).get("attempts", 0) for r in cs)
            tin = sum(r["stages"].get(s, {}).get("in", 0) for r in cs)
            tout = sum(r["stages"].get(s, {}).get("out", 0) for r in cs)
            cp = sum(r["stages"].get(s, {}).get("cost_pub", 0) for r in cs)
            lat = sum(r["stages"].get(s, {}).get("lat", 0) for r in cs)
            body.append([s, f(att / len(cs), 2), f(tin / len(cs), 0), f(tout / len(cs), 0), f((tin + tout) / tot_all, pct=True), f(cp / cost_all, pct=True), f(lat / len(cs), 1)])
        md.append(table(["Etapa", "Tentativas por arena", "Tokens entrada", "Tokens saída", "% tokens", "% custo", "Latência somada (s)"], body))
        dec = Counter(r["decision_status"] for r in cs)
        rule = Counter(r["deliverable_rule"] for r in cs)
        md.append(f"\nDecisão oficial das arenas: {dict(dec)}. Regra de entrega usada: {dict(rule)}.\n")
        # juiz interno escolheu a melhor das duas?
        disc = 0
        right = 0
        for r in cs:
            props = r.get("c_props") or []
            if len(props) == 2 and props[0]["opcao_correta"] != props[1]["opcao_correta"]:
                disc += 1
                win = next((p for p in props if p["cid"] == r["winner_cid"]), None)
                right += int(bool(win and win["opcao_correta"]))
        both = sum(1 for r in cs if len(r.get("c_props") or []) == 2 and all(p["opcao_correta"] for p in r["c_props"]))
        none = sum(1 for r in cs if len(r.get("c_props") or []) == 2 and not any(p["opcao_correta"] for p in r["c_props"]))
        md.append(f"\nSeleção pelo juiz interno: nas {len(cs)} arenas, as duas equipes acertaram a opção em {both}, nenhuma acertou em {none}, e houve divergência em {disc}; "
                  f"nessas divergências, a proposta entregue (rank 1) era a correta em {right}.\n")
        mdis = 0
        mright = 0
        for r in cs:
            props = r.get("c_props") or []
            if len(props) == 2 and props[0]["metricas_corretas"] != props[1]["metricas_corretas"]:
                mdis += 1
                win = next((p for p in props if p["cid"] == r["winner_cid"]), None)
                mright += int(bool(win and win["metricas_corretas"]))
        md.append(f"Divergência em 'todas as métricas corretas' entre as duas equipes: {mdis} arenas; a entregue era a correta em {mright}.\n")

    # efeito da revisao (v1 -> versao final) em B e C
    md.append("\n## Efeito da crítica/revisão (versão 1 → versão final)\n")
    body = []
    for c in [x for x in cfgs if x in ("B", "C", "B+", "C$")]:
        trans = Counter()
        for r0 in [r for r in runs if r["config"] == c and r.get("deliverable")]:
            ch = BY_ID[r0["challenge"]]
            pairs = []
            if c.startswith("B"):
                vs = r0.get("versions") or []
                if len(vs) >= 2:
                    pairs.append((vs[0], vs[-1]))
            elif r0.get("run_id"):
                pv = proposal_versions(r0["run_id"])
                by = defaultdict(list)
                for p in pv:
                    by[p["cid"]].append(p)
                for cid, lst in by.items():
                    lst.sort(key=lambda p: p["version"])
                    if len(lst) >= 2:
                        pairs.append((lst[0]["payload"], lst[-1]["payload"]))
            for v1, vf in pairs:
                a1 = code_checks(ch, v1, r0.get("pack"))
                af = code_checks(ch, vf, r0.get("pack"))
                k1 = (a1["opcao_correta"] and a1["metricas_corretas"])
                kf = (af["opcao_correta"] and af["metricas_corretas"])
                trans[("certo" if k1 else "errado") + "→" + ("certo" if kf else "errado")] += 1
        body.append([c, sum(trans.values()), trans.get("errado→certo", 0), trans.get("certo→errado", 0), trans.get("certo→certo", 0), trans.get("errado→errado", 0)])
    md.append(table(["Config", "Propostas revisadas", "errado→certo", "certo→errado", "certo→certo", "errado→errado"], body))
    md.append("(\"certo\" = opção correta e todas as métricas exigidas corretas, verificado em código.)\n")

    # avaliador: consistencia e posicao
    md.append("\n## Confiabilidade do avaliador externo\n")
    spreads = [max(r["quality_passes"]) - min(r["quality_passes"]) for r in rows if len(r["quality_passes"]) > 1]
    bypos = defaultdict(list)
    for lab, q in pos:
        bypos[lab].append(q)
    md.append(f"- Diferença máx−mín entre passadas da mesma entrega: média {f(mean(spreads))}, máx {f(max(spreads) if spreads else None)}.\n")
    md.append("- Nota média por posição de apresentação: " + ", ".join(f"{k}: {f(mean(v))}" for k, v in sorted(bypos.items())) + ".\n")
    qs = [(r["chars"], r["quality"]) for r in rows if r["quality"] is not None and r["entregue"]]
    if len(qs) > 2:
        xs, ys = zip(*qs, strict=True)
        mx, my = mean(xs), mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in qs)
        corr = cov / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        md.append(f"- Correlação (Pearson) entre tamanho da entrega e nota: {f(corr)}.\n")
    agree = []
    for r in rows:
        if r["quality"] is not None and r["entregue"]:
            agree.append((r["opcao_correta"] and r["metricas_corretas"], r["quality"]))
    md.append(f"- Nota média do avaliador para entregas corretas em código: {f(mean([q for ok, q in agree if ok]))}; incorretas: {f(mean([q for ok, q in agree if not ok]))}.\n")

    # modelos informados
    md.append("\n## Modelos informados pela API e uso\n")
    rm = Counter(m for r in rows for m in r["reported_models"])
    md.append(f"- Modelos informados no campo `model` das respostas (geração): {dict(rm)}.\n")
    md.append(f"- Tokens em cache informados: {sum(sum(r['cached']) for r in rows)} (campos presentes em {sum(len(r['cached']) for r in rows)} chamadas). "
              f"Tokens de reasoning informados: {sum(sum(r['reasoning']) for r in rows)} (presentes em {sum(len(r['reasoning']) for r in rows)} chamadas).\n")

    # por execucao (apendice)
    md.append("\n## Resultados por execução\n")
    hdr = ["exec_id", "Des.", "Cfg", "Rep", "Ordem", "Opção", "Métricas ok", "Refs inex.", "Suporte", "Complet.", "Qualidade (passadas)", "Aprov.", "Tent.", "Reparos", "Erros", "Tok. in", "Tok. out", "US$ pub.", "US$ API", "Tempo (s)", "Decisão C"]
    body = []
    for r in sorted(rows, key=lambda r: (r["rep"], [c["id"] for c in CHALLENGES].index(r["challenge"]), r["order"])):
        body.append([r["exec_id"], r["challenge"], r["config"], r["rep"], r["order"], r["opcao"], f"{r['metricas_ok']}/{r['metricas_total']}", r["refs_inexistentes"],
                     f(r["suporte_metricas"], pct=True), f(r["completude"], pct=True), f"{f(r['quality'])} ({', '.join(f(x, 1) for x in r['quality_passes'])})",
                     "sim" if r["approved"] else "não", r["attempts"], r["repairs"], r["failed_attempts"], r["in"], r["out"], f(r["cost_pub"], 4), f(r["cost_prov"], 5),
                     f(r["wall_s"], 0), r["decision_status"] or "—"])
    md.append(table(hdr, body))
    (OUT / f"analysis_{phase}.md").write_text("\n".join(md), encoding="utf-8")
    json.dump({"summary": S, "rows": [{k: v for k, v in r.items() if k not in ("stages", "c_props")} for r in rows]},
              open(OUT / f"summary_{phase}.json", "w", encoding="utf-8"), ensure_ascii=False, default=str, indent=1)
    print("\n".join(md[:12]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "main")
