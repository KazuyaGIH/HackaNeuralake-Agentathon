"use client";

import { useState } from "react";
import type { Report } from "@/lib/api";
import Icon from "../Icon";
import { initial } from "./live";

export type Feedback = Record<string, string>;
export type NextMode = "plan" | "refine" | null;
type Team = (id: string) => { name: string; color: string };

// Comentario por proposta (usado dentro da aba Propostas; compartilha o estado com o painel de proximo passo).
export function CommentBox({ cid, feedback, setFeedback }: { cid: string; feedback: Feedback; setFeedback: (f: Feedback) => void }) {
  const value = feedback[cid] ?? "";
  return (
    <div className={`comment-box ${value.trim() ? "filled" : ""}`}>
      <label>
        <Icon name="edit" size={13} /> Comentário para esta equipe (leva a equipe para a repescagem)
      </label>
      <textarea rows={2} value={value} placeholder="O que esta equipe deve melhorar? (ex.: detalhe o cronograma, reduza o custo...)" onChange={(e) => setFeedback({ ...feedback, [cid]: e.target.value })} />
    </div>
  );
}

export default function NextSteps({ report, team, feedback, setFeedback, onRefine, onPlan, busy, isRefinement, mode, setMode }: {
  report: Report;
  team: Team;
  feedback: Feedback;
  setFeedback: (f: Feedback) => void;
  onRefine: (items: { candidate_id: string; comment: string }[], general: string) => void;
  onPlan: (candidateId: string, instructions: string) => void;
  busy: boolean;
  isRefinement: boolean;
  mode: NextMode;
  setMode: (m: NextMode) => void;
}) {
  const teams = report.proposals.map((p) => p.candidate_id);
  const [general, setGeneral] = useState("");
  const [planTeam, setPlanTeam] = useState(report.winner_candidate_id ?? teams[0] ?? "");
  const [instructions, setInstructions] = useState("");
  const selected = teams.filter((t) => t in feedback);
  const missing = selected.filter((t) => !general.trim() && !(feedback[t] ?? "").trim());
  const canSend = selected.length > 0 && missing.length === 0;
  const leader = report.winner_candidate_id ?? report.co_leaders[0] ?? null;

  const toggle = (cid: string) => {
    const next = { ...feedback };
    if (cid in next) delete next[cid];
    else next[cid] = "";
    setFeedback(next);
  };
  const selectAll = () => setFeedback(Object.fromEntries(teams.map((t) => [t, feedback[t] ?? ""])));

  return (
    <section id="next-steps" className="next">
      <div className="next-title">
        <div className="eyebrow">Próximo passo</div>
        <h3>O que você quer fazer agora?</h3>
      </div>

      <div className="next-options">
        <button className={`next-option go ${mode === "plan" ? "on" : ""}`} onClick={() => setMode(mode === "plan" ? null : "plan")}>
          <span className="next-option-icon">
            <Icon name="check" size={18} />
          </span>
          <span className="next-option-text">
            <strong>{leader ? `Seguir com a ${team(leader).name}` : "Seguir para o plano de ação"}</strong>
            <span>Gostou? A equipe transforma a proposta em um plano de ação: fases, tarefas, metas e orçamento.</span>
          </span>
          <span className="badge ok">Recomendado</span>
        </button>
        <button className={`next-option ${mode === "refine" ? "on" : ""}`} onClick={() => setMode(mode === "refine" ? null : "refine")}>
          <span className="next-option-icon">
            <Icon name="edit" size={18} />
          </span>
          <span className="next-option-text">
            <strong>{isRefinement ? "Outra repescagem" : "Repescagem"}</strong>
            <span>Ainda não está bom? Escolha as equipes e diga o que melhorar. As outras saem da disputa.</span>
          </span>
        </button>
      </div>

      {mode === "plan" && (
        <div className="panel next-form">
          <div className="inline">
            <div>
              <label>Equipe que monta o plano</label>
              <select value={planTeam} onChange={(e) => setPlanTeam(e.target.value)}>
                {teams.map((cid) => (
                  <option key={cid} value={cid}>
                    {team(cid).name}
                    {cid === report.winner_candidate_id ? " (vencedora)" : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="field" style={{ marginTop: 12 }}>
            <label>Pedido para o plano (opcional)</label>
            <textarea rows={2} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Ex.: plano para 3 meses, com responsáveis por área" />
          </div>
          <div className="next-actions">
            <span className="muted small">Você poderá pedir para detalhar mais depois.</span>
            <button className="primary" disabled={busy || !planTeam} onClick={() => onPlan(planTeam, instructions.trim())}>
              <Icon name="file" size={14} /> {busy ? "Enviando…" : "Montar plano de ação"}
            </button>
          </div>
        </div>
      )}

      {mode === "refine" && (
        <div className="panel next-form">
          <div className="row spread" style={{ marginBottom: 10 }}>
            <label style={{ margin: 0 }}>1. Quem vai para a repescagem?</label>
            {teams.length > 1 && (
              <button className="link small" onClick={selectAll}>
                Selecionar todas
              </button>
            )}
          </div>
          <div className="fb-list">
            {teams.map((cid) => {
              const t = team(cid);
              const on = cid in feedback;
              const entry = report.ranking.find((r) => r.candidate_id === cid);
              const lacks = missing.includes(cid);
              return (
                <div key={cid} className={`fb-item ${on ? "on" : ""} ${lacks ? "lacks" : ""}`} style={{ ["--team" as string]: t.color }}>
                  <button className="fb-toggle" onClick={() => toggle(cid)}>
                    <span className={`fb-check ${on ? "on" : ""}`}>{on && <Icon name="check" size={12} />}</span>
                    <span className="fb-avatar">{initial(t.name)}</span>
                    <strong>{t.name}</strong>
                    {entry?.rank && <span className="muted small">#{entry.rank} · {Number(entry.score_0_100 ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}</span>}
                  </button>
                  {on && (
                    <textarea
                      rows={2} value={feedback[cid]} placeholder={general.trim() ? "Comentário só para esta equipe (opcional)" : `O que a ${t.name} deve melhorar?`}
                      onChange={(e) => setFeedback({ ...feedback, [cid]: e.target.value })}
                    />
                  )}
                </div>
              );
            })}
          </div>

          <div className="field" style={{ marginTop: 16 }}>
            <label>2. Comentário para todas as escolhidas {selected.some((t) => (feedback[t] ?? "").trim()) ? "(opcional)" : ""}</label>
            <textarea rows={2} value={general} onChange={(e) => setGeneral(e.target.value)} placeholder="Ex.: o prazo é mais importante que o custo; deixem a proposta mais concreta" />
            <div className="hint">Use um comentário geral, um por equipe, ou os dois: cada equipe recebe o geral mais o dela.</div>
          </div>

          <div className="next-actions">
            <span className={`small ${missing.length ? "text-bad" : "muted"}`}>
              {selected.length === 0
                ? "Escolha pelo menos uma equipe."
                : missing.length
                  ? `Falta comentário para ${missing.map((m) => team(m).name).join(", ")}: escreva um geral ou um específico.`
                  : `${selected.length} na repescagem${teams.length - selected.length > 0 ? ` · ${teams.length - selected.length} fica${teams.length - selected.length > 1 ? "m" : ""} de fora` : ""}`}
            </span>
            <button className="primary" disabled={busy || !canSend} onClick={() => onRefine(selected.map((cid) => ({ candidate_id: cid, comment: (feedback[cid] ?? "").trim() })), general.trim())}>
              <Icon name="zap" size={14} /> {busy ? "Enviando…" : "Enviar para a repescagem"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
