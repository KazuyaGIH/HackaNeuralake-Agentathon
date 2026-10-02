import type { components } from "./api-types";

// O formulario usa a variante -Output (todos os campos presentes; dinheiro como string). A API aceita esse formato
// como entrada: valores Decimal sao parseados a partir de string, evitando ponto flutuante binario.
export type ChallengeConfig = components["schemas"]["ChallengeConfig-Output"];
export type CandidateConfig = components["schemas"]["CandidateConfig-Output"];
export type Constraint = components["schemas"]["Constraint-Output"];
export type JudgeConfig = components["schemas"]["JudgeConfig-Output"];
export type Rubric = components["schemas"]["Rubric-Output"];
export type JudgePersona = components["schemas"]["CatalogJudgePersona"];
export type CatalogResponse = Omit<components["schemas"]["CatalogResponse"], "limits" | "specialists" | "providers"> & {
  limits: Record<string, Record<string, number>>;
  specialists: { kind: string; label: string; description: string; uses_inference: boolean }[];
  providers: Record<string, { enabled: boolean; label: string; simulated: boolean; unavailable_reason?: string | null; notes?: string; base_url?: string }>;
};
export type RunDetail = components["schemas"]["RunDetail"];
export type RunSummary = components["schemas"]["RunSummary"];
export type RunEventView = components["schemas"]["RunEventView"];
export type Report = components["schemas"]["Report"];
export type Proposal = components["schemas"]["Proposal"];
export type ActionPlan = components["schemas"]["ActionPlan"];
export type SourceCreateResponse = components["schemas"]["SourceCreateResponse"];
export type RunCreateResponse = components["schemas"]["RunCreateResponse"];

// Aceita URL completa ou so o host; host sem dominio (nome interno do Render) vira o endereco publico .onrender.com.
const RAW_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").trim().replace(/\/$/, "");
const WITH_DOMAIN = /^https?:\/\//.test(RAW_BASE) || RAW_BASE.includes(".") || RAW_BASE.includes(":") ? RAW_BASE : `${RAW_BASE}.onrender.com`;
export const API_BASE = /^https?:\/\//.test(WITH_DOMAIN) ? WITH_DOMAIN : `https://${WITH_DOMAIN}`;

// Servidor no plano gratuito (Render) "dorme" sem uso: ao acordar, as primeiras chamadas falham por ate ~1 min.
// Todas as chamadas esperam o /health responder; quem quiser mostrar um aviso assina onServerWaiting.
let readyPromise: Promise<boolean> | null = null;
let waitingNow = false;
const waitListeners = new Set<(waiting: boolean) => void>();

function setWaiting(w: boolean) {
  waitingNow = w;
  waitListeners.forEach((f) => f(w));
}

export function onServerWaiting(fn: (waiting: boolean) => void): () => void {
  waitListeners.add(fn);
  fn(waitingNow);
  return () => void waitListeners.delete(fn);
}

async function waitForServer(maxMs = 150000): Promise<boolean> {
  const start = Date.now();
  let first = true;
  while (Date.now() - start < maxMs) {
    try {
      const r = await fetch(API_BASE + "/health", { cache: "no-store" });
      if (r.ok) {
        setWaiting(false);
        return true;
      }
    } catch {
      /* ainda acordando */
    }
    if (first) {
      first = false;
      setWaiting(true);
    }
    await new Promise((res) => setTimeout(res, 3000));
  }
  setWaiting(false);
  return false;
}

export function serverReady(): Promise<boolean> {
  if (!readyPromise) readyPromise = waitForServer().then((ok) => ((readyPromise = ok ? readyPromise : null), ok));
  return readyPromise;
}

const call: typeof fetch = (input, init) => serverReady().then(() => fetch(input, init));

export class ApiError extends Error {
  status: number;
  code?: string;
  hint?: string;
  constructor(status: number, message: string, code?: string, hint?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    const text = await res.text();
    return (text ? JSON.parse(text) : null) as T;
  }
  let message = `${res.status} ${res.statusText}`;
  let code: string | undefined;
  let hint: string | undefined;
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object" && "message" in d) {
      message = String(d.message);
      code = d.code;
      hint = d.hint;
    } else if (Array.isArray(d)) {
      message = d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).join(".")}: ${e.msg}`).join("; ");
      code = "validation_error";
    }
  } catch {
    /* corpo nao-JSON */
  }
  throw new ApiError(res.status, message, code, hint);
}

export const api = {
  catalog: () => call(`${API_BASE}/api/v1/catalog`).then((r) => handle<CatalogResponse>(r)),
  demoPrepare: () => call(`${API_BASE}/api/v1/demo/prepare`, { method: "POST" }).then((r) => handle<{ challenge: ChallengeConfig; documents: string[]; note: string }>(r)),
  uploadFile: (file: File, title?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (title) fd.append("title", title);
    return call(`${API_BASE}/api/v1/sources`, { method: "POST", body: fd }).then((r) => handle<SourceCreateResponse>(r));
  },
  uploadText: (title: string, text: string) =>
    call(`${API_BASE}/api/v1/sources/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, text }) }).then((r) =>
      handle<SourceCreateResponse>(r),
    ),
  createRun: (cfg: ChallengeConfig, idempotencyKey: string) =>
    call(`${API_BASE}/api/v1/runs`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(cfg) }).then((r) =>
      handle<RunCreateResponse>(r),
    ),
  listRuns: () => call(`${API_BASE}/api/v1/runs`, { cache: "no-store" }).then((r) => handle<RunSummary[]>(r)),
  run: (id: string) => call(`${API_BASE}/api/v1/runs/${id}`, { cache: "no-store" }).then((r) => handle<RunDetail>(r)),
  events: (id: string, after = 0) => call(`${API_BASE}/api/v1/runs/${id}/events/list?after=${after}`, { cache: "no-store" }).then((r) => handle<RunEventView[]>(r)),
  report: (id: string) => call(`${API_BASE}/api/v1/runs/${id}/report?format=json`, { cache: "no-store" }).then((r) => handle<Report>(r)),
  cancel: (id: string) => call(`${API_BASE}/api/v1/runs/${id}/cancel`, { method: "POST" }).then((r) => handle<{ status: string; changed: boolean }>(r)),
  retry: (id: string) => call(`${API_BASE}/api/v1/runs/${id}/retry`, { method: "POST" }).then((r) => handle<RunCreateResponse>(r)),
  refine: (id: string, feedback: { candidate_id: string; comment: string }[], generalComment: string) =>
    call(`${API_BASE}/api/v1/runs/${id}/refine`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ feedback, general_comment: generalComment }) }).then((r) =>
      handle<RunCreateResponse>(r),
    ),
  actionPlan: (id: string, candidateId: string | null, instructions: string) =>
    call(`${API_BASE}/api/v1/runs/${id}/action-plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_id: candidateId, instructions }) }).then((r) =>
      handle<RunCreateResponse>(r),
    ),
  deleteRun: (id: string) => call(`${API_BASE}/api/v1/runs/${id}`, { method: "DELETE" }).then((r) => (r.status === 404 ? null : handle<null>(r))),
  reportUrl: (id: string, format: "json" | "md") => `${API_BASE}/api/v1/runs/${id}/report?format=${format}`,
  eventsUrl: (id: string, after = 0) => `${API_BASE}/api/v1/runs/${id}/events?after=${after}`,
};

export const TERMINAL = new Set(["completed", "partial", "failed", "cancelled", "interrupted"]);
