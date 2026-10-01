"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, type RunSummary } from "@/lib/api";
import { STATUS_LABEL, ago } from "@/lib/format";
import { createProject, deleteProject, emptyConfig, loadProjects, projectName, saveProject, type Project } from "@/lib/projects";
import Icon from "./Icon";

const STATUS_CLASS: Record<string, string> = { completed: "ok", partial: "warn", failed: "bad", cancelled: "info", interrupted: "bad", running: "accent", queued: "info" };

export default function ProjectsHome() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  useEffect(() => {
    setProjects(loadProjects());
    api.listRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  const refresh = () => setProjects(loadProjects());

  function rename(p: Project) {
    const title = editValue.trim();
    if (title && title !== projectName(p)) saveProject({ ...p, config: { ...p.config, title } });
    setEditing(null);
    refresh();
  }

  function duplicate(p: Project) {
    const copy = createProject({ ...p.config, title: `${projectName(p)} (cópia)` }, p.sources);
    refresh();
    setEditing(copy.id);
    setEditValue(projectName(copy));
  }

  function remove(p: Project) {
    deleteProject(p.id);
    setConfirmDel(null);
    refresh();
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...(projects ?? [])]
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .filter((p) => !q || projectName(p).toLowerCase().includes(q) || p.config.objective.toLowerCase().includes(q));
  }, [projects, query]);

  async function create(kind: "blank" | "demo") {
    setBusy(true);
    setError(null);
    try {
      let project: Project;
      if (kind === "demo") {
        const demo = await api.demoPrepare();
        const sources = demo.challenge.source_ids.map((id, i) => ({
          source_id: id, title: demo.documents[i] ?? id, media_type: "text/markdown", size_bytes: 0, sha256: "", extraction_status: "ok", pages: null, chars: 0, warnings: [],
        }));
        project = createProject({ ...demo.challenge, candidates: null, judge: null }, sources);
      } else {
        project = createProject(emptyConfig(await api.catalog()));
      }
      router.push(`/projetos/${project.id}${kind === "blank" ? "?aba=desafio" : ""}`);
    } catch (e) {
      setError(`Não foi possível falar com o servidor: ${(e as Error).message}`);
      setBusy(false);
    }
  }

  if (projects === null) return null;

  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1>Projetos</h1>
          <p className="lead">Cada projeto é um desafio de decisão. Abra um para configurar e colocar as equipes de agentes para competir.</p>
        </div>
        <div className="row">
          <button onClick={() => create("demo")} disabled={busy}>
            Criar exemplo
          </button>
          <button className="primary" onClick={() => create("blank")} disabled={busy}>
            <Icon name="plus" /> Novo projeto
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {projects.length === 0 ? (
        <div className="empty">
          <div className="empty-icon">
            <Icon name="folder" size={28} />
          </div>
          <h2>Nenhum projeto ainda</h2>
          <p className="muted">Comece pelo exemplo pronto para ver a arena funcionando, ou crie um projeto do zero.</p>
          <div className="row" style={{ justifyContent: "center" }}>
            <button onClick={() => create("demo")} disabled={busy}>
              Criar exemplo
            </button>
            <button className="primary" onClick={() => create("blank")} disabled={busy}>
              <Icon name="plus" /> Novo projeto
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="search">
            <Icon name="search" />
            <input placeholder="Buscar projeto…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="repo-list">
            {visible.map((p) => {
              const mine = runs.filter((r) => p.runIds.includes(r.run_id)).sort((a, b) => b.created_at.localeCompare(a.created_at));
              const last = mine[0];
              const teams = p.config.config_mode === "manual" ? (p.config.candidates?.length ?? 0) : (p.config.candidate_count ?? 2);
              if (confirmDel === p.id)
                return (
                  <div key={p.id} className="repo repo-confirm">
                    <div className="repo-main">
                      <strong>Excluir “{projectName(p)}”?</strong>
                      <p className="repo-desc">O projeto sai da lista. As arenas já executadas continuam no Histórico.</p>
                    </div>
                    <div className="row">
                      <button onClick={() => setConfirmDel(null)}>Cancelar</button>
                      <button className="danger solid" onClick={() => remove(p)}>
                        <Icon name="trash" /> Excluir
                      </button>
                    </div>
                  </div>
                );
              return (
                <div key={p.id} className="repo">
                  <Link href={`/projetos/${p.id}`} className="repo-link" onClick={(e) => editing === p.id && e.preventDefault()}>
                  <div className="repo-main">
                    <div className="repo-title">
                      {editing === p.id ? (
                        <form className="repo-rename" onSubmit={(e) => (e.preventDefault(), rename(p))} onClick={(e) => e.preventDefault()}>
                          <input
                            autoFocus value={editValue} onChange={(e) => setEditValue(e.target.value)} onBlur={() => rename(p)}
                            onKeyDown={(e) => e.key === "Escape" && setEditing(null)} onClick={(e) => e.stopPropagation()}
                          />
                        </form>
                      ) : (
                        <span>{projectName(p)}</span>
                      )}
                      <span className={`badge ${p.config.mode === "real" ? "accent" : "seal"}`}>{p.config.mode === "real" ? "REAL" : "SIMULADO"}</span>
                    </div>
                    <p className="repo-desc">{p.config.objective || "Sem objetivo definido ainda."}</p>
                    <div className="repo-meta">
                      <span>
                        <Icon name="file" size={13} /> {p.config.source_ids.length} documento{p.config.source_ids.length === 1 ? "" : "s"}
                      </span>
                      <span>
                        <Icon name="users" size={13} /> {teams} equipes
                      </span>
                      <span>
                        <Icon name="zap" size={13} /> {p.runIds.length} arena{p.runIds.length === 1 ? "" : "s"}
                      </span>
                      <span>Atualizado {ago(p.updatedAt)}</span>
                    </div>
                  </div>
                  <div className="repo-side">
                    {last ? <span className={`badge ${STATUS_CLASS[last.status] ?? "info"}`}>Última arena: {STATUS_LABEL[last.status] ?? last.status}</span> : <span className="muted small">Nenhuma arena</span>}
                    <Icon name="chevron" />
                  </div>
                  </Link>
                  <div className="repo-actions">
                    <button className="icon-btn" title="Renomear" onClick={() => (setEditing(p.id), setEditValue(projectName(p)))}>
                      <Icon name="edit" size={15} />
                    </button>
                    <button className="icon-btn" title="Duplicar" onClick={() => duplicate(p)}>
                      <Icon name="folder" size={15} />
                    </button>
                    <button className="icon-btn danger-icon" title="Excluir" onClick={() => setConfirmDel(p.id)}>
                      <Icon name="trash" size={15} />
                    </button>
                  </div>
                </div>
              );
            })}
            {visible.length === 0 && <p className="muted" style={{ padding: 16 }}>Nenhum projeto encontrado para “{query}”.</p>}
          </div>
        </>
      )}
    </div>
  );
}
