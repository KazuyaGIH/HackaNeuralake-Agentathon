"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, TERMINAL, type Report, type RunDetail, type RunEventView } from "@/lib/api";
import { elapsed, STATUS_LABEL } from "@/lib/format";
import { createProject, type RunMeta } from "@/lib/projects";
import Icon from "./Icon";
import ActionPlanView from "./arena/ActionPlanView";
import LiveView, { Stepper } from "./arena/LiveView";
import type { Feedback } from "./arena/NextSteps";
import Results, { usd } from "./arena/Results";
import { SILENT, deriveLive, kindOf } from "./arena/live";

type Props = {
  runId: string;
  title?: string;
  onNewRun?: (runId: string, meta?: RunMeta) => void;
  onStatus?: (detail: RunDetail) => void;
  onRename?: () => void;
  onDelete?: () => void;
};
type EvidenceItem = { evidence_id: string; excerpt: string; type: string; source_id: string | null; locator: { page?: number | null; section?: string | null; line_start?: number | null; line_end?: number | null }; provenance: string };

const STATUS_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "live", queued: "info" };
// Ritmo do replay: rapido o bastante para nao cansar, lento o bastante para acompanhar cada etapa.
const STEP_MS = 420;

const ALL_EVENTS = [
  "run.started", "evidence.ready", "plan.ready", "task.started", "task.completed", "proposal.ready", "proposal.failed", "critique.order", "critique.ready",
  "verification.ready", "evaluation.ready", "evaluation.failed", "budget.updated", "call.finished", "report.ready", "run.finished", "run.failed", "run.cancelled",
  "run.cancel_requested", "run.interrupted", "run.late_result", "run.queued", "action_plan.started", "action_plan.ready", "action_plan.failed",
];

const TEAM_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea"];

export default function RunView({ runId, title, onNewRun, onStatus, onRename, onDelete }: Props) {
  const router = useRouter();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEventView[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [shown, setShown] = useState<number | null>(null); // null = mostrar tudo; numero = replay em andamento
  const [menu, setMenu] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>({});
  const [sending, setSending] = useState(false);
  const lastSeq = useRef(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  const refreshDetail = useCallback(async () => {
    try {
      const d = await api.run(runId);
      setDetail(d);
      onStatusRef.current?.(d);
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
      // Run ainda em andamento ao abrir: os eventos entram no ritmo do replay para dar tempo de acompanhar.
      setShown(initial.length);
      es = new EventSource(api.eventsUrl(runId, lastSeq.current));
      const onAny = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data) as RunEventView & { seq: number };
          if (typeof data.seq !== "number" || data.seq <= lastSeq.current) return;
          lastSeq.current = data.seq;
          setEvents((prev) => (prev.some((x) => x.seq === data.seq) ? prev : [...prev, data]));
          scheduleRefresh();
        } catch {
          /* heartbeat */
        }
      };
      for (const t of ALL_EVENTS) es.addEventListener(t, onAny as EventListener);
      es.addEventListener("stream.end", () => {
        es?.close();
        void refreshDetail();
      });
    })();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [runId, refreshDetail, scheduleRefresh]);

  // Replay: avanca um evento "visivel" por passo; eventos silenciosos (custos) passam junto.
  useEffect(() => {
    if (shown === null) return;
    if (shown >= events.length) {
      if (detail && TERMINAL.has(detail.status) && events.length > 0) {
        const t = setTimeout(() => setShown(null), 700);
        return () => clearTimeout(t);
      }
      return;
    }
    const t = setTimeout(() => {
      let n = shown;
      while (n < events.length && SILENT.has(events[n].type)) n++;
      setShown(Math.min(events.length, n + 1));
    }, shown === 0 ? 250 : STEP_MS);
    return () => clearTimeout(t);
  }, [shown, events, detail]);

  const visible = useMemo(() => (shown === null ? events : events.slice(0, shown)), [events, shown]);
  const live = useMemo(() => (detail ? deriveLive(detail, visible, shown === null && TERMINAL.has(detail.status)) : null), [detail, visible, shown]);
  const packs = (detail?.artifacts.evidence_pack as { version: number; items: EvidenceItem[]; sources?: { source_id: string; title: string }[] }[] | undefined) ?? [];
  const latestPack = packs.length ? packs[packs.length - 1] : null;
  const evidence = latestPack?.items.find((i) => i.evidence_id === evidenceId) ?? null;
  const sourceTitle = (sid: string | null) => (sid ? (packs[0]?.sources?.find((s) => s.source_id === sid)?.title ?? sid) : "cálculo derivado");

  if (!detail || !live) return error ? <div className="error">{error}</div> : <div className="arena-loading"><span className="spinner" /> Carregando a arena…</div>;

  const isTerminal = TERMINAL.has(detail.status);
  const playing = shown !== null;
  const showResults = isTerminal && !playing && report;

  async function cancel() {
    await api.cancel(runId).catch((e: Error) => setError(e.message));
    scheduleRefresh();
  }

  function duplicate() {
    if (!detail) return;
    const sources = (packs[0]?.sources ?? []).map((s) => ({
      source_id: s.source_id, title: s.title, media_type: "text/markdown", size_bytes: 0, sha256: "", extraction_status: "ok", pages: null, chars: 0, warnings: [],
    }));
    const project = createProject({ ...detail.snapshot, seed: null, refinement: null, action_plan: null }, sources);
    router.push(`/projetos/${project.id}`);
  }

  function openNew(newId: string, meta: RunMeta) {
    if (onNewRun) onNewRun(newId, meta);
    else router.push(`/runs/${newId}`);
  }

  async function retry() {
    try {
      const r = await api.retry(runId);
      openNew(r.run_id, { kind: "arena" });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function refine(items: { candidate_id: string; comment: string }[], general: string) {
    setSending(true);
    try {
      const r = await api.refine(runId, items, general);
      openNew(r.run_id, { kind: "refinement", parent: runId });
    } catch (e) {
      setError((e as Error).message);
      setSending(false);
    }
  }

  async function plan(candidateId: string, instructions: string) {
    setSending(true);
    try {
      const r = await api.actionPlan(runId, candidateId, instructions);
      openNew(r.run_id, { kind: "action_plan", parent: runId });
    } catch (e) {
      setError((e as Error).message);
      setSending(false);
    }
  }

  const kind = kindOf(detail);
  const cands = detail.snapshot.candidates ?? [];
  const teamOf = (id: string) => {
    const i = cands.findIndex((c) => c.candidate_id === id);
    return { name: cands[i]?.name ?? id, color: cands[i]?.color ?? TEAM_COLORS[Math.max(0, i) % TEAM_COLORS.length] };
  };

  const statusKey = playing ? "running" : detail.status;

  return (
    <div className="arena">
      <header className="arena-head">
        <div>
          <h1>{title ?? (detail.title || "Arena")}</h1>
          <div className="arena-meta">
            <span className={`status-pill ${STATUS_CLASS[statusKey] ?? "info"}`}>
              <span className="pulse" />
              {playing && isTerminal ? "Reproduzindo" : (STATUS_LABEL[statusKey] ?? statusKey)}
            </span>
            {detail.simulated && <span className="badge seal">SIMULADO</span>}
            {kind === "refinement" && <span className="badge accent">Repescagem {detail.snapshot.refinement?.round}</span>}
            {kind === "action_plan" && <span className="badge accent">Plano de ação</span>}
            <span className="muted small">
              {kind === "refinement" ? (detail.snapshot.refinement?.feedback.length ?? 0) : cands.length} equipe{(kind === "refinement" ? (detail.snapshot.refinement?.feedback.length ?? 0) : cands.length) === 1 ? "" : "s"} · {(detail.snapshot.judges ?? []).length || 1} juiz{((detail.snapshot.judges ?? []).length || 1) > 1 ? "es" : ""}
              {isTerminal && ` · ${elapsed(detail.started_at, detail.finished_at)} · ${usd(report?.cost.total ?? detail.metrics.spent)}`}
            </span>
          </div>
        </div>
        <div className="row">
          {!isTerminal && (
            <button className="danger" onClick={cancel}>
              <Icon name="x" /> Cancelar
            </button>
          )}
          {isTerminal && !playing && (
            <button onClick={() => setShown(0)}>
              <Icon name="play" size={14} /> Rever execução
            </button>
          )}
          {playing && isTerminal && <button onClick={() => setShown(null)}>Pular para o resultado</button>}
          {isTerminal && kind === "arena" && (
            <button onClick={retry}>
              <Icon name="zap" size={14} /> Rodar de novo
            </button>
          )}
          <div className="menu">
            <button className="icon-btn bordered" onClick={() => setMenu(!menu)} title="Mais opções">
              <span className="kebab">
                <i />
                <i />
                <i />
              </span>
            </button>
            {menu && (
              <>
                <div className="menu-backdrop" onClick={() => setMenu(false)} />
                <div className="menu-pop">
                  {report && (
                    <>
                      <a href={api.reportUrl(runId, "md")} target="_blank" rel="noreferrer" onClick={() => setMenu(false)}>
                        <Icon name="file" /> Baixar relatório (Markdown)
                      </a>
                      <a href={api.reportUrl(runId, "json")} target="_blank" rel="noreferrer" onClick={() => setMenu(false)}>
                        <Icon name="file" /> Baixar dados (JSON)
                      </a>
                    </>
                  )}
                  <button onClick={duplicate}>
                    <Icon name="folder" /> Copiar para novo projeto
                  </button>
                  {onRename && (
                    <button onClick={() => (setMenu(false), onRename())}>
                      <Icon name="edit" /> Renomear
                    </button>
                  )}
                  {onDelete && isTerminal && (
                    <button className="menu-danger" onClick={() => (setMenu(false), onDelete())}>
                      <Icon name="trash" /> Excluir
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {detail.error && !playing && <div className="notice">{detail.error}</div>}
      {detail.parent_run_id && kind === "arena" && (
        <p className="hint">
          Nova tentativa de <Link href={`/runs/${detail.parent_run_id}`}>uma arena anterior</Link>.
        </p>
      )}

      {showResults && kind === "action_plan" ? (
        report.action_plan ? (
          <ActionPlanView
            plan={report.action_plan} report={report} runId={runId} team={teamOf(report.action_plan.candidate_id)} onEvidence={setEvidenceId}
            constraints={detail.snapshot.constraints}
            onDetail={(ask) => plan(report.action_plan!.candidate_id, ask)} busy={sending}
          />
        ) : (
          <div className="panel empty small-empty">
            <p className="muted">O plano de ação não foi produzido. {report.limitations.slice(-1)[0]}</p>
          </div>
        )
      ) : showResults ? (
        <>
          <div className="panel done-strip">
            <Stepper live={live} compact />
          </div>
          <Results
            report={report} detail={detail} events={events} onEvidence={setEvidenceId}
            next={report.proposals.length ? { feedback, setFeedback, onRefine: refine, onPlan: plan, busy: sending } : null}
          />
        </>
      ) : isTerminal && !playing && !report ? (
        <div className="panel empty small-empty">
          <p className="muted">A execução terminou sem relatório ({STATUS_LABEL[detail.status] ?? detail.status}).</p>
        </div>
      ) : (
        <LiveView live={live} paced={playing && isTerminal} />
      )}

      {evidenceId && (
        <>
          <div className="drawer-backdrop" onClick={() => setEvidenceId(null)} />
          <aside className="drawer">
            <div className="drawer-head">
              <div>
                <div className="eyebrow">Evidência</div>
                <strong className="mono">{evidenceId}</strong>
              </div>
              <button className="icon-btn" onClick={() => setEvidenceId(null)} title="Fechar">
                <Icon name="x" />
              </button>
            </div>
            {evidence ? (
              <>
                <dl className="kv">
                  <dt>Fonte</dt>
                  <dd>{sourceTitle(evidence.source_id)}</dd>
                  <dt>Local</dt>
                  <dd>{evidence.locator.page ? `página ${evidence.locator.page}` : evidence.locator.line_start ? `linhas ${evidence.locator.line_start}–${evidence.locator.line_end}` : (evidence.locator.section ?? "—")}</dd>
                </dl>
                <blockquote className="excerpt">{evidence.excerpt}</blockquote>
              </>
            ) : (
              <p className="muted">Trecho não encontrado no pacote de evidências.</p>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
