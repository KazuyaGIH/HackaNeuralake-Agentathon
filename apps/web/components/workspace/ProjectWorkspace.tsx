"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, TERMINAL, type CatalogResponse, type ChallengeConfig, type RunSummary, type SourceCreateResponse } from "@/lib/api";
import { STATUS_LABEL, ago } from "@/lib/format";
import { deleteProject, getProject, projectName, saveProject, withJudges, type Project } from "@/lib/projects";
import Icon, { type IconName } from "../Icon";
import RunView from "../RunView";
import { BudgetTab, ChallengeTab, DocumentsTab, JudgesTab, OverviewTab, RulesTab, TeamsTab, blockers } from "./tabs";

const CONFIG_TABS: { key: string; label: string; icon: IconName; title: string; subtitle: string }[] = [
  { key: "overview", label: "Visão geral", icon: "grid", title: "Visão geral", subtitle: "Resumo do projeto e das arenas executadas." },
  { key: "desafio", label: "Desafio", icon: "edit", title: "Desafio", subtitle: "O que as equipes de agentes precisam decidir." },
  { key: "documentos", label: "Documentos", icon: "file", title: "Documentos", subtitle: "Material que as equipes podem consultar e citar como prova." },
  { key: "regras", label: "Regras", icon: "flag", title: "Regras", subtitle: "Limites que toda proposta precisa respeitar." },
  { key: "juizes", label: "Juízes", icon: "star", title: "Juízes", subtitle: "Quem dá as notas, com quais critérios e quanto cada um pesa no resultado." },
  { key: "equipes", label: "Equipes", icon: "users", title: "Equipes", subtitle: "Quem compete na arena." },
  { key: "orcamento", label: "Orçamento e modo", icon: "dollar", title: "Orçamento e modo", subtitle: "Quanto pode ser gasto e se a execução é simulada ou real." },
];

const DOT_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "live", queued: "info" };

export default function ProjectWorkspace({ projectId, initialTab }: { projectId: string; initialTab?: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null | undefined>(undefined);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [tab, setTab] = useState(initialTab ?? "overview");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setProject(getProject(projectId));
    api
      .catalog()
      .then(setCatalog)
      .catch((e: Error) => setError({ message: `Não foi possível falar com o servidor: ${e.message}`, hint: "Confira se o backend está ligado em http://127.0.0.1:8000." }));
  }, [projectId]);

  // Projetos sem painel de juizes (antigos ou recem-carregados do exemplo) ganham o juiz "Padrão".
  const needsJudges = !!project && !!catalog && !project.config.judges?.length;
  useEffect(() => {
    if (needsJudges && catalog) setProject((p) => (p ? saveProject({ ...p, config: withJudges(p.config, catalog) }) : p));
  }, [needsJudges, catalog]);

  // Atualiza a lista de arenas do projeto; enquanto alguma estiver rodando, consulta de novo.
  const runKey = project?.runIds.join(",") ?? "";
  useEffect(() => {
    if (!runKey) return setRuns([]);
    const ids = runKey.split(",");
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const mine = (await api.listRuns()).filter((r) => ids.includes(r.run_id));
        if (stop) return;
        setRuns(mine);
        if (mine.some((r) => !TERMINAL.has(r.status))) timer = setTimeout(load, 2500);
      } catch {
        /* backend fora do ar: a lista fica como esta */
      }
    };
    void load();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [runKey]);

  if (project === undefined) return null;
  if (project === null)
    return (
      <div className="container">
        <div className="empty">
          <h2>Projeto não encontrado</h2>
          <p className="muted">Ele pode ter sido excluído ou criado em outro navegador.</p>
          <Link href="/">
            <button>Voltar para Projetos</button>
          </Link>
        </div>
      </div>
    );

  const cfg = project.config;
  const persist = (patch: Partial<Project>) => setProject((p) => (p ? saveProject({ ...p, ...patch }) : p));
  const update = (patch: Partial<ChallengeConfig>) => setProject((p) => (p ? saveProject({ ...p, config: { ...p.config, ...patch } }) : p));
  const addSource = (src: SourceCreateResponse) =>
    setProject((p) =>
      p
        ? saveProject({
            ...p,
            sources: p.sources.some((x) => x.source_id === src.source_id) ? p.sources : [...p.sources, src],
            config: { ...p.config, source_ids: p.config.source_ids.includes(src.source_id) ? p.config.source_ids : [...p.config.source_ids, src.source_id] },
          })
        : p,
    );
  const removeSource = (id: string) => persist({ sources: project.sources.filter((x) => x.source_id !== id), config: { ...cfg, source_ids: cfg.source_ids.filter((x) => x !== id) } });
  const runNumber = (id: string) => project.runIds.indexOf(id) + 1;
  const go = (t: string) => {
    setTab(t);
    setError(null);
    setNotice(null);
  };
  const problems = blockers(cfg, catalog);

  async function loadDemo() {
    setBusy(true);
    setError(null);
    try {
      const demo = await api.demoPrepare();
      const sources = demo.challenge.source_ids.map((id, i) => ({
        source_id: id, title: demo.documents[i] ?? id, media_type: "text/markdown", size_bytes: 0, sha256: "", extraction_status: "ok", pages: null, chars: 0, warnings: [],
      }));
      persist({ config: { ...demo.challenge, candidates: null, judge: null }, sources });
      setNotice(demo.note);
    } catch (e) {
      setError({ message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files) return;
    setBusy(true);
    setError(null);
    try {
      for (const f of Array.from(files)) addSource(await api.uploadFile(f));
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, hint: err.hint });
    } finally {
      setBusy(false);
    }
  }

  async function onPaste(title: string, text: string): Promise<boolean> {
    if (!text.trim()) return false;
    setBusy(true);
    try {
      addSource(await api.uploadText(title || "texto colado", text));
      return true;
    } catch (e) {
      setError({ message: (e as Error).message });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function startArena() {
    setBusy(true);
    setError(null);
    try {
      const payload: ChallengeConfig = { ...cfg, title: cfg.title || null, seed: cfg.seed === null || (cfg.seed as unknown) === "" ? null : Number(cfg.seed) };
      if (payload.config_mode === "auto") payload.candidates = null;
      const key = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
      const res = await api.createRun(payload, key);
      addRun(res.run_id);
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, hint: err.hint });
    } finally {
      setBusy(false);
    }
  }

  function addRun(runId: string) {
    setProject((p) => (p ? saveProject({ ...p, runIds: p.runIds.includes(runId) ? p.runIds : [...p.runIds, runId] }) : p));
    go(`arena:${runId}`);
  }

  const activeRun = tab.startsWith("arena:") ? tab.slice(6) : null;
  const meta = CONFIG_TABS.find((t) => t.key === tab);
  const sortedRuns = [...project.runIds].reverse();
  const statusOf = (id: string) => runs.find((r) => r.run_id === id);

  return (
    <div className="workspace">
      <aside className="sidebar">
        <Link href="/" className="side-back">
          <Icon name="back" size={14} /> Projetos
        </Link>
        <div className="side-project">
          <div className="side-avatar">{(projectName(project).match(/[\p{L}\p{N}]/u)?.[0] ?? "P").toUpperCase()}</div>
          <div className="side-project-name" title={projectName(project)}>
            {projectName(project)}
          </div>
        </div>
        <button className="primary block" onClick={startArena} disabled={busy || !catalog || problems.length > 0} title={problems.join("\n")}>
          <Icon name="play" size={14} /> Iniciar arena
        </button>

        <nav className="side-nav">
          <div className="side-label">Projeto</div>
          {CONFIG_TABS.map((t) => (
            <button key={t.key} className={`side-item ${tab === t.key ? "active" : ""}`} onClick={() => go(t.key)}>
              <Icon name={t.icon} size={15} />
              <span>{t.label}</span>
            </button>
          ))}

          <div className="side-label">
            Arenas <span className="side-count">{project.runIds.length}</span>
          </div>
          {sortedRuns.length === 0 && <div className="side-empty">Nenhuma arena ainda</div>}
          {sortedRuns.map((id) => {
            const r = statusOf(id);
            return (
              <button key={id} className={`side-item run ${activeRun === id ? "active" : ""}`} onClick={() => go(`arena:${id}`)} title={r ? STATUS_LABEL[r.status] : ""}>
                <span className={`dot ${r ? (DOT_CLASS[r.status] ?? "info") : "info"}`} />
                <span className="run-name">Arena {runNumber(id)}</span>
                <span className="run-when">{r ? ago(r.created_at) : ""}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="content">
        <div className="content-inner">
          {meta && (
            <div className="page-head">
              <div>
                <h1>{meta.title}</h1>
                <p className="lead">{meta.subtitle}</p>
              </div>
              {tab === "overview" && problems.length > 0 && (
                <div className="notice compact">
                  <Icon name="alert" /> {problems[0]}
                </div>
              )}
            </div>
          )}
          {notice && <div className="notice">{notice}</div>}
          {error && (
            <div className="error">
              <strong>Erro:</strong> {error.message}
              {error.hint && <div className="hint">{error.hint}</div>}
            </div>
          )}

          {activeRun ? (
            <RunView
              key={activeRun} runId={activeRun} title={`Arena ${runNumber(activeRun)}`} onNewRun={addRun}
              onStatus={(d) => setRuns((rs) => rs.map((r) => (r.run_id === d.run_id ? { ...r, status: d.status, decision_status: d.decision_status, finished_at: d.finished_at } : r)))}
            />
          ) : !catalog ? (
            !error && <p className="muted">Carregando…</p>
          ) : tab === "overview" ? (
            <OverviewTab
              cfg={cfg} update={update} catalog={catalog} sources={project.sources} runs={runs} runNumber={runNumber} go={go}
              onDelete={() => {
                deleteProject(project.id);
                router.push("/");
              }}
            />
          ) : tab === "desafio" ? (
            <ChallengeTab cfg={cfg} update={update} catalog={catalog} onLoadDemo={loadDemo} busy={busy} />
          ) : tab === "documentos" ? (
            <DocumentsTab cfg={cfg} update={update} catalog={catalog} sources={project.sources} busy={busy} onUpload={onUpload} onPaste={onPaste} onRemove={removeSource} />
          ) : tab === "regras" ? (
            <RulesTab cfg={cfg} update={update} catalog={catalog} />
          ) : tab === "juizes" ? (
            <JudgesTab cfg={cfg} update={update} catalog={catalog} />
          ) : tab === "equipes" ? (
            <TeamsTab cfg={cfg} update={update} catalog={catalog} />
          ) : tab === "orcamento" ? (
            <BudgetTab cfg={cfg} update={update} catalog={catalog} />
          ) : null}
        </div>
      </section>
    </div>
  );
}
