"use client";

import { useState } from "react";
import type { ActionPlan, Constraint, Report } from "@/lib/api";
import { api } from "@/lib/api";
import { makeHumanizer } from "@/lib/humanize";
import Icon from "../Icon";
import { usd } from "./Results";

export default function ActionPlanView({ plan, report, runId, team, constraints, onEvidence, onDetail, busy }: {
  plan: ActionPlan;
  report: Report;
  runId: string;
  team: { name: string; color: string };
  constraints: Constraint[];
  onEvidence: (id: string) => void;
  onDetail?: (request: string) => void;
  busy?: boolean;
}) {
  const hz = makeHumanizer(constraints);
  const [ask, setAsk] = useState("");
  const toDetail = () => document.getElementById("plan-detail")?.scrollIntoView({ behavior: "smooth", block: "center" });
  const ideas = ["Detalhe a fase de piloto semana a semana", "Inclua um orçamento por fase", "Defina responsáveis por área e um RACI", "Adicione um cronograma com marcos e datas"];

  return (
    <div className="plan" style={{ ["--team" as string]: team.color }}>
      <div className="plan-hero">
        <div className="winner-icon">
          <Icon name="file" size={24} />
        </div>
        <div className="plan-hero-body">
          <div className="eyebrow">
            Plano de ação · {team.name} · versão {plan.version}
          </div>
          <h2>{hz.text(plan.title)}</h2>
          <p>{hz.text(plan.summary)}</p>
          {plan.detail_request && (
            <div className="plan-asked">
              <Icon name="edit" size={13} /> Você pediu: “{plan.detail_request}”
            </div>
          )}
        </div>
        <div className="plan-hero-actions">
          {onDetail && (
            <button className="primary" onClick={toDetail}>
              <Icon name="plus" size={14} /> Detalhar mais
            </button>
          )}
          <a href={api.reportUrl(runId, "md")} target="_blank" rel="noreferrer">
            <button>
              <Icon name="file" size={14} /> Baixar
            </button>
          </a>
        </div>
      </div>

      {plan.objectives.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Objetivos</h3>
          <ul className="plan-objectives">
            {plan.objectives.map((o, i) => (
              <li key={i}>
                <span className="plan-num">{i + 1}</span>
                {hz.text(o)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.phases.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Fases</h3>
          <div className="phases">
            {plan.phases.map((ph, i) => (
              <div key={i} className="phase">
                <div className="phase-rail">
                  <span className="phase-dot">{i + 1}</span>
                  {i < plan.phases.length - 1 && <span className="phase-line" />}
                </div>
                <div className="phase-body">
                  <div className="phase-head">
                    <strong>{hz.text(ph.name)}</strong>
                    {ph.duration && <span className="badge info">{ph.duration}</span>}
                  </div>
                  {ph.goal && <p className="muted small">{hz.text(ph.goal)}</p>}
                  {ph.tasks.length > 0 && (
                    <table className="matrix phase-tasks">
                      <thead>
                        <tr>
                          <th>Tarefa</th>
                          <th>Responsável</th>
                          <th>Entregável</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ph.tasks.map((t, j) => (
                          <tr key={j}>
                            <td>{hz.text(t.task)}</td>
                            <td>{t.owner || "—"}</td>
                            <td>{t.deliverable || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="plan-grid">
        {plan.kpis.length > 0 && (
          <div className="panel">
            <h3 className="panel-title">Metas (KPIs)</h3>
            <div className="kpis">
              {plan.kpis.map((k, i) => (
                <div key={i} className="kpi">
                  <span>{hz.text(k.metric)}</span>
                  <strong>{hz.text(k.target)}</strong>
                </div>
              ))}
            </div>
          </div>
        )}
        {plan.risks.length > 0 && (
          <div className="panel">
            <h3 className="panel-title">Riscos e como evitar</h3>
            <ul className="risks">
              {plan.risks.map((r, i) => (
                <li key={i}>
                  <strong>{hz.text(r.risk)}</strong>
                  <span>{hz.text(r.mitigation)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="plan-grid">
        {plan.budget_estimate && (
          <div className="panel">
            <h3 className="panel-title">Orçamento estimado</h3>
            <p style={{ margin: 0 }}>{hz.text(plan.budget_estimate)}</p>
          </div>
        )}
        {plan.next_steps.length > 0 && (
          <div className="panel">
            <h3 className="panel-title">Próximos passos imediatos</h3>
            <ol className="plan-next">
              {plan.next_steps.map((s, i) => (
                <li key={i}>{hz.text(s)}</li>
              ))}
            </ol>
          </div>
        )}
      </div>

      <p className="hint">
        {plan.evidence_ids.length > 0 && (
          <>
            Evidências citadas:{" "}
            {plan.evidence_ids.map((id) => (
              <button key={id} className="ev-chip" onClick={() => onEvidence(id)}>
                {id}
              </button>
            ))}{" "}
            ·{" "}
          </>
        )}
        Custo para montar o plano: {usd(report.cost.total)}
      </p>

      {onDetail && (
        <div id="plan-detail" className="panel next-steps plan-detail">
          <div className="eyebrow">Próximo passo</div>
          <h3>Quer o plano mais detalhado?</h3>
          <p className="hint" style={{ marginTop: 0 }}>
            Diga o que aprofundar. A {team.name} gera a versão {plan.version + 1}, mantendo o que já está bom.
          </p>
          <div className="idea-chips">
            {ideas.map((i) => (
              <button key={i} className="idea-chip" onClick={() => setAsk(ask.trim() ? `${ask.trim()}; ${i.toLowerCase()}` : i)}>
                <Icon name="plus" size={12} /> {i}
              </button>
            ))}
          </div>
          <textarea rows={3} value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="O que deve ser detalhado?" />
          <div className="next-actions">
            <span className="muted small">Uma chamada de IA da equipe (custo baixo).</span>
            <button className="primary" disabled={busy || !ask.trim()} onClick={() => onDetail(ask.trim())}>
              <Icon name="zap" size={14} /> {busy ? "Enviando…" : `Gerar versão ${plan.version + 1}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
