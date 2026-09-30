"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type RunSummary } from "@/lib/api";
import { DECISION_LABEL, STATUS_LABEL, when } from "@/lib/format";

const STATUS_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "accent", queued: "info" };

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.listRuns().then(setRuns).catch((e: Error) => setError(e.message));
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h1>Histórico de execuções</h1>
      <p className="lead">Reabra uma execução para consultar a configuração congelada, os artefatos e exportar o relatório.</p>
      {error && <div className="error">{error}</div>}
      <div className="panel">
        {runs === null ? (
          <p className="muted">Carregando…</p>
        ) : runs.length === 0 ? (
          <p className="muted">
            Nenhuma execução ainda. <Link href="/">Configure um desafio</Link>.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Título</th>
                <th>Modo</th>
                <th>Status</th>
                <th>Decisão</th>
                <th>Candidatos</th>
                <th>Criada</th>
                <th>Concluída</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <Link href={`/runs/${r.run_id}`}>{r.title || r.run_id}</Link>
                    {r.parent_run_id && <div className="hint">nova tentativa de {r.parent_run_id}</div>}
                  </td>
                  <td>{r.simulated ? <span className="badge seal">SIMULADO</span> : <span className="badge accent">REAL</span>}</td>
                  <td>
                    <span className={`badge ${STATUS_CLASS[r.status] ?? "info"}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
                  </td>
                  <td>{DECISION_LABEL[r.decision_status] ?? r.decision_status}</td>
                  <td className="num">{r.candidate_count}</td>
                  <td>{when(r.created_at)}</td>
                  <td>{when(r.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
