export function num(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "n/d";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function money(value: string | number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "n/d";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${n.toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 6 })} ${currency}`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR");
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  if (d < 30) return `há ${d} dia${d > 1 ? "s" : ""}`;
  return new Date(iso).toLocaleDateString("pt-BR");
}

export function elapsed(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  return `${(ms / 1000).toFixed(1)} s`;
}

export const STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  running: "Em execução",
  completed: "Concluída",
  partial: "Parcial",
  failed: "Falhou",
  cancelled: "Cancelada",
  interrupted: "Interrompida",
};

export const DECISION_LABEL: Record<string, string> = {
  ranked: "Ranqueada",
  tie: "Empate (co-liderança)",
  no_eligible_candidate: "Nenhum elegível",
  inconclusive: "Inconclusiva",
  not_evaluated: "Não avaliada",
};

export const ELIGIBILITY_LABEL: Record<string, string> = {
  eligible: "Elegível",
  ineligible: "Inelegível",
  pending: "Pendente",
};

export const CHECK_LABEL: Record<string, string> = { pass: "OK", fail: "Violada", unknown: "Sem prova" };
