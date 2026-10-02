import type { CatalogResponse, ChallengeConfig, JudgeConfig, Rubric, SourceCreateResponse } from "./api";

// Projetos vivem no navegador (localStorage): agrupam a configuracao em edicao, as fontes anexadas e as arenas
// (runs) disparadas a partir dela. Os runs e as fontes continuam no backend; aqui ficam so os IDs.
export type RunKind = "arena" | "refinement" | "action_plan";
export type RunMeta = { name?: string; kind?: RunKind; parent?: string };

export type Project = {
  id: string;
  config: ChallengeConfig;
  sources: SourceCreateResponse[];
  runIds: string[];
  runMeta?: Record<string, RunMeta>;
  createdAt: string;
  updatedAt: string;
};

// Nome exibido de uma execucao do projeto: nome dado pelo usuario ou padrao pelo tipo
// ("Arena 2", "Arena 2 · Repescagem 1", "Arena 2 · Plano de ação").
export function runLabel(p: Project, runId: string): string {
  const meta = p.runMeta?.[runId];
  if (meta?.name) return meta.name;
  const root = rootOf(p, runId);
  const arenas = p.runIds.filter((id) => (p.runMeta?.[id]?.kind ?? "arena") === "arena");
  const n = arenas.indexOf(root) + 1 || p.runIds.indexOf(root) + 1;
  const base = p.runMeta?.[root]?.name ?? `Arena ${n}`;
  if (root === runId) return base;
  if (meta?.kind === "action_plan") {
    const v = descendants(p, root).filter((id) => p.runMeta?.[id]?.kind === "action_plan").indexOf(runId) + 1;
    return `${base} · Plano de ação${v > 1 ? ` v${v}` : ""}`;
  }
  const round = descendants(p, root).filter((id) => p.runMeta?.[id]?.kind === "refinement").indexOf(runId) + 1;
  return `${base} · Repescagem ${round}`;
}

export function rootOf(p: Project, runId: string): string {
  let cur = runId;
  const seen = new Set<string>();
  while (p.runMeta?.[cur]?.parent && p.runIds.includes(p.runMeta[cur].parent!) && !seen.has(cur)) {
    seen.add(cur);
    cur = p.runMeta[cur].parent!;
  }
  return cur;
}

export function descendants(p: Project, root: string): string[] {
  return p.runIds.filter((id) => id !== root && rootOf(p, id) === root);
}

const KEY = "agentathon:projects";

export const PERSONA_COLOR: Record<string, string> = { default: "#2952e3", technical: "#0891b2", business: "#16a34a", ux: "#db2777", custom: "#7c3aed" };

// Juiz a partir de uma persona do catalogo (copia a rubrica para poder editar os pesos livremente).
export function judgeFromPersona(catalog: CatalogResponse, persona: string, taken: string[] = []): JudgeConfig {
  const p = catalog.judge_personas.find((x) => x.persona === persona);
  let name = p?.name ?? "Juiz personalizado";
  for (let i = 2; taken.some((t) => t.trim().toLowerCase() === name.toLowerCase()); i++) name = `${p?.name ?? "Juiz personalizado"} ${i}`;
  const rubric: Rubric = p
    ? (JSON.parse(JSON.stringify(p.rubric)) as Rubric)
    : { criteria: [{ criterion_id: "qualidade_geral", name: "Qualidade geral", description: "", weight: "100", computed_by: "judge" }], min_score_threshold: null };
  return {
    judge_id: null, name, persona: (p ? persona : "custom") as JudgeConfig["persona"], instructions: p?.instructions ?? "", weight: "1", rubric,
    provider: null, model_option: null, max_output_tokens: 3000,
  };
}

// Projetos antigos tinham um unico juiz usando a rubrica do desafio: vira o juiz "Padrao" do painel.
export function withJudges(cfg: ChallengeConfig, catalog: CatalogResponse): ChallengeConfig {
  if (cfg.judges && cfg.judges.length) return cfg;
  const padrao = judgeFromPersona(catalog, "default");
  return { ...cfg, judge: null, judges: [{ ...padrao, rubric: cfg.rubric ?? padrao.rubric }] };
}

export function emptyConfig(catalog: CatalogResponse | null): ChallengeConfig {
  return {
    title: "",
    objective: "",
    context: "",
    source_ids: [],
    constraints: [],
    rubric: (catalog?.default_rubric as ChallengeConfig["rubric"]) ?? { criteria: [] },
    budget: { currency: "USD", total_cap: "1.00", strict: true, common_share_pct: "30", max_total_calls: 32, max_concurrent_calls: 2, run_deadline_s: 300, call_timeout_s: 60, max_attempts_per_call: 2 },
    mode: "mock",
    config_mode: "auto",
    candidate_count: 2,
    candidates: null,
    judge: null,
    judges: catalog ? [judgeFromPersona(catalog, "default")] : null,
    critique_rounds: 1,
    seed: null,
    mock_scenario: "default",
    tags: [],
    refinement: null,
    action_plan: null,
    real_provider: "neuralake",
  };
}

export function projectName(p: Project): string {
  return p.config.title?.trim() || "Projeto sem título";
}

export function loadProjects(): Project[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Project[]) : [];
  } catch {
    return [];
  }
}

function saveAll(list: Project[]): void {
  window.localStorage.setItem(KEY, JSON.stringify(list));
}

export function getProject(id: string): Project | null {
  return loadProjects().find((p) => p.id === id) ?? null;
}

export function saveProject(p: Project): Project {
  const next = { ...p, updatedAt: new Date().toISOString() };
  const list = loadProjects();
  const i = list.findIndex((x) => x.id === p.id);
  if (i >= 0) list[i] = next;
  else list.push(next);
  saveAll(list);
  return next;
}

export function createProject(config: ChallengeConfig, sources: SourceCreateResponse[] = []): Project {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().slice(0, 8) : String(Date.now());
  const now = new Date().toISOString();
  return saveProject({ id, config, sources, runIds: [], createdAt: now, updatedAt: now });
}

export function deleteProject(id: string): void {
  saveAll(loadProjects().filter((p) => p.id !== id));
}
