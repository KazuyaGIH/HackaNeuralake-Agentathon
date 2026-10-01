import type { RunDetail, RunEventView } from "@/lib/api";

// Estado "ao vivo" derivado dos eventos reais do run (mesma fonte para execucao em andamento e para o replay).

export const STAGES = [
  { key: "evidence", label: "Evidências", running: "Lendo os documentos" },
  { key: "plan", label: "Planejamento", running: "Equipes planejando" },
  { key: "delegate", label: "Ajudantes", running: "Ajudantes trabalhando" },
  { key: "propose", label: "Propostas", running: "Escrevendo propostas" },
  { key: "critique", label: "Críticas", running: "Equipes se criticando" },
  { key: "revise", label: "Revisão", running: "Revisando propostas" },
  { key: "verify", label: "Regras", running: "Conferindo as regras" },
  { key: "judge", label: "Juízes", running: "Juízes avaliando" },
  { key: "result", label: "Resultado", running: "Calculando o ranking" },
  { key: "action", label: "Plano de ação", running: "Montando o plano de ação" },
] as const;

export type RunKindLive = "arena" | "refinement" | "action_plan";

// Etapas exibidas por tipo de execucao (rodadas derivadas nao repetem as etapas iniciais).
export const KIND_STAGES: Record<RunKindLive, string[]> = {
  arena: ["evidence", "plan", "delegate", "propose", "critique", "revise", "verify", "judge", "result"],
  refinement: ["revise", "verify", "judge", "result"],
  action_plan: ["action", "result"],
};

export function kindOf(detail: RunDetail): RunKindLive {
  if (detail.snapshot.action_plan) return "action_plan";
  if (detail.snapshot.refinement) return "refinement";
  return "arena";
}

export type StageKey = (typeof STAGES)[number]["key"];
export type StageState = "pending" | "active" | "done" | "fail" | "skipped";

const STAGE_INDEX: Record<string, number> = Object.fromEntries(STAGES.map((s, i) => [s.key, i]));

// Eventos que so movem contadores (nao entram no feed nem no ritmo do replay).
export const SILENT = new Set(["budget.updated", "call.finished", "critique.order", "run.queued"]);

function stageOf(e: RunEventView, kind: RunKindLive): StageKey | null {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "run.started":
      return kind === "arena" ? "evidence" : kind === "refinement" ? "revise" : "action";
    case "evidence.ready":
      if (p.inherited) return null;
      return p.frozen ? "delegate" : "evidence";
    case "action_plan.started":
    case "action_plan.ready":
    case "action_plan.failed":
      return "action";
    case "plan.ready":
      return "plan";
    case "task.started":
    case "task.completed":
      return "delegate";
    case "proposal.ready":
    case "proposal.failed":
      return Number(p.version) >= 2 ? "revise" : "propose";
    case "critique.order":
    case "critique.ready":
      return "critique";
    case "verification.ready":
      return "verify";
    case "evaluation.ready":
    case "evaluation.failed":
      return "judge";
    case "report.ready":
    case "run.finished":
    case "run.failed":
    case "run.cancelled":
    case "run.interrupted":
      return "result";
    default:
      return null;
  }
}

export type TeamLane = {
  id: string;
  name: string;
  color: string;
  model: string;
  secondary: string | null;
  activity: string;
  detail: string | null;
  tier: "main" | "secondary" | "none" | null;
  working: boolean;
  spent: number | null;
  cap: number | null;
  proposals: number;
  eligibility: string | null;
};

export type FeedItem = { seq: number; ts: string; text: string; tone: "info" | "ok" | "warn" | "bad"; color?: string };

export type LiveState = {
  stages: Record<StageKey, StageState>;
  current: StageKey;
  lanes: TeamLane[];
  feed: FeedItem[];
  spent: number;
  cap: number | null;
  calls: number;
  callsCap: number;
  finished: boolean;
  kind: RunKindLive;
};

const TEAM_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea"];

// Inicial do avatar: ignora o prefixo "Equipe" para nao repetir a mesma letra em todas.
export function initial(name: string): string {
  return (name.replace(/^equipe\s+/i, "").match(/[\p{L}\p{N}]/u)?.[0] ?? "?").toUpperCase();
}

export function deriveLive(detail: RunDetail, events: RunEventView[], complete = false): LiveState {
  const cands = detail.snapshot.candidates ?? [];
  const noCritique = (detail.snapshot.critique_rounds ?? 1) === 0;
  const name = (id: unknown) => cands.find((c) => c.candidate_id === id)?.name ?? String(id);
  const colorOf = (id: unknown) => {
    const i = cands.findIndex((c) => c.candidate_id === id);
    return cands[i]?.color ?? TEAM_COLORS[Math.max(0, i) % TEAM_COLORS.length];
  };

  const kind = kindOf(detail);
  const refining = new Set((detail.snapshot.refinement?.feedback ?? []).map((f) => f.candidate_id));
  const planner = detail.snapshot.action_plan?.candidate_id ?? null;
  // Plano: so a equipe que monta o plano. Repescagem: so as equipes que seguem na disputa.
  const visibleCands = planner ? cands.filter((c) => c.candidate_id === planner) : kind === "refinement" ? cands.filter((c) => refining.has(c.candidate_id ?? "")) : cands;
  const lanes: TeamLane[] = visibleCands.map((c, i) => ({
    id: c.candidate_id ?? String(i), name: c.name, color: c.color ?? TEAM_COLORS[i % TEAM_COLORS.length], model: c.model_option,
    secondary: c.secondary_model_option ?? null, activity: "Aguardando o início", detail: null, tier: null, working: false,
    spent: null, cap: null, proposals: 0, eligibility: null,
  }));
  const lane = (id: unknown) => lanes.find((l) => l.id === id);
  const feed: FeedItem[] = [];
  // Progresso medido na ordem das etapas exibidas para este tipo de execucao.
  const order = KIND_STAGES[kind];
  const pos = (key: string) => order.indexOf(key);
  let reachedPos = -1;
  let failedStage: number | null = null;
  let spent = 0;
  const cap: number | null = detail.snapshot.budget.total_cap ? Number(detail.snapshot.budget.total_cap) : null;
  let calls = 0;
  let callsCap = detail.snapshot.budget.max_total_calls;
  let finished = false;
  const push = (e: RunEventView, text: string, tone: FeedItem["tone"] = "info", color?: string) => feed.push({ seq: e.seq, ts: e.ts, text, tone, color });

  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    const st = stageOf(e, kind);
    if (st && pos(st) >= 0) reachedPos = Math.max(reachedPos, pos(st));
    const l = lane(p.candidate_id);
    switch (e.type) {
      case "run.started":
        if (kind === "refinement") {
          push(e, `Repescagem: ${refining.size} equipe${refining.size > 1 ? "s seguem" : " segue"} na disputa com o seu feedback`);
          lanes.forEach((x) => Object.assign(x, { activity: "Lendo o seu feedback", working: true }));
        } else if (kind === "action_plan") {
          push(e, `${name(planner)} vai transformar a proposta em plano de ação`);
          lanes.forEach((x) => Object.assign(x, { activity: "Revisando a proposta e a avaliação", working: true }));
        } else {
          push(e, `Arena iniciada com ${cands.length} equipes`);
          lanes.forEach((x) => Object.assign(x, { activity: "Estudando o desafio", working: true }));
        }
        break;
      case "action_plan.started":
        if (l) Object.assign(l, { activity: Number(p.version) > 1 ? `Detalhando o plano (versão ${p.version})` : "Montando fases, tarefas e metas", tier: "main", detail: l.model, working: true });
        if (Number(p.version) > 1) push(e, `${name(p.candidate_id)} está detalhando o plano a seu pedido`, "info", colorOf(p.candidate_id));
        break;
      case "action_plan.ready":
        if (l) Object.assign(l, { activity: `Plano de ação pronto${Number(p.version) > 1 ? ` (versão ${p.version})` : ""}`, detail: String(p.title ?? ""), tier: null, working: false });
        push(e, `Plano de ação${Number(p.version) > 1 ? ` v${p.version}` : ""} pronto: ${p.phases} fase(s)`, "ok", colorOf(p.candidate_id));
        break;
      case "action_plan.failed":
        failedStage = STAGE_INDEX.action;
        if (l) Object.assign(l, { activity: "Não conseguiu montar o plano", working: false });
        push(e, `Plano de ação não produzido: ${p.reason}`, "bad");
        break;
      case "evidence.ready":
        if (p.frozen) push(e, `Pacote final de evidências congelado (${p.items} trechos${Number(p.derived) ? `, ${p.derived} cálculos` : ""})`, "ok");
        else push(e, `${p.items} trechos de evidência extraídos de ${p.sources} documento(s)`, "ok");
        break;
      case "plan.ready": {
        const n = ((p.accepted as unknown[]) ?? []).length;
        const rej = ((p.rejected as unknown[]) ?? []).length;
        if (l) Object.assign(l, { activity: n ? `Planejou ${n} tarefa${n > 1 ? "s" : ""} para os ajudantes` : "Decidiu trabalhar sem ajudantes", detail: null, working: true });
        push(e, `${name(p.candidate_id)} planejou ${n} tarefa${n === 1 ? "" : "s"}${rej ? ` (${rej} recusada${rej > 1 ? "s" : ""} pelas regras)` : ""}`, rej ? "warn" : "info", colorOf(p.candidate_id));
        break;
      }
      case "task.started":
        if (l) {
          const research = p.kind === "document_research";
          Object.assign(l, {
            activity: research ? "Pesquisando nos documentos" : "Fazendo um cálculo", working: true,
            tier: (p.model_tier as TeamLane["tier"]) ?? null, detail: research ? String(p.model_option ?? "") : "sem IA",
          });
        }
        break;
      case "task.completed": {
        const research = p.kind === "document_research";
        const eco = p.model_tier === "secondary";
        if (l) Object.assign(l, { activity: research ? "Pesquisa concluída" : "Cálculo concluído", working: true, tier: null, detail: null });
        push(e, `${name(p.candidate_id)}: ${research ? "pesquisa" : "cálculo"} ${p.status === "completed" ? "concluído" : "não concluído"}${eco ? " no modelo econômico" : ""}`, p.status === "completed" ? "info" : "warn", colorOf(p.candidate_id));
        break;
      }
      case "proposal.ready": {
        const v = Number(p.version);
        const fb = Boolean(p.from_feedback);
        if (l) Object.assign(l, { activity: fb ? "Revisou com o seu feedback" : v >= 2 ? "Revisou a proposta após a crítica" : "Entregou a primeira proposta", detail: String(p.title ?? ""), tier: null, working: true, proposals: v });
        push(e, `${name(p.candidate_id)} ${v >= 2 ? "revisou" : "entregou"} a proposta${v >= 2 ? ` (versão ${v})` : ""}${fb ? " com o seu feedback" : ""}`, "ok", colorOf(p.candidate_id));
        break;
      }
      case "proposal.failed":
        if (l) Object.assign(l, { activity: "Não conseguiu entregar a proposta", working: false });
        push(e, `${name(p.candidate_id)} não entregou a proposta`, "bad", colorOf(p.candidate_id));
        break;
      case "critique.ready": {
        const a = lane(p.author_candidate_id);
        const t = lane(p.target_candidate_id);
        const n = Number(p.objections);
        if (a) Object.assign(a, { activity: `Criticou a proposta da ${name(p.target_candidate_id)}`, detail: `${n} objeç${n === 1 ? "ão" : "ões"}`, working: true });
        if (t && t !== a && !t.activity.startsWith("Criticou")) Object.assign(t, { activity: "Recebeu uma crítica", working: true });
        push(e, `${name(p.author_candidate_id)} criticou ${name(p.target_candidate_id)}: ${n} objeç${n === 1 ? "ão" : "ões"}`, "info", colorOf(p.author_candidate_id));
        break;
      }
      case "verification.ready": {
        const ok = p.eligibility === "eligible";
        if (l) Object.assign(l, { activity: ok ? "Cumpriu todas as regras" : p.eligibility === "ineligible" ? "Quebrou uma regra obrigatória" : "Regras sem prova suficiente", detail: null, eligibility: String(p.eligibility), working: false });
        push(e, `${name(p.candidate_id)}: ${ok ? "cumpre as regras" : p.eligibility === "ineligible" ? "desclassificada por regra" : "regras sem prova"}`, ok ? "ok" : p.eligibility === "ineligible" ? "bad" : "warn", colorOf(p.candidate_id));
        break;
      }
      case "evaluation.ready": {
        const n = ((p.judges as unknown[]) ?? []).length || 1;
        lanes.forEach((x) => Object.assign(x, { activity: "Avaliada pelos juízes", detail: null, working: false }));
        push(e, `${n} juiz${n > 1 ? "es avaliaram" : " avaliou"} as propostas sem saber de quem eram`, "ok");
        break;
      }
      case "evaluation.failed":
        failedStage = STAGE_INDEX.judge;
        push(e, String(p.reason ?? "Falha na avaliação"), "bad");
        break;
      case "report.ready":
        push(e, p.winner_candidate_id ? `Vencedora: ${name(p.winner_candidate_id)}` : "Ranking calculado", "ok", p.winner_candidate_id ? colorOf(p.winner_candidate_id) : undefined);
        break;
      case "run.finished":
        finished = true;
        lanes.forEach((x) => (x.working = false));
        push(e, "Execução concluída", "ok");
        break;
      case "run.failed":
      case "run.cancelled":
      case "run.interrupted":
        finished = true;
        failedStage = failedStage ?? STAGE_INDEX[order[Math.max(0, reachedPos)]];
        lanes.forEach((x) => (x.working = false));
        push(e, e.type === "run.cancelled" ? "Execução cancelada" : e.type === "run.interrupted" ? "Execução interrompida" : `Execução falhou${p.error ? `: ${p.error}` : ""}`, "bad");
        break;
      case "budget.updated": {
        calls = Number(p.calls_used ?? calls);
        callsCap = Number(p.calls_cap ?? callsCap);
        const buckets = (p.buckets as { bucket_key: string; spent: string; cap: string | null }[]) ?? [];
        spent = buckets.reduce((s, b) => s + Number(b.spent || 0), 0);
        for (const b of buckets) {
          const x = b.bucket_key.startsWith("candidate:") ? lane(b.bucket_key.slice(10)) : undefined;
          if (x) Object.assign(x, { spent: Number(b.spent || 0), cap: b.cap ? Number(b.cap) : null });
        }
        break;
      }
    }
  }

  if (complete) {
    finished = true;
    reachedPos = order.length - 1;
  }
  const stages = {} as Record<StageKey, StageState>;
  STAGES.forEach((s, i) => {
    const k = pos(s.key);
    let state: StageState = k < 0 ? "skipped" : k < reachedPos ? "done" : k === reachedPos ? (finished ? "done" : "active") : "pending";
    if (kind === "arena" && noCritique && (s.key === "critique" || s.key === "revise")) state = "skipped";
    if (failedStage !== null && i === failedStage) state = "fail";
    stages[s.key] = state;
  });
  if (reachedPos < 0) stages[order[0] as StageKey] = "active";
  const current = (order[Math.max(0, Math.min(reachedPos, order.length - 1))] ?? "evidence") as StageKey;
  return { stages, current, lanes, feed, spent, cap, calls, callsCap, finished, kind };
}

export function progressPct(live: LiveState): number {
  const keys = STAGES.filter((s) => live.stages[s.key] !== "skipped");
  const done = keys.filter((s) => live.stages[s.key] === "done").length;
  const active = keys.some((s) => live.stages[s.key] === "active") ? 0.5 : 0;
  return Math.min(100, ((done + active) / keys.length) * 100);
}
