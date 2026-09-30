import type { components } from "./api-types";

// O formulario usa a variante -Output (todos os campos presentes; dinheiro como string). A API aceita esse formato
// como entrada: valores Decimal sao parseados a partir de string, evitando ponto flutuante binario.
export type ChallengeConfig = components["schemas"]["ChallengeConfig-Output"];
export type CandidateConfig = components["schemas"]["CandidateConfig-Output"];
export type Constraint = components["schemas"]["Constraint-Output"];
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
export type SourceCreateResponse = components["schemas"]["SourceCreateResponse"];
export type RunCreateResponse = components["schemas"]["RunCreateResponse"];

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

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
  catalog: () => fetch(`${API_BASE}/api/v1/catalog`).then((r) => handle<CatalogResponse>(r)),
  demoPrepare: () => fetch(`${API_BASE}/api/v1/demo/prepare`, { method: "POST" }).then((r) => handle<{ challenge: ChallengeConfig; documents: string[]; note: string }>(r)),
  uploadFile: (file: File, title?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (title) fd.append("title", title);
    return fetch(`${API_BASE}/api/v1/sources`, { method: "POST", body: fd }).then((r) => handle<SourceCreateResponse>(r));
  },
  uploadText: (title: string, text: string) =>
    fetch(`${API_BASE}/api/v1/sources/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, text }) }).then((r) =>
      handle<SourceCreateResponse>(r),
    ),
  createRun: (cfg: ChallengeConfig, idempotencyKey: string) =>
    fetch(`${API_BASE}/api/v1/runs`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(cfg) }).then((r) =>
      handle<RunCreateResponse>(r),
    ),
  listRuns: () => fetch(`${API_BASE}/api/v1/runs`, { cache: "no-store" }).then((r) => handle<RunSummary[]>(r)),
  run: (id: string) => fetch(`${API_BASE}/api/v1/runs/${id}`, { cache: "no-store" }).then((r) => handle<RunDetail>(r)),
  events: (id: string, after = 0) => fetch(`${API_BASE}/api/v1/runs/${id}/events/list?after=${after}`, { cache: "no-store" }).then((r) => handle<RunEventView[]>(r)),
  report: (id: string) => fetch(`${API_BASE}/api/v1/runs/${id}/report?format=json`, { cache: "no-store" }).then((r) => handle<Report>(r)),
  cancel: (id: string) => fetch(`${API_BASE}/api/v1/runs/${id}/cancel`, { method: "POST" }).then((r) => handle<{ status: string; changed: boolean }>(r)),
  retry: (id: string) => fetch(`${API_BASE}/api/v1/runs/${id}/retry`, { method: "POST" }).then((r) => handle<RunCreateResponse>(r)),
  reportUrl: (id: string, format: "json" | "md") => `${API_BASE}/api/v1/runs/${id}/report?format=${format}`,
  eventsUrl: (id: string, after = 0) => `${API_BASE}/api/v1/runs/${id}/events?after=${after}`,
};

export const TERMINAL = new Set(["completed", "partial", "failed", "cancelled", "interrupted"]);
