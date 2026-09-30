"""Cliente agente de exemplo: jornada completa via API, sem navegador.

Uso:
    python examples/agent_client.py --base-url http://127.0.0.1:8000 [--token TOKEN] [--out relatorio.md]

Fluxo: descobre catalogo -> prepara fontes (demo sintetica ou arquivos proprios) -> cria o desafio (202)
-> acompanha eventos (polling) -> baixa relatorio JSON e Markdown. Nao executa a proposta vencedora.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}


async def run_journey(client: httpx.AsyncClient, *, files: list[Path] | None = None, objective: str | None = None, poll_s: float = 0.5, quiet: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
    def log(*a: Any) -> None:
        if not quiet:
            print(*a)

    catalog = (await client.get("/api/v1/catalog")).raise_for_status().json()
    log(f"[catalogo] versao {catalog['catalog_version']} · modos {catalog['modes']} · presets {[p['preset'] for p in catalog['presets']]}")
    openapi = (await client.get("/openapi.json")).raise_for_status().json()
    log(f"[openapi] {len(openapi['paths'])} rotas descobertas")

    if files:
        source_ids = []
        for f in files:
            r = await client.post("/api/v1/sources", files={"file": (f.name, f.read_bytes())}, data={"title": f.stem})
            r.raise_for_status()
            source_ids.append(r.json()["source_id"])
            log(f"[fonte] {f.name} -> {r.json()['source_id']} ({r.json()['extraction_status']})")
        demo = (await client.post("/api/v1/demo/prepare")).raise_for_status().json()["challenge"]
        challenge = {**demo, "source_ids": source_ids, "title": f"Desafio via agente: {files[0].stem}"}
        if objective:
            challenge["objective"] = objective
    else:
        challenge = (await client.post("/api/v1/demo/prepare")).raise_for_status().json()["challenge"]
        log(f"[demo] fontes sinteticas preparadas: {challenge['source_ids']}")
        if objective:
            challenge["objective"] = objective

    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    r = await client.post("/api/v1/runs", json=challenge, headers=headers)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"criacao rejeitada ({r.status_code}): {r.text}")
    created = r.json()
    run_id = created["run_id"]
    log(f"[run] {run_id} status={created['status']} links={list(created['links'])}")

    last_seq = 0
    while True:
        events = (await client.get(f"/api/v1/runs/{run_id}/events/list", params={"after": last_seq})).raise_for_status().json()
        for e in events:
            last_seq = e["seq"]
            p = e["payload"]
            summary = {k: p[k] for k in ("candidate_id", "version", "status", "eligibility", "decision_status", "task_id", "kind") if k in p}
            log(f"  #{e['seq']:>3} {e['type']:<20} {json.dumps(summary, ensure_ascii=False) if summary else ''}")
        detail = (await client.get(f"/api/v1/runs/{run_id}")).raise_for_status().json()
        if detail["status"] in TERMINAL:
            break
        await asyncio.sleep(poll_s)

    report = (await client.get(f"/api/v1/runs/{run_id}/report", params={"format": "json"})).raise_for_status().json()
    markdown = (await client.get(f"/api/v1/runs/{run_id}/report", params={"format": "md"})).raise_for_status().text
    log(f"[resultado] status={report['status']} decisao={report['decision_status']} simulado={report['simulated']} vencedor={report['winner_candidate_id']}")
    for e in sorted(report["ranking"], key=lambda e: (e["rank"] is None, e["rank"] or 0)):
        score = f"{float(e['score_0_100']):.2f}" if e["score_0_100"] is not None else "n/d"
        log(f"   {e['rank'] or '-'}  {e['candidate_name']:<22} score={score:<7} {e['eligibility']}")
    log(f"[custo] total={report['cost']['total']} {report['cost']['currency']} ({report['cost']['quality']}) chamadas={report['cost']['calls_used']}/{report['cost']['calls_cap']}")
    return {"run_id": run_id, "detail": detail, "report": report, "markdown": markdown}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default=None, help="Bearer token quando AGENTATHON_AUTH_MODE=token")
    ap.add_argument("--file", action="append", type=Path, default=None, help="TXT/MD/PDF proprio (repetivel). Sem --file usa a demo sintetica.")
    ap.add_argument("--objective", default=None)
    ap.add_argument("--out", type=Path, default=None, help="grava o relatorio Markdown neste caminho")
    ap.add_argument("--idempotency-key", default=None)
    args = ap.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, timeout=60) as client:
        result = await run_journey(client, files=args.file, objective=args.objective, idempotency_key=args.idempotency_key)
    if args.out:
        args.out.write_text(result["markdown"], encoding="utf-8")
        print(f"[saida] relatorio Markdown salvo em {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
