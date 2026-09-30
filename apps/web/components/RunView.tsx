"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, TERMINAL, type Report, type RunDetail, type RunEventView } from "@/lib/api";
import { DECISION_LABEL, ELIGIBILITY_LABEL, STATUS_LABEL, elapsed, money, num, when } from "@/lib/format";
import ResultsView from "./ResultsView";

const STATUS_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "accent", queued: "info" };
const STAGES = ["plan", "delegate", "propose", "critique", "revise", "verify", "judge"] as const;
const STAGE_LABEL: Record<string, string> = { plan: "planejamento", delegate: "especialistas", propose: "proposta", critique: "crítica", revise: "revisão", verify: "verificação", judge: "Judge" };

type CandidateProgress = {
  stages: Record<string, "done" | "active" | "fail" | "pending">;
  tasks: { task_id: string; kind: string; status: string; error?: string | null }[];
  proposalVersions: number[];
  eligibility?: string;
  critiquesGiven: number;
  critiquesReceived: number;
};

type EvidenceItem = { evidence_id: string; excerpt: string; type: string; source_id: string | null; locator: { page?: number | null; section?: string | null; line_start?: number | null; line_end?: number | null }; provenance: string };

function deriveProgress(events: RunEventView[], candidateIds: string[], critiqueRounds: number): Record<string, CandidateProgress> {
  const out: Record<string, CandidateProgress> = {};
  for (const cid of candidateIds) out[cid] = { stages: {}, tasks: [], proposalVersions: [], critiquesGiven: 0, critiquesReceived: 0 };
  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    const cid = p.candidate_id as string | undefined;
    switch (e.type) {
      case "plan.ready":
        if (cid && out[cid]) out[cid].stages.plan = "done";
        break;
      case "task.started":
        if (cid && out[cid]) {
          out[cid].stages.delegate = "active";
          out[cid].tasks.push({ task_id: String(p.task_id), kind: String(p.kind), status: "running" });
        }
        break;
      case "task.completed":
        if (cid && out[cid]) {
          const t = out[cid].tasks.find((x) => x.task_id === p.task_id);
          if (t) {
            t.status = String(p.status);
            t.error = p.error as string | null;
          }
          out[cid].stages.delegate = "done";
        }
        break;
      case "proposal.ready":
        if (cid && out[cid]) {
          out[cid].proposalVersions.push(Number(p.version));
          out[cid].stages.propose = "done";
          if (Number(p.version) >= 2) out[cid].stages.revise = "done";
        }
        break;
      case "proposal.failed":
        if (cid && out[cid]) out[cid].stages.propose = "fail";
        break;
      case "critique.ready": {
        const a = p.author_candidate_id as string;
        const t = p.target_candidate_id as string;
        if (out[a]) {
          out[a].critiquesGiven += 1;
          out[a].stages.critique = "done";
        }
        if (out[t]) out[t].critiquesReceived += 1;
        break;
      }
      case "verification.ready":
        if (cid && out[cid]) {
          out[cid].stages.verify = "done";
          out[cid].eligibility = String(p.eligibility);
        }
        break;
      case "evaluation.ready":
        for (const c of (p.candidates as string[]) ?? []) if (out[c]) out[c].stages.judge = "done";
        break;
      case "evaluation.failed":
        for (const c of candidateIds) out[c].stages.judge = "fail";
        break;
    }
  }
  if (critiqueRounds === 0) for (const c of candidateIds) delete out[c].stages.critique, delete out[c].stages.revise;
  return out;
}

export default function RunView({ runId }: { runId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEventView[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const lastSeq = useRef(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshDetail = useCallback(async () => {
    try {
      const d = await api.run(runId);
      setDetail(d);
      if (TERMINAL.has(d.status) && d.artifacts.report) setReport(d.artifacts.report as Report);
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [runId]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) return;
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      void refreshDetail();
    }, 400);
  }, [refreshDetail]);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    (async () => {
      const d = await refreshDetail();
      const initial = await api.events(runId).catch(() => [] as RunEventView[]);
      if (cancelled) return;
      setEvents(initial);
      lastSeq.current = initial.length ? initial[initial.length - 1].seq : 0;
      if (!d || TERMINAL.has(d.status)) return;
      // Reconexao segura: EventSource reenvia Last-Event-ID; recarregar a aba nao recria nem cancela o job.
      es = new EventSource(api.eventsUrl(runId, lastSeq.current));
      es.onopen = () => setConnected(true);
      es.onerror = () => setConnected(false);
      const onAny = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as RunEventView & { seq: number };
          if (typeof data.seq !== "number" || data.seq <= lastSeq.current) return;
          lastSeq.current = data.seq;
          setEvents((prev) => (prev.some((x) => x.seq === data.seq) ? prev : [...prev, data]));
          scheduleRefresh();
        } catch {
          /* ignora heartbeats */
        }
      };
      for (const t of [
        "run.started", "evidence.ready", "plan.ready", "task.started", "task.completed", "proposal.ready", "proposal.failed", "critique.order", "critique.ready",
        "verification.ready", "evaluation.ready", "evaluation.failed", "budget.updated", "call.finished", "report.ready", "run.finished", "run.failed", "run.cancelled",
        "run.cancel_requested", "run.interrupted", "run.late_result", "run.queued",
      ]) es.addEventListener(t, onAny as EventListener);
      es.addEventListener("stream.end", () => {
        es?.close();
        setConnected(false);
        void refreshDetail();
      });
    })();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [runId, refreshDetail, scheduleRefresh]);

  const candidates = detail?.snapshot.candidates ?? [];
  const progress = useMemo(() => deriveProgress(events, candidates.map((c) => c.candidate_id ?? ""), detail?.snapshot.critique_rounds ?? 1), [events, candidates, detail]);
  const packs = (detail?.artifacts.evidence_pack as { version: number; items: EvidenceItem[]; gaps: string[] }[] | undefined) ?? [];
  const latestPack = packs.length ? packs[packs.length - 1] : null;
  const evidence = latestPack?.items.find((i) => i.evidence_id === evidenceId) ?? null;
  const isTerminal = detail ? TERMINAL.has(detail.status) : false;

  async function cancel() {
    if (!confirm("Cancelar esta execução? Chamadas em voo terminam, mas nenhuma nova é admitida.")) return;
    await api.cancel(runId).catch((e: Error) => setError(e.message));
    scheduleRefresh();
  }

  function duplicate() {
    if (!detail) return;
    const sources = (latestPack?.items ?? []).length
      ? (packs[0] as unknown as { sources: { source_id: string; title: string; chars: number; media_type: string; sha256: string; warnings: string[]; pages: number | null }[] }).sources.map((s) => ({
          source_id: s.source_id, title: s.title, media_type: s.media_type, size_bytes: 0, sha256: s.sha256, extraction_status: "ok", pages: s.pages, chars: s.chars, warnings: s.warnings,
        }))
      : [];
    window.sessionStorage.setItem("agentathon:prefill", JSON.stringify({ challenge: detail.snapshot, sources }));
    router.push("/");
  }

  async function retry() {
    try {
      const r = await api.retry(runId);
      router.push(`/runs/${r.run_id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!detail) return error ? <div className="error">{error}</div> : <p className="muted">Carregando execução…</p>;

  const m = detail.metrics;
  const spentPct = m.cap ? Math.min(100, (Number(m.spent) / Number(m.cap)) * 100) : null;

  return (
    <div>
      <div className="row spread">
        <div>
          <h1>{detail.title || detail.run_id}</h1>
          <div className="row">
            <span className={`badge ${STATUS_CLASS[detail.status] ?? "info"}`}>{STATUS_LABEL[detail.status] ?? detail.status}</span>
            {detail.simulated ? <span className="badge seal">SIMULADO</span> : <span className="badge accent">REAL · {detail.mode}</span>}
            <span className="badge info">{DECISION_LABEL[detail.decision_status] ?? detail.decision_status}</span>
            <span className="mono muted">{detail.run_id}</span>
            {!isTerminal && <span className="hint">{connected ? "● eventos ao vivo" : "○ reconectando (polling)"}</span>}
          </div>
        </div>
        <div className="row">
          {!isTerminal && (
            <button className="danger" onClick={cancel}>
              Cancelar
            </button>
          )}
          <button onClick={duplicate}>Duplicar configuração</button>
          {isTerminal && <button onClick={retry}>Repetir (novo run)</button>}
          {report && (
            <>
              <a href={api.reportUrl(runId, "json")} target="_blank" rel="noreferrer">
                <button>Exportar JSON</button>
              </a>
              <a href={api.reportUrl(runId, "md")} target="_blank" rel="noreferrer">
                <button>Exportar Markdown</button>
              </a>
            </>
          )}
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {detail.error && <div className="notice">{detail.error}</div>}
      {detail.parent_run_id && (
        <p className="hint">
          Nova tentativa de <Link href={`/runs/${detail.parent_run_id}`}>{detail.parent_run_id}</Link>.
        </p>
      )}

      <div className="grid three">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Orçamento</h3>
          <dl className="kv">
            <dt>Chamadas</dt>
            <dd>
              {m.calls_used} / {m.calls_cap}
            </dd>
            <dt>Gasto conhecido</dt>
            <dd>
              {money(m.spent, m.currency)} <span className="badge info">{m.cost_quality}</span>
            </dd>
            <dt>Reservado</dt>
            <dd>{money(m.reserved, m.currency)}</dd>
            {Number(m.pending_unknown) > 0 && (
              <>
                <dt>Pendente (desconhecido)</dt>
                <dd className="badge warn">{money(m.pending_unknown, m.currency)}</dd>
              </>
            )}
            <dt>Teto</dt>
            <dd>{m.cap ? money(m.cap, m.currency) : "sem teto monetário"}</dd>
          </dl>
          {spentPct !== null && (
            <div className="progress" title={`${spentPct.toFixed(1)}% do teto`}>
              <div style={{ width: `${spentPct}%` }} />
            </div>
          )}
          <details style={{ marginTop: 8 }}>
            <summary>Buckets</summary>
            <table>
              <tbody>
                {detail.budget_buckets.map((b) => (
                  <tr key={b.bucket_key}>
                    <td className="mono">{b.bucket_key}</td>
                    <td className="num">
                      {num(b.spent, 5)} / {b.cap ? num(b.cap, 3) : "∞"}
                    </td>
                    <td className="num">{b.calls_used} ch.</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Execução</h3>
          <dl className="kv">
            <dt>Criada</dt>
            <dd>{when(detail.created_at)}</dd>
            <dt>Início</dt>
            <dd>{when(detail.started_at)}</dd>
            <dt>Duração</dt>
            <dd>
              {elapsed(detail.started_at, detail.finished_at)} / {m.deadline_s} s
            </dd>
            <dt>Seed</dt>
            <dd className="mono">{detail.seed}</dd>
            <dt>Rodada crítica</dt>
            <dd>{detail.snapshot.critique_rounds}</dd>
            <dt>Evidências</dt>
            <dd>{latestPack ? `${latestPack.items.length} trechos · pacote v${latestPack.version}` : "—"}</dd>
          </dl>
          <details style={{ marginTop: 8 }}>
            <summary>Configuração congelada (hashes)</summary>
            <div className="mono" style={{ fontSize: 11, wordBreak: "break-all" }}>
              {Object.entries(detail.snapshot_hashes).map(([k, v]) => (
                <div key={k}>
                  {k}: {v}
                </div>
              ))}
            </div>
          </details>
        </div>
        <div className="panel evidence-panel">
          <h3 style={{ marginTop: 0 }}>Evidência selecionada</h3>
          {evidence ? (
            <div>
              <div className="mono">{evidence.evidence_id}</div>
              <div className="hint">
                {evidence.type} · fonte {evidence.source_id ?? "derivação"} · {evidence.locator.page ? `p. ${evidence.locator.page}` : `linhas ${evidence.locator.line_start}-${evidence.locator.line_end}`} ·{" "}
                {evidence.provenance}
              </div>
              <p style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{evidence.excerpt}</p>
            </div>
          ) : (
            <p className="hint">Clique em um ID de evidência (ev-…/drv-…) para ver o trecho e o localizador.</p>
          )}
          {latestPack && latestPack.gaps.length > 0 && (
            <details>
              <summary>Lacunas do pacote ({latestPack.gaps.length})</summary>
              <ul className="tight">
                {latestPack.gaps.map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>

      <h2>Candidatos</h2>
      <div className="grid two">
        {candidates.map((c) => {
          const cid = c.candidate_id ?? "";
          const pr = progress[cid];
          const entry = report?.ranking.find((e) => e.candidate_id === cid);
          return (
            <div key={cid} className="card" style={{ borderLeftColor: c.color ?? "#2563eb" }}>
              <div className="row spread">
                <h3>{c.name}</h3>
                <span className="row">
                  {entry?.score_0_100 != null && <span className="badge accent">score {num(entry.score_0_100)}</span>}
                  {pr?.eligibility && <span className={`badge ${pr.eligibility === "eligible" ? "ok" : pr.eligibility === "ineligible" ? "bad" : "warn"}`}>{ELIGIBILITY_LABEL[pr.eligibility]}</span>}
                </span>
              </div>
              <div className="meta">
                {c.provider}/{c.model_option} · preset {c.preset ?? "personalizado"} · até {c.max_specialist_tasks} tarefas · especialistas: {(c.allowed_specialists ?? []).join(", ") || "nenhum"}
              </div>
              <div className="steps">
                {STAGES.filter((s) => !(detail.snapshot.critique_rounds === 0 && (s === "critique" || s === "revise"))).map((s) => (
                  <span key={s} className={`step ${pr?.stages[s] ?? ""}`}>
                    {STAGE_LABEL[s]}
                  </span>
                ))}
              </div>
              {pr && pr.tasks.length > 0 && (
                <ul className="tight">
                  {pr.tasks.map((t) => (
                    <li key={t.task_id}>
                      <code>{t.task_id}</code> {t.kind} — <span className={`badge ${t.status === "completed" ? "ok" : t.status === "running" ? "accent" : "warn"}`}>{t.status}</span>
                      {t.error && <span className="hint"> {t.error}</span>}
                    </li>
                  ))}
                </ul>
              )}
              <div className="hint">
                Propostas: {pr?.proposalVersions.length ? pr.proposalVersions.map((v) => `v${v}`).join(", ") : "—"} · críticas emitidas {pr?.critiquesGiven ?? 0} · recebidas {pr?.critiquesReceived ?? 0}
              </div>
            </div>
          );
        })}
      </div>

      {report && <ResultsView report={report} detail={detail} onEvidence={setEvidenceId} />}

      <h2>Linha do tempo (eventos reais)</h2>
      <div className="timeline">
        {events.map((e) => {
          const p = e.payload as Record<string, unknown>;
          const brief = ["candidate_id", "version", "status", "eligibility", "task_id", "kind", "decision_status", "reason", "author_candidate_id", "target_candidate_id", "calls_used"]
            .filter((k) => p[k] !== undefined && p[k] !== null)
            .map((k) => `${k}=${String(p[k])}`)
            .join(" ");
          return (
            <div key={e.seq}>
              <span className="t">#{String(e.seq).padStart(3, " ")}</span> {new Date(e.ts).toLocaleTimeString("pt-BR")} <strong>{e.type}</strong> {brief}
            </div>
          );
        })}
        {events.length === 0 && <div>sem eventos ainda</div>}
      </div>
    </div>
  );
}
