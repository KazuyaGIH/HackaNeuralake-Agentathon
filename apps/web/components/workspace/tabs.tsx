"use client";

import { useState } from "react";
import { type CandidateConfig, type CatalogResponse, type ChallengeConfig, type Constraint, type JudgeConfig, type Rubric, type RunSummary, type SourceCreateResponse } from "@/lib/api";
import { DECISION_LABEL, STATUS_LABEL, ago } from "@/lib/format";
import { PERSONA_COLOR, judgeFromPersona } from "@/lib/projects";
import Icon, { type IconName } from "../Icon";

type Update = (patch: Partial<ChallengeConfig>) => void;
type Base = { cfg: ChallengeConfig; update: Update; catalog: CatalogResponse };

const STATUS_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "accent", queued: "info" };

export function weightSum(rubric: Rubric | null | undefined): number {
  return (rubric?.criteria ?? []).reduce((s, c) => s + Number(c.weight || 0), 0);
}

function panelOf(cfg: ChallengeConfig): JudgeConfig[] {
  return cfg.judges ?? [];
}

export function teamCount(cfg: ChallengeConfig): number {
  return cfg.config_mode === "manual" ? (cfg.candidates?.length ?? 0) : (cfg.candidate_count ?? 2);
}

// Pendencias que impedem iniciar a arena (o backend valida de novo; aqui e so para orientar).
export function blockers(cfg: ChallengeConfig, catalog: CatalogResponse | null): string[] {
  const out: string[] = [];
  if (cfg.objective.trim().length < 10) out.push("Descreva o que precisa ser decidido (aba Desafio).");
  const bad = panelOf(cfg).filter((j) => weightSum(j.rubric) !== 100);
  if (bad.length) out.push(`Os pesos dos critérios de ${bad.map((j) => j.name).join(", ")} precisam somar 100 (aba Juízes).`);
  if (!panelOf(cfg).length) out.push("Adicione pelo menos um juiz (aba Juízes).");
  if (panelOf(cfg).some((j) => j.rubric?.criteria.some((c) => c.computed_by === "server_efficiency")) && !cfg.budget.total_cap)
    out.push("O critério de eficiência exige um teto de gasto (aba Orçamento).");
  if (cfg.mode === "real" && catalog?.providers?.neuralake?.enabled !== true) out.push("O modo real está indisponível: falta a chave da NeuraLake no servidor.");
  return out;
}

function defaultCandidate(i: number, catalog: CatalogResponse, mode: string): CandidateConfig {
  const preset = catalog.presets[i % catalog.presets.length];
  const provider = mode === "mock" ? "mock" : "neuralake";
  return {
    candidate_id: null,
    name: `Equipe ${preset.label}`,
    preset: preset.preset as CandidateConfig["preset"],
    instructions: preset.instructions,
    provider: provider as CandidateConfig["provider"],
    model_option: preset.model_option_by_provider[provider] ?? "mock-default",
    secondary_model_option: preset.secondary_by_provider?.[provider] ?? null,
    secondary_for: ["research"],
    allowed_specialists: preset.allowed_specialists as CandidateConfig["allowed_specialists"],
    max_specialist_tasks: preset.max_specialist_tasks,
    max_output_tokens: 2000,
    quota_weight: "1",
    color: null,
  };
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "on" : ""} disabled={o.disabled} onClick={() => onChange(o.value)} type="button">
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      {label}
    </label>
  );
}

/* ---------------------------------------------------------------- Visao geral */

export function OverviewTab({ cfg, catalog, sources, runs, runNumber, go, onDelete }: Base & {
  sources: SourceCreateResponse[];
  runs: RunSummary[];
  runNumber: (id: string) => number;
  go: (tab: string) => void;
  onDelete: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const judges = panelOf(cfg);
  const judgesOk = judges.length > 0 && judges.every((j) => weightSum(j.rubric) === 100);
  const items: { icon: IconName; tab: string; label: string; value: string; ok: boolean | null }[] = [
    { icon: "edit", tab: "desafio", label: "Desafio", value: cfg.objective.trim().length >= 10 ? "Objetivo definido" : "Falta descrever o objetivo", ok: cfg.objective.trim().length >= 10 },
    { icon: "file", tab: "documentos", label: "Documentos", value: sources.length ? `${sources.length} anexado${sources.length > 1 ? "s" : ""}` : "Nenhum (opcional)", ok: sources.length ? true : null },
    { icon: "flag", tab: "regras", label: "Regras", value: cfg.constraints.length ? `${cfg.constraints.length} regra${cfg.constraints.length > 1 ? "s" : ""}` : "Nenhuma (opcional)", ok: cfg.constraints.length ? true : null },
    {
      icon: "star", tab: "juizes", label: "Juízes",
      value: judges.length ? `${judges.length} juiz${judges.length > 1 ? "es" : ""} · ${judges.map((j) => j.name).join(", ")}${judgesOk ? "" : " · pesos inválidos"}` : "Nenhum juiz",
      ok: judgesOk,
    },
    { icon: "users", tab: "equipes", label: "Equipes", value: `${teamCount(cfg)} equipes · ${cfg.config_mode === "auto" ? "automático" : "manual"}`, ok: true },
    {
      icon: "dollar", tab: "orcamento", label: "Orçamento e modo",
      value: `${cfg.budget.total_cap ? `até ${cfg.budget.total_cap} ${cfg.budget.currency}` : "sem teto"} · ${cfg.mode === "real" ? "real" : "simulado"}`, ok: true,
    },
  ];
  const sorted = [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div className="stack">
      <div className="panel hero">
        <div className="eyebrow">Objetivo</div>
        {cfg.objective ? <p className="hero-text">{cfg.objective}</p> : <p className="muted">Ainda não definido. <button className="link" onClick={() => go("desafio")}>Definir agora</button></p>}
        {cfg.context && <p className="muted small">{cfg.context}</p>}
      </div>

      <div className="panel">
        <h3 className="panel-title">Configuração</h3>
        <div className="checklist">
          {items.map((it) => (
            <button key={it.tab} className="check-item" onClick={() => go(it.tab)}>
              <span className={`check-dot ${it.ok === true ? "ok" : it.ok === false ? "bad" : ""}`}>{it.ok === false ? <Icon name="alert" size={14} /> : <Icon name={it.icon} size={14} />}</span>
              <span className="check-label">{it.label}</span>
              <span className="check-value">{it.value}</span>
              <Icon name="chevron" size={14} />
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Arenas recentes</h3>
        {sorted.length === 0 ? (
          <p className="muted">Nenhuma arena ainda. Quando a configuração estiver pronta, clique em <strong>Iniciar arena</strong>.</p>
        ) : (
          <div className="checklist">
            {sorted.slice(0, 5).map((r) => (
              <button key={r.run_id} className="check-item" onClick={() => go(`arena:${r.run_id}`)}>
                <span className="check-dot">
                  <Icon name="zap" size={14} />
                </span>
                <span className="check-label">Arena {runNumber(r.run_id)}</span>
                <span className="check-value">
                  <span className={`badge ${STATUS_CLASS[r.status] ?? "info"}`}>{STATUS_LABEL[r.status] ?? r.status}</span> {DECISION_LABEL[r.decision_status] ?? r.decision_status} · {ago(r.created_at)}
                </span>
                <Icon name="chevron" size={14} />
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="panel danger-zone">
        <div>
          <strong>Excluir projeto</strong>
          <div className="hint">Remove o projeto desta lista. As arenas já executadas continuam no Histórico.</div>
        </div>
        {confirmDelete ? (
          <div className="row">
            <button onClick={() => setConfirmDelete(false)}>Cancelar</button>
            <button className="danger solid" onClick={onDelete}>
              Confirmar exclusão
            </button>
          </div>
        ) : (
          <button className="danger" onClick={() => setConfirmDelete(true)}>
            <Icon name="trash" /> Excluir
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Desafio */

export function ChallengeTab({ cfg, update, onLoadDemo, busy }: Base & { onLoadDemo: () => void; busy: boolean }) {
  return (
    <div className="stack">
      <div className="panel">
        <div className="field">
          <label>Nome do projeto</label>
          <input value={cfg.title ?? ""} onChange={(e) => update({ title: e.target.value })} placeholder="Ex.: Arquitetura do chatbot interno" />
        </div>
        <div className="field">
          <label>O que precisa ser decidido?</label>
          <textarea rows={4} value={cfg.objective} onChange={(e) => update({ objective: e.target.value })} placeholder="Descreva a decisão que as equipes de agentes vão disputar." />
          <div className="hint">Mínimo de 10 caracteres.</div>
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Contexto (opcional)</label>
          <textarea rows={3} value={cfg.context ?? ""} onChange={(e) => update({ context: e.target.value })} placeholder="Informações de fundo que ajudam as equipes." />
        </div>
      </div>
      <div className="panel subtle row spread">
        <div>
          <strong>Quer ver um exemplo?</strong>
          <div className="hint">Preenche tudo com o caso pronto (empresa fictícia escolhendo um chatbot). Substitui a configuração atual.</div>
        </div>
        <button onClick={onLoadDemo} disabled={busy}>
          Usar exemplo
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Documentos */

export function DocumentsTab({ catalog, sources, busy, onUpload, onPaste, onRemove }: Base & {
  sources: SourceCreateResponse[];
  busy: boolean;
  onUpload: (files: FileList | null) => void;
  onPaste: (title: string, text: string) => Promise<boolean>;
  onRemove: (id: string) => void;
}) {
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [drag, setDrag] = useState(false);
  const lim = catalog.limits?.sources ?? {};

  return (
    <div className="stack">
      <div className="panel">
        <label
          className={`dropzone ${drag ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            onUpload(e.dataTransfer.files);
          }}
        >
          <input type="file" multiple hidden accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf" onChange={(e) => onUpload(e.target.files)} disabled={busy} />
          <Icon name="upload" size={22} />
          <strong>{busy ? "Enviando…" : "Arraste arquivos ou clique para escolher"}</strong>
          <span className="hint">
            TXT, Markdown ou PDF com texto · até {lim.max ?? 5} arquivos de {lim.max_upload_mb ?? 10} MB
          </span>
        </label>

        <div className="file-list">
          {sources.length === 0 && <p className="muted small">Nenhum documento. Sem documentos, as equipes trabalham só com hipóteses.</p>}
          {sources.map((s) => (
            <div key={s.source_id} className={`file-row ${s.extraction_status !== "ok" ? "bad" : ""}`} title={s.warnings.join("; ")}>
              <Icon name="file" />
              <span className="file-name">{s.title}</span>
              <span className="hint">{s.extraction_status !== "ok" ? s.extraction_status : s.chars ? `${s.chars.toLocaleString("pt-BR")} caracteres` : ""}</span>
              <button className="icon-btn" onClick={() => onRemove(s.source_id)} title="Remover">
                <Icon name="x" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <details className="panel collapsible">
        <summary>Colar texto em vez de enviar arquivo</summary>
        <div className="field" style={{ marginTop: 12 }}>
          <input placeholder="Título" value={pasteTitle} onChange={(e) => setPasteTitle(e.target.value)} />
        </div>
        <div className="field">
          <textarea rows={5} placeholder="Cole aqui o conteúdo" value={pasteText} onChange={(e) => setPasteText(e.target.value)} />
        </div>
        <button
          disabled={busy || !pasteText.trim()}
          onClick={async () => {
            if (await onPaste(pasteTitle, pasteText)) {
              setPasteText("");
              setPasteTitle("");
            }
          }}
        >
          Adicionar texto
        </button>
      </details>
    </div>
  );
}

/* ---------------------------------------------------------------- Regras */

export function RulesTab({ cfg, update }: Base) {
  const setConstraint = (i: number, patch: Partial<Constraint>) => update({ constraints: cfg.constraints.map((c, idx) => (idx === i ? { ...c, ...patch } : c)) });
  const add = () =>
    update({ constraints: [...cfg.constraints, { constraint_id: `regra_${cfg.constraints.length + 1}`, description: "", kind: "numeric_max", metric_key: "", limit: "0", unit: "", mandatory: true }] });

  return (
    <div className="stack">
      {cfg.constraints.length === 0 && (
        <div className="panel empty small-empty">
          <p className="muted">Nenhuma regra. Regras são limites que as propostas precisam respeitar, como “custo mensal de no máximo R$ 8.000”.</p>
        </div>
      )}
      {cfg.constraints.map((c, i) => (
        <div key={i} className="panel rule">
          <div className="row spread">
            <input className="rule-desc" value={c.description} onChange={(e) => setConstraint(i, { description: e.target.value })} placeholder="Descreva a regra" />
            <button className="icon-btn" title="Remover" onClick={() => update({ constraints: cfg.constraints.filter((_, idx) => idx !== i) })}>
              <Icon name="trash" />
            </button>
          </div>
          <div className="inline" style={{ marginTop: 10 }}>
            <div>
              <label>Tipo</label>
              <select value={c.kind} onChange={(e) => setConstraint(i, { kind: e.target.value as Constraint["kind"] })}>
                <option value="numeric_max">Valor máximo</option>
                <option value="numeric_min">Valor mínimo</option>
                <option value="qualitative">Qualitativa</option>
              </select>
            </div>
            {c.kind !== "qualitative" && (
              <>
                <div>
                  <label>Métrica</label>
                  <input value={c.metric_key ?? ""} onChange={(e) => setConstraint(i, { metric_key: e.target.value })} placeholder="custo_mensal" />
                </div>
                <div>
                  <label>Limite</label>
                  <input value={c.limit ?? ""} onChange={(e) => setConstraint(i, { limit: e.target.value })} />
                </div>
                <div>
                  <label>Unidade</label>
                  <input value={c.unit ?? ""} onChange={(e) => setConstraint(i, { unit: e.target.value })} placeholder="BRL" />
                </div>
              </>
            )}
            <div>
              <label>Identificador</label>
              <input value={c.constraint_id} onChange={(e) => setConstraint(i, { constraint_id: e.target.value })} />
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <Toggle checked={c.mandatory} onChange={(v) => setConstraint(i, { mandatory: v })} label="Obrigatória (quem quebrar é desclassificado)" />
          </div>
          {c.kind === "qualitative" && c.mandatory && <div className="hint">Regras qualitativas não têm verificação automática; obrigatórias ficam sempre “sem prova”.</div>}
        </div>
      ))}
      <button className="add-btn" onClick={add}>
        <Icon name="plus" /> Nova regra
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------- Juizes */

function newCriterionId(rubric: Rubric): string {
  const used = new Set(rubric.criteria.map((c) => c.criterion_id));
  let n = rubric.criteria.length + 1;
  while (used.has(`criterio_${n}`)) n++;
  return `criterio_${n}`;
}

function JudgeCard({ judge, index, open, onToggle, onChange, onRemove, canRemove, share, catalog, mode }: {
  judge: JudgeConfig;
  index: number;
  open: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<JudgeConfig>) => void;
  onRemove: () => void;
  canRemove: boolean;
  share: number;
  catalog: CatalogResponse;
  mode: string;
}) {
  const rubric = judge.rubric ?? { criteria: [], min_score_threshold: null };
  const sum = weightSum(rubric);
  const color = PERSONA_COLOR[judge.persona] ?? PERSONA_COLOR.custom;
  const persona = catalog.judge_personas.find((p) => p.persona === judge.persona);
  const options = catalog.model_options.filter((m) => m.enabled && (mode === "mock" ? m.provider === "mock" : m.provider !== "mock"));
  const setCriteria = (criteria: Rubric["criteria"]) => onChange({ rubric: { ...rubric, criteria } });
  const setCriterion = (i: number, patch: Partial<Rubric["criteria"][number]>) => setCriteria(rubric.criteria.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  return (
    <div className={`panel judge ${open ? "open" : ""}`} style={{ ["--judge" as string]: color }}>
      <div className="judge-head">
        <button className="judge-toggle" onClick={onToggle} title={open ? "Recolher" : "Editar"}>
          <span className="judge-avatar">{judge.name.match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() ?? index + 1}</span>
          <span className="judge-title">
            <strong>{judge.name}</strong>
            <span className="hint">
              {rubric.criteria.length} critérios{sum !== 100 && <span className="text-bad"> · pesos somam {sum}</span>}
            </span>
          </span>
        </button>
        <div className="judge-weight" title="Quanto a nota deste juiz pesa no resultado final">
          <span className="muted small">Peso</span>
          <input value={String(judge.weight)} onChange={(e) => onChange({ weight: e.target.value })} />
          <span className="badge info">{share.toFixed(0)}%</span>
        </div>
        <button className="icon-btn" onClick={onToggle} title={open ? "Recolher" : "Editar"}>
          <span className={`chev ${open ? "up" : ""}`}>
            <Icon name="chevron" />
          </span>
        </button>
        <button className="icon-btn" title="Remover juiz" disabled={!canRemove} onClick={onRemove}>
          <Icon name="trash" />
        </button>
      </div>

      {open && (
        <div className="judge-body">
          <div className="inline">
            <div>
              <label>Nome</label>
              <input value={judge.name} onChange={(e) => onChange({ name: e.target.value })} />
            </div>
            <div>
              <label>Modelo</label>
              <select
                value={judge.provider && judge.model_option ? `${judge.provider}|${judge.model_option}` : ""}
                onChange={(e) => {
                  if (!e.target.value) return onChange({ provider: null, model_option: null });
                  const [provider, option] = e.target.value.split("|");
                  onChange({ provider: provider as JudgeConfig["provider"], model_option: option });
                }}
              >
                <option value="">Padrão do modo</option>
                {options.map((m) => (
                  <option key={`${m.provider}|${m.option}`} value={`${m.provider}|${m.option}`}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="field" style={{ marginTop: 12 }}>
            <label>Como este juiz avalia</label>
            <textarea rows={3} value={judge.instructions} placeholder="Sem perspectiva especial: avaliação geral pela rubrica." onChange={(e) => onChange({ instructions: e.target.value })} />
          </div>

          <div className="row spread" style={{ marginBottom: 8 }}>
            <label style={{ margin: 0 }}>Critérios e pesos</label>
            <span className="row">
              <span className={`badge ${sum === 100 ? "ok" : "bad"}`}>Soma: {sum} / 100</span>
              {persona && (
                <button className="small" onClick={() => onChange({ rubric: JSON.parse(JSON.stringify(persona.rubric)) as Rubric })}>
                  Restaurar padrão da persona
                </button>
              )}
            </span>
          </div>
          <div className="criteria">
            {rubric.criteria.map((c, i) => (
              <div key={i} className="criterion">
                <div className="criterion-text">
                  <input className="plain strong" value={c.name} onChange={(e) => setCriterion(i, { name: e.target.value })} />
                  <input className="plain hint-input" value={c.description} placeholder="Descrição (opcional)" onChange={(e) => setCriterion(i, { description: e.target.value })} />
                  {c.computed_by === "server_efficiency" && <span className="badge info">calculado pelo sistema</span>}
                </div>
                <input className="weight" value={String(c.weight)} onChange={(e) => setCriterion(i, { weight: e.target.value })} />
                <button className="icon-btn" title="Remover critério" disabled={rubric.criteria.length <= 1} onClick={() => setCriteria(rubric.criteria.filter((_, idx) => idx !== i))}>
                  <Icon name="trash" />
                </button>
              </div>
            ))}
          </div>
          <button className="add-btn" onClick={() => setCriteria([...rubric.criteria, { criterion_id: newCriterionId(rubric), name: "Novo critério", description: "", weight: "0", computed_by: "judge" }])}>
            <Icon name="plus" /> Novo critério
          </button>
        </div>
      )}
    </div>
  );
}

export function JudgesTab({ cfg, update, catalog }: Base) {
  const judges = panelOf(cfg);
  const [open, setOpen] = useState<number | null>(judges.length === 1 ? 0 : null);
  const max = catalog.limits?.judges?.max ?? 6;
  const totalWeight = judges.reduce((s, j) => s + (Number(j.weight) || 0), 0) || 1;
  const setJudges = (next: JudgeConfig[]) => update({ judges: next, judge: null });
  const add = (persona: string) => {
    setJudges([...judges, judgeFromPersona(catalog, persona, judges.map((j) => j.name))]);
    setOpen(judges.length);
  };
  const present = new Set(judges.map((j) => j.persona));

  return (
    <div className="stack">
      <div className="panel">
        <p style={{ marginTop: 0 }}>
          Cada juiz dá a sua nota (0 a 100) pelos próprios critérios, sem saber qual equipe escreveu cada proposta. A <strong>nota final</strong> é a média ponderada pelo peso de
          cada juiz.
        </p>
        <div className="share-bar">
          {judges.map((j, i) => (
            <div key={i} style={{ flex: Number(j.weight) || 0, background: PERSONA_COLOR[j.persona] ?? PERSONA_COLOR.custom }} title={`${j.name}: ${(((Number(j.weight) || 0) / totalWeight) * 100).toFixed(0)}%`} />
          ))}
        </div>
        <div className="share-legend">
          {judges.map((j, i) => (
            <span key={i}>
              <span className="dot" style={{ background: PERSONA_COLOR[j.persona] ?? PERSONA_COLOR.custom }} /> {j.name} {(((Number(j.weight) || 0) / totalWeight) * 100).toFixed(0)}%
            </span>
          ))}
        </div>
      </div>

      {judges.map((j, i) => (
        <JudgeCard
          key={i} judge={j} index={i} open={open === i} onToggle={() => setOpen(open === i ? null : i)} catalog={catalog} mode={cfg.mode}
          share={((Number(j.weight) || 0) / totalWeight) * 100} canRemove={judges.length > 1}
          onChange={(patch) => setJudges(judges.map((x, idx) => (idx === i ? { ...x, ...patch } : x)))}
          onRemove={() => {
            setJudges(judges.filter((_, idx) => idx !== i));
            setOpen(null);
          }}
        />
      ))}

      {judges.length < max && (
        <div className="panel subtle">
          <label>Adicionar juiz</label>
          <div className="persona-grid">
            {catalog.judge_personas
              .filter((p) => !present.has(p.persona as JudgeConfig["persona"]))
              .map((p) => (
                <button key={p.persona} className="persona-btn" style={{ ["--judge" as string]: PERSONA_COLOR[p.persona] }} onClick={() => add(p.persona)}>
                  <span className="persona-dot" />
                  <span>
                    <strong>{p.name}</strong>
                    <span className="hint">{p.description}</span>
                  </span>
                  <Icon name="plus" />
                </button>
              ))}
            <button className="persona-btn" style={{ ["--judge" as string]: PERSONA_COLOR.custom }} onClick={() => add("custom")}>
              <span className="persona-dot" />
              <span>
                <strong>Juiz personalizado</strong>
                <span className="hint">Você define o nome, a perspectiva, os critérios e os pesos.</span>
              </span>
              <Icon name="plus" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Equipes */

const TEAM_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#db2777", "#0891b2", "#dc2626", "#475569"];
type ModelOption = CatalogResponse["model_options"][number];

function priceTag(m: ModelOption | undefined): string {
  if (!m) return "";
  if (!m.price_known) return "preço desconhecido";
  return `US$ ${Number(m.price_input_per_1m)} / ${Number(m.price_output_per_1m)} por 1M tokens`;
}

function cheaperBy(main: ModelOption | undefined, second: ModelOption | undefined): number | null {
  if (!main?.price_known || !second?.price_known) return null;
  const a = Number(main.price_input_per_1m) + Number(main.price_output_per_1m);
  const b = Number(second.price_input_per_1m) + Number(second.price_output_per_1m);
  return b > 0 && a > b ? a / b : null;
}

function ModelChips({ c, catalog }: { c: Pick<CandidateConfig, "provider" | "model_option" | "secondary_model_option">; catalog: CatalogResponse }) {
  const find = (opt: string | null | undefined) => catalog.model_options.find((m) => m.provider === c.provider && m.option === opt);
  const main = find(c.model_option);
  const second = find(c.secondary_model_option);
  const ratio = cheaperBy(main, second);
  return (
    <span className="model-chips">
      <span className="model-chip main" title={priceTag(main)}>
        <Icon name="star" size={12} /> {main?.label ?? c.model_option}
      </span>
      {second ? (
        <span className="model-chip second" title={priceTag(second)}>
          <Icon name="zap" size={12} /> {second.label}
          {ratio && <strong> · {ratio.toFixed(0)}x mais barato</strong>}
        </span>
      ) : (
        <span className="model-chip none">sem modelo econômico</span>
      )}
    </span>
  );
}

function TeamCard({ c, index, open, onToggle, onChange, onRemove, canRemove, catalog, mode }: {
  c: CandidateConfig;
  index: number;
  open: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<CandidateConfig>) => void;
  onRemove: () => void;
  canRemove: boolean;
  catalog: CatalogResponse;
  mode: string;
}) {
  const color = c.color ?? TEAM_COLORS[index % TEAM_COLORS.length];
  const options = catalog.model_options.filter((m) => m.enabled && (mode === "mock" ? m.provider === "mock" : m.provider !== "mock"));
  const find = (opt: string | null | undefined) => options.find((m) => m.option === opt);
  const ratio = cheaperBy(find(c.model_option), find(c.secondary_model_option));
  const uses = new Set(c.secondary_for ?? []);
  const toggleUse = (u: "research" | "critique", on: boolean) => {
    const next = new Set(uses);
    if (on) next.add(u);
    else next.delete(u);
    onChange({ secondary_for: Array.from(next) as CandidateConfig["secondary_for"] });
  };

  function applyPreset(name: string) {
    const preset = catalog.presets.find((p) => p.preset === name);
    if (!preset) return onChange({ preset: null });
    onChange({
      preset: preset.preset as CandidateConfig["preset"],
      instructions: preset.instructions,
      model_option: preset.model_option_by_provider[c.provider] ?? c.model_option,
      secondary_model_option: preset.secondary_by_provider?.[c.provider] ?? null,
      allowed_specialists: preset.allowed_specialists as CandidateConfig["allowed_specialists"],
      max_specialist_tasks: preset.max_specialist_tasks,
    });
  }

  return (
    <div className={`panel judge team ${open ? "open" : ""}`} style={{ ["--judge" as string]: color }}>
      <div className="judge-head">
        <button className="judge-toggle" onClick={onToggle} title={open ? "Recolher" : "Editar"}>
          <span className="judge-avatar">{c.name.match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() ?? index + 1}</span>
          <span className="judge-title">
            <strong>{c.name}</strong>
            <ModelChips c={c} catalog={catalog} />
          </span>
        </button>
        <button className="icon-btn" onClick={onToggle} title={open ? "Recolher" : "Editar"}>
          <span className={`chev ${open ? "up" : ""}`}>
            <Icon name="chevron" />
          </span>
        </button>
        <button className="icon-btn" title="Remover equipe" disabled={!canRemove} onClick={onRemove}>
          <Icon name="trash" />
        </button>
      </div>

      {open && (
        <div className="judge-body team-body">
          <section>
            <h4>Identidade</h4>
            <div className="inline">
              <div>
                <label>Nome</label>
                <input value={c.name} onChange={(e) => onChange({ name: e.target.value })} />
              </div>
              <div>
                <label>Estratégia pronta</label>
                <select value={c.preset ?? ""} onChange={(e) => applyPreset(e.target.value)}>
                  <option value="">Personalizada</option>
                  {catalog.presets.map((p) => (
                    <option key={p.preset} value={p.preset}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <label style={{ marginTop: 12 }}>Cor</label>
            <div className="swatches">
              {TEAM_COLORS.map((col) => (
                <button key={col} className={`swatch ${color === col ? "on" : ""}`} style={{ background: col }} onClick={() => onChange({ color: col })} title={col} />
              ))}
            </div>
          </section>

          <section>
            <h4>Modelos</h4>
            <div className="model-pair">
              <div className="model-box main">
                <div className="model-box-head">
                  <Icon name="star" /> <strong>Modelo principal</strong>
                </div>
                <p className="hint">Planeja, escreve e revisa a proposta da equipe.</p>
                <select value={c.model_option} onChange={(e) => onChange({ model_option: e.target.value })}>
                  {options.map((m) => (
                    <option key={m.option} value={m.option}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <div className="hint">{priceTag(find(c.model_option))}</div>
              </div>
              <div className="model-box second">
                <div className="model-box-head">
                  <Icon name="zap" /> <strong>Modelo econômico</strong> <span className="muted small">(opcional)</span>
                  {ratio && <span className="badge ok">{ratio.toFixed(0)}x mais barato</span>}
                </div>
                <p className="hint">Faz as tarefas internas simples para economizar tokens.</p>
                <select value={c.secondary_model_option ?? ""} onChange={(e) => onChange({ secondary_model_option: e.target.value || null })}>
                  <option value="">Nenhum (usa só o principal)</option>
                  {options
                    .filter((m) => m.option !== c.model_option)
                    .map((m) => (
                      <option key={m.option} value={m.option}>
                        {m.label}
                      </option>
                    ))}
                </select>
                <div className="hint">{priceTag(find(c.secondary_model_option))}</div>
                {c.secondary_model_option && (
                  <div className="uses">
                    <span className="muted small">Usar em:</span>
                    <Toggle label="Pesquisa nos documentos" checked={uses.has("research")} onChange={(v) => toggleUse("research", v)} />
                    <Toggle label="Críticas às outras equipes" checked={uses.has("critique")} onChange={(v) => toggleUse("critique", v)} />
                  </div>
                )}
              </div>
            </div>
            {c.secondary_model_option && (
              <p className="hint" style={{ marginBottom: 0 }}>
                O pensante da equipe ainda pode mandar uma pesquisa difícil para o modelo principal, se julgar necessário.
              </p>
            )}
          </section>

          <section>
            <h4>Ajudantes</h4>
            <div className="row spread">
              <div className="row">
                {catalog.specialists.map((s) => (
                  <Toggle
                    key={s.kind}
                    label={s.label}
                    checked={(c.allowed_specialists ?? []).includes(s.kind as never)}
                    onChange={(on) => {
                      const set = new Set(c.allowed_specialists ?? []);
                      if (on) set.add(s.kind as never);
                      else set.delete(s.kind as never);
                      onChange({ allowed_specialists: Array.from(set) as CandidateConfig["allowed_specialists"] });
                    }}
                  />
                ))}
              </div>
              <div className="row">
                <span className="muted small">Máx. de tarefas</span>
                <Segmented value={String(c.max_specialist_tasks)} options={["0", "1", "2"].map((n) => ({ value: n, label: n }))} onChange={(v) => onChange({ max_specialist_tasks: Number(v) })} />
              </div>
            </div>
          </section>

          <section>
            <h4>Instruções da equipe</h4>
            <textarea rows={4} value={c.instructions ?? ""} placeholder="Como esta equipe deve pensar? (o juiz não vê este texto)" onChange={(e) => onChange({ instructions: e.target.value, preset: null })} />
          </section>

          <details className="collapsible-inline">
            <summary>Avançado</summary>
            <div className="inline" style={{ marginTop: 10 }}>
              <div>
                <label>Tamanho máximo da resposta (tokens)</label>
                <input type="number" min={200} max={8000} step={100} value={c.max_output_tokens} onChange={(e) => onChange({ max_output_tokens: Number(e.target.value) })} />
              </div>
              <div>
                <label>Fatia do orçamento (peso)</label>
                <input value={String(c.quota_weight)} onChange={(e) => onChange({ quota_weight: e.target.value })} />
              </div>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

export function TeamsTab({ cfg, update, catalog }: Base) {
  const [open, setOpen] = useState<number | null>(null);
  const provider = cfg.mode === "mock" ? "mock" : "neuralake";

  function switchConfigMode(mode: "auto" | "manual") {
    if (mode === "manual") {
      const n = cfg.candidate_count ?? 2;
      const cands = cfg.candidates && cfg.candidates.length >= 2 ? cfg.candidates : Array.from({ length: n }, (_, i) => defaultCandidate(i, catalog, cfg.mode));
      update({ config_mode: "manual", candidates: cands });
    } else {
      update({ config_mode: "auto", candidates: null });
    }
  }

  const cands = cfg.candidates ?? [];
  const setCandidate = (i: number, patch: Partial<CandidateConfig>) => update({ candidates: cands.map((c, idx) => (idx === i ? { ...c, ...patch } : c)) });

  return (
    <div className="stack">
      <div className="panel">
        <div className="row spread">
          <Segmented
            value={cfg.config_mode as "auto" | "manual"}
            options={[
              { value: "auto", label: "Automático" },
              { value: "manual", label: "Personalizado" },
            ]}
            onChange={switchConfigMode}
          />
          {cfg.config_mode === "auto" && (
            <div className="row">
              <span className="muted small">Quantas equipes?</span>
              <Segmented value={String(cfg.candidate_count ?? 2)} options={["2", "3", "4"].map((n) => ({ value: n, label: n }))} onChange={(v) => update({ candidate_count: Number(v) })} />
            </div>
          )}
        </div>
        <div className="economy-note">
          <Icon name="zap" />
          <span>
            Cada equipe tem um <strong>modelo principal</strong>, que pensa e escreve a proposta, e pode ter um <strong>modelo econômico</strong> para as tarefas simples. Assim gasta menos
            tokens sem perder qualidade na proposta.
          </span>
        </div>
      </div>

      {cfg.config_mode === "auto" ? (
        <>
          <div className="team-grid">
            {catalog.presets.slice(0, cfg.candidate_count ?? 2).map((p, i) => (
              <div key={p.preset} className="team-card" style={{ ["--team" as string]: TEAM_COLORS[i % TEAM_COLORS.length] }}>
                <div className="team-avatar">{p.label.slice(0, 1)}</div>
                <div style={{ minWidth: 0 }}>
                  <strong>Equipe {p.label}</strong>
                  <div className="hint">{p.description}</div>
                  <ModelChips c={{ provider: provider as CandidateConfig["provider"], model_option: p.model_option_by_provider[provider], secondary_model_option: p.secondary_by_provider?.[provider] ?? null }} catalog={catalog} />
                </div>
              </div>
            ))}
          </div>
          <button className="add-btn" onClick={() => switchConfigMode("manual")}>
            <Icon name="edit" /> Personalizar estas equipes
          </button>
        </>
      ) : (
        <>
          {cands.map((c, i) => (
            <TeamCard
              key={i} c={c} index={i} open={open === i} onToggle={() => setOpen(open === i ? null : i)} catalog={catalog} mode={cfg.mode} canRemove={cands.length > 2}
              onChange={(patch) => setCandidate(i, patch)}
              onRemove={() => {
                update({ candidates: cands.filter((_, idx) => idx !== i) });
                setOpen(null);
              }}
            />
          ))}
          {cands.length < 4 && (
            <button
              className="add-btn"
              onClick={() => {
                update({ candidates: [...cands, { ...defaultCandidate(cands.length, catalog, cfg.mode), color: TEAM_COLORS[cands.length % TEAM_COLORS.length] }] });
                setOpen(cands.length);
              }}
            >
              <Icon name="plus" /> Adicionar equipe
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Orcamento e modo */

export function BudgetTab({ cfg, update, catalog }: Base) {
  const realAvailable = catalog.providers?.neuralake?.enabled === true;
  const updateBudget = (patch: Partial<ChallengeConfig["budget"]>) => update({ budget: { ...cfg.budget, ...patch } });

  function switchMode(mode: "mock" | "real") {
    const provider = mode === "mock" ? "mock" : "neuralake";
    const cands = cfg.candidates?.map((c) => {
      const preset = catalog.presets.find((p) => p.preset === c.preset);
      return {
        ...c, provider: provider as CandidateConfig["provider"], model_option: preset?.model_option_by_provider[provider] ?? (mode === "mock" ? "mock-default" : "auto"),
        secondary_model_option: preset?.secondary_by_provider?.[provider] ?? null,
      };
    });
    // Juizes voltam para o modelo padrao do novo modo (o servidor escolhe o provedor certo).
    const judges = cfg.judges?.map((j) => ({ ...j, provider: null, model_option: null }));
    update({ mode, candidates: cands ?? null, judge: null, judges: judges ?? null, mock_scenario: "default" });
  }

  return (
    <div className="stack">
      <div className="panel">
        <label>Modo de execução</label>
        <Segmented
          value={cfg.mode as "mock" | "real"}
          options={[
            { value: "mock", label: "Simulado (grátis)" },
            { value: "real", label: "Real · NeuraLake", disabled: !realAvailable },
          ]}
          onChange={switchMode}
        />
        <p className="hint" style={{ marginBottom: 0 }}>
          {realAvailable ? "O modo real usa a IA da NeuraLake e gasta créditos." : "Modo real indisponível: falta configurar a chave da NeuraLake no servidor."}
        </p>
        {cfg.mode === "mock" && (
          <div className="field" style={{ marginTop: 14, marginBottom: 0, maxWidth: 320 }}>
            <label>Cenário simulado</label>
            <select value={cfg.mock_scenario} onChange={(e) => update({ mock_scenario: e.target.value })}>
              {catalog.mock_scenarios.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="inline">
          <div>
            <label>Teto de gasto ({cfg.budget.currency})</label>
            <input value={cfg.budget.total_cap ?? ""} onChange={(e) => updateBudget({ total_cap: e.target.value || null })} placeholder="ex.: 1.00" />
          </div>
          <div>
            <label>Rodadas de crítica entre equipes</label>
            <Segmented value={String(cfg.critique_rounds)} options={[{ value: "0", label: "Nenhuma" }, { value: "1", label: "Uma" }]} onChange={(v) => update({ critique_rounds: Number(v) })} />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <Toggle checked={cfg.budget.strict} onChange={(v) => updateBudget({ strict: v })} label="Bloquear qualquer chamada que passe do teto" />
        </div>
      </div>

      <details className="panel collapsible">
        <summary>Configurações avançadas</summary>
        <div className="inline" style={{ marginTop: 12 }}>
          <div>
            <label>Cota comum (%)</label>
            <input value={String(cfg.budget.common_share_pct)} onChange={(e) => updateBudget({ common_share_pct: e.target.value })} />
          </div>
          <div>
            <label>Máx. de chamadas</label>
            <input type="number" min={4} max={32} value={cfg.budget.max_total_calls} onChange={(e) => updateBudget({ max_total_calls: Number(e.target.value) })} />
          </div>
          <div>
            <label>Chamadas simultâneas</label>
            <input type="number" min={1} max={4} value={cfg.budget.max_concurrent_calls} onChange={(e) => updateBudget({ max_concurrent_calls: Number(e.target.value) })} />
          </div>
          <div>
            <label>Prazo total (s)</label>
            <input type="number" min={10} value={cfg.budget.run_deadline_s} onChange={(e) => updateBudget({ run_deadline_s: Number(e.target.value) })} />
          </div>
          <div>
            <label>Timeout por chamada (s)</label>
            <input type="number" min={1} value={cfg.budget.call_timeout_s} onChange={(e) => updateBudget({ call_timeout_s: Number(e.target.value) })} />
          </div>
          <div>
            <label>Tentativas por chamada</label>
            <input type="number" min={1} max={2} value={cfg.budget.max_attempts_per_call} onChange={(e) => updateBudget({ max_attempts_per_call: Number(e.target.value) })} />
          </div>
          <div>
            <label>Seed</label>
            <input value={cfg.seed ?? ""} placeholder="aleatória" onChange={(e) => update({ seed: e.target.value === "" ? null : (Number(e.target.value) as unknown as number) })} />
          </div>
        </div>
      </details>
    </div>
  );
}
