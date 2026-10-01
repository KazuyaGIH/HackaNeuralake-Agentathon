import type { Constraint } from "./api";

// Deixa textos gerados por agentes legiveis: tira o selo [SIMULADO] (ja exibido no cabecalho), troca chaves tecnicas
// de metricas (monthly_cost_brl) pelo nome da regra e formata valores (8000 BRL -> R$ 8.000).

function parseNum(raw: string): number {
  const s = raw.replace(/[.,]$/, "");
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) return Number(s.replace(/\./g, "").replace(",", "."));
  if (/^\d+,\d+$/.test(s)) return Number(s.replace(",", "."));
  return Number(s.replace(/,/g, ""));
}

export function fmtNumber(n: number): string {
  return n.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

export function fmtValue(v: string | number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : parseNum(String(v));
  if (Number.isNaN(n)) return `${v} ${unit ?? ""}`.trim();
  const u = (unit ?? "").trim();
  if (u.toUpperCase() === "BRL" || u === "R$") return `R$ ${fmtNumber(n)}`;
  if (u.toUpperCase() === "USD" || u === "US$") return `US$ ${fmtNumber(n)}`;
  return `${fmtNumber(n)} ${u}`.trim();
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
const upperFirst = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export type Humanizer = { text: (s: string | null | undefined) => string; label: (key: string) => string; value: typeof fmtValue };

export function makeHumanizer(constraints: Constraint[] = []): Humanizer {
  const labels = new Map<string, string>();
  for (const c of constraints) if (c.metric_key) labels.set(c.metric_key, c.description);
  const label = (key: string) => labels.get(key) ?? upperFirst(key.replace(/_/g, " "));

  const text = (s: string | null | undefined) => {
    let out = String(s ?? "").replace(/\s*\[SIMULADO\]\s*/gi, " ").trim();
    for (const [key, desc] of labels) {
      // "monthly_cost_brl 8000 BRL" / "monthly_cost_brl: <= 8000 BRL" -> "custo mensal...: R$ 8.000" / "...de até R$ 8.000"
      const withValue = new RegExp(`\\b${esc(key)}\\b\\s*(?:[:=]\\s*)?(<=|>=|≤|≥)?\\s*(\\d[\\d.,]*)\\s*(BRL|USD|R\\$|US\\$|[A-Za-zÀ-ÿ%]+)?`, "g");
      out = out.replace(withValue, (_m, op: string | undefined, num: string, unit: string | undefined) => {
        const rel = !op ? ":" : op === "<=" || op === "≤" ? " de até" : " de pelo menos";
        return `${lowerFirst(desc)}${rel} ${fmtValue(num, unit)}`;
      });
      out = out.replace(new RegExp(`\\b${esc(key)}\\b`, "g"), lowerFirst(desc));
    }
    out = out.replace(/(\d[\d.,]*)\s?(BRL|USD)\b/g, (_m, num: string, unit: string) => fmtValue(num, unit));
    out = out.replace(/(^|\s)<=\s*/g, "$1até ").replace(/(^|\s)>=\s*/g, "$1pelo menos ");
    return out.replace(/\s{2,}/g, " ");
  };

  return { text, label, value: fmtValue };
}
