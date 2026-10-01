"use client";

import { useState } from "react";
import type { Report, RunDetail, RunEventView } from "@/lib/api";
import { elapsed, when } from "@/lib/format";
import { makeHumanizer } from "@/lib/humanize";
import Icon from "../Icon";
import NextSteps, { CommentBox, type Feedback, type NextMode } from "./NextSteps";

export type NextProps = {
  feedback: Feedback;
  setFeedback: (f: Feedback) => void;
  onRefine: (items: { candidate_id: string; comment: string }[], general: string) => void;
  onPlan: (candidateId: string, instructions: string) => void;
  busy: boolean;
};
type Props = { report: Report; detail: RunDetail; events: RunEventView[]; onEvidence: (id: string) => void; next?: NextProps | null };
type Flow = { mode: NextMode; setMode: (m: NextMode) => void; goNext: (m: NextMode) => void };

const TEAM_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea"];

export function usd(v: string | number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || v === "") return "—";
  return `US$ ${Number(v).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function score(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

// Textos dos agentes passam pelo humanizador: sem o selo [SIMULADO] (ja no cabecalho), sem chaves tecnicas, valores formatados.
const hzOf = (detail: RunDetail) => makeHumanizer(detail.snapshot.constraints);

const DECISION_TEXT: Record<string, string> = {
  ranked: "Melhor proposta entre as que cumprem as regras.",
  tie: "Empate: as melhores propostas tiveram a mesma nota.",
  no_eligible_candidate: "Nenhuma proposta cumpriu todas as regras obrigatórias.",
  inconclusive: "Resultado inconclusivo: faltam provas ou dados de custo.",
  not_evaluated: "As propostas não puderam ser avaliadas pelos juízes.",
};

function Chips({ ids, onEvidence }: { ids: string[]; onEvidence: (id: string) => void }) {
  if (!ids.length) return null;
  return (
    <span className="ev-chips">
      {ids.map((id) => (
        <button key={id} className="ev-chip" onClick={() => onEvidence(id)} title="Ver o trecho citado">
          <Icon name="file" size={11} /> {id}
        </button>
      ))}
    </span>
  );
}

/* ------------------------------------------------------------------ Resultado */

function ResultTab({ report, detail, team, next, flow }: Props & { team: (id: string) => { name: string; color: string }; flow: Flow }) {
  const ranking = [...report.ranking].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || a.candidate_id.localeCompare(b.candidate_id));
  const winner = report.winner_candidate_id ? ranking.find((e) => e.candidate_id === report.winner_candidate_id) : null;
  const winnerProposal = winner ? report.proposals.find((p) => p.candidate_id === winner.candidate_id) : null;
  const panel = (detail.snapshot.judges ?? []).length > 1;
  const savings = Object.values(report.cost.secondary_savings ?? {}).reduce((s, v) => s + Number(v), 0);
  const hz = hzOf(detail);

  return (
    <div className="stack">
      <div className={`winner ${winner ? "" : "none"}`} style={winner ? { ["--team" as string]: team(winner.candidate_id).color } : undefined}>
        <div className="winner-icon">
          <Icon name={winner ? "star" : report.co_leaders.length ? "users" : "alert"} size={26} />
        </div>
        <div className="winner-body">
          <div className="eyebrow">{winner ? "Vencedora" : report.co_leaders.length ? "Empate" : "Sem vencedora"}</div>
          <h2>{winner ? team(winner.candidate_id).name : report.co_leaders.length ? report.co_leaders.map((c) => team(c).name).join(" e ") : "Nenhuma equipe venceu"}</h2>
          <p>{DECISION_TEXT[report.decision_status] ?? report.decision_status}</p>
          {winnerProposal && (
            <div className="winner-proposal">
              <strong>{hz.text(winnerProposal.title)}</strong>
              <span>{hz.text(winnerProposal.recommendation)}</span>
            </div>
          )}
        </div>
        {winner && (
          <div className="winner-side">
            <div className="winner-score">
              <span>{score(winner.score_0_100)}</span>
              <em>de 100</em>
            </div>
            {next && (
              <button className="primary winner-go" onClick={() => flow.goNext("plan")}>
                Seguir com esta equipe <Icon name="chevron" size={14} />
              </button>
            )}
          </div>
        )}
      </div>

      {next && <NextSteps report={report} team={team} {...next} isRefinement={Boolean(detail.snapshot.refinement)} mode={flow.mode} setMode={flow.setMode} />}

      <div className="tiles">
        <div className="tile">
          <span>Custo total</span>
          <strong>{usd(report.cost.total)}</strong>
          <em>{report.cost.cap ? `teto ${usd(report.cost.cap, 2)}` : "sem teto"}</em>
        </div>
        <div className="tile green">
          <span>Economia com modelo econômico</span>
          <strong>{usd(savings)}</strong>
          <em>{Object.values(report.cost.secondary_calls ?? {}).reduce((s, v) => s + v, 0)} tarefa(s) delegadas</em>
        </div>
        <div className="tile">
          <span>Chamadas de IA</span>
          <strong>{report.cost.calls_used}</strong>
          <em>de {report.cost.calls_cap} permitidas</em>
        </div>
        <div className="tile">
          <span>Duração</span>
          <strong>{elapsed(detail.started_at, detail.finished_at)}</strong>
          <em>{when(detail.finished_at)}</em>
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Ranking</h3>
        <div className="rank-list">
          {ranking.map((e) => {
            const t = team(e.candidate_id);
            const s = e.score_0_100 !== null && e.score_0_100 !== undefined ? Number(e.score_0_100) : null;
            return (
              <div key={e.candidate_id} className={`rank-row ${e.eligibility}`} style={{ ["--team" as string]: t.color }}>
                <div className="rank-pos">{e.rank ?? "–"}</div>
                <div className="rank-main">
                  <div className="rank-top">
                    <strong>{t.name}</strong>
                    {e.eligibility === "eligible" ? (
                      <span className="badge ok">Cumpre as regras</span>
                    ) : e.eligibility === "ineligible" ? (
                      <span className="badge bad">Desclassificada</span>
                    ) : (
                      <span className="badge warn">Regras sem prova</span>
                    )}
                    {e.co_leader && <span className="badge accent">Empate</span>}
                  </div>
                  <div className="rank-bar">
                    <div style={{ width: `${s ?? 0}%` }} />
                  </div>
                  {panel && e.judge_scores.length > 0 && (
                    <div className="rank-judges">
                      {e.judge_scores.map((j) => (
                        <span key={j.judge_id}>
                          {j.judge_name} <strong>{score(j.score_0_100)}</strong>
                        </span>
                      ))}
                    </div>
                  )}
                  {e.disqualification_reason && <div className="rank-note">{hz.text(e.disqualification_reason)}</div>}
                </div>
                <div className="rank-score">{score(e.score_0_100)}</div>
              </div>
            );
          })}
        </div>
        {panel && <p className="hint" style={{ marginBottom: 0 }}>Nota final = média ponderada das notas dos juízes.</p>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Propostas */

function ProposalsTab({ report, detail, onEvidence, team, next, flow }: Props & { team: (id: string) => { name: string; color: string }; flow: Flow }) {
  const hz = hzOf(detail);
  const [sel, setSel] = useState(report.winner_candidate_id ?? report.proposals[0]?.candidate_id ?? "");
  const p = report.proposals.find((x) => x.candidate_id === sel) ?? report.proposals[0];
  if (!p) return <div className="panel muted">Nenhuma proposta foi entregue.</div>;
  const sections: [string, string[]][] = [
    ["Passos", p.steps],
    ["Premissas", p.assumptions],
    ["Prós e contras", p.tradeoffs],
    ["Riscos", p.risks],
    ["Pendências", p.open_items],
  ];

  return (
    <div className="stack">
      <div className="team-tabs">
        {report.proposals.map((x) => (
          <button key={x.candidate_id} className={x.candidate_id === p.candidate_id ? "on" : ""} style={{ ["--team" as string]: team(x.candidate_id).color }} onClick={() => setSel(x.candidate_id)}>
            <span className="dot" /> {team(x.candidate_id).name}
          </button>
        ))}
      </div>
      <div className="panel proposal" style={{ ["--team" as string]: team(p.candidate_id).color }}>
        <div className="row spread">
          <span className="eyebrow">Proposta · versão {p.version}</span>
          <span className="row">
            {p.revised_from_critique && <span className="badge info">Revisada após crítica</span>}
            {p.revised_from_feedback && <span className="badge accent">Revisada com o seu feedback</span>}
          </span>
        </div>
        <h2>{hz.text(p.title)}</h2>
        <p className="proposal-rec">{hz.text(p.recommendation)}</p>

        {Object.keys(p.metrics).length > 0 && (
          <div className="metric-row">
            {Object.entries(p.metrics).map(([k, m]) => (
              <div key={k} className="metric">
                <span>{hz.label(k)}</span>
                <strong>{hz.value(m.value, m.unit)}</strong>
                <Chips ids={m.evidence_ids} onEvidence={onEvidence} />
              </div>
            ))}
          </div>
        )}

        <div className="proposal-sections">
          {sections
            .filter(([, items]) => items.length)
            .map(([title, items]) => (
              <div key={title}>
                <h4>{title}</h4>
                <ul>
                  {items.map((s, i) => (
                    <li key={i}>{hz.text(s)}</li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
        {p.evidence_ids.length > 0 && (
          <div className="proposal-ev">
            <span className="muted small">Evidências citadas</span>
            <Chips ids={p.evidence_ids} onEvidence={onEvidence} />
          </div>
        )}
        {next && <CommentBox cid={p.candidate_id} feedback={next.feedback} setFeedback={next.setFeedback} />}
      </div>
      {next && Object.values(next.feedback).some((v) => v.trim()) && (
        <div className="send-bar">
          <span>
            <Icon name="edit" size={14} /> {Object.values(next.feedback).filter((v) => v.trim()).length} comentário(s) prontos
          </span>
          <button className="primary" onClick={() => flow.goNext("refine")}>
            Revisar e enviar para a repescagem <Icon name="chevron" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Avaliacao */

const CHECK: Record<string, { icon: "check" | "x" | "alert"; cls: string; label: string }> = {
  pass: { icon: "check", cls: "ok", label: "Cumpre" },
  fail: { icon: "x", cls: "bad", label: "Quebra" },
  unknown: { icon: "alert", cls: "warn", label: "Sem prova" },
};

function EvaluationTab({ report, detail, onEvidence, team }: Props & { team: (id: string) => { name: string; color: string } }) {
  const hz = hzOf(detail);
  const teams = report.proposals.map((p) => p.candidate_id);
  const constraints = detail.snapshot.constraints;
  const judges = detail.snapshot.judges?.length ? detail.snapshot.judges : [{ judge_id: "j1", name: "Juiz", rubric: detail.snapshot.rubric }];
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="stack">
      {constraints.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Regras</h3>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th>Regra</th>
                  {teams.map((t) => (
                    <th key={t} className="center">
                      <span className="dot" style={{ background: team(t).color }} /> {team(t).name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {constraints.map((c) => (
                  <tr key={c.constraint_id}>
                    <td>
                      {c.description}
                      {!c.mandatory && <span className="muted small"> (opcional)</span>}
                    </td>
                    {teams.map((t) => {
                      const chk = report.verifications.find((v) => v.candidate_id === t)?.checks.find((x) => x.constraint_id === c.constraint_id);
                      const meta = chk ? CHECK[chk.result] : null;
                      return (
                        <td key={t} className="center" title={chk ? hz.text(chk.reason) : ""}>
                          {meta ? (
                            <span className={`check ${meta.cls}`}>
                              <Icon name={meta.icon} size={13} /> {meta.label}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {judges.map((j) => {
        const evs = report.evaluations.filter((e) => (e.judge_id ?? "j1") === j.judge_id || judges.length === 1);
        const criteria = (j.rubric ?? detail.snapshot.rubric).criteria;
        const entryScore = (cid: string) => report.ranking.find((r) => r.candidate_id === cid)?.judge_scores.find((s) => s.judge_id === j.judge_id)?.score_0_100;
        if (!evs.length) return null;
        return (
          <div key={j.judge_id ?? j.name} className="panel">
            <h3 className="panel-title">{judges.length > 1 ? `Notas · ${j.name}` : "Notas do juiz"}</h3>
            <div className="matrix-wrap">
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Critério</th>
                    <th className="num">Peso</th>
                    {teams.map((t) => (
                      <th key={t} className="center">
                        <span className="dot" style={{ background: team(t).color }} /> {team(t).name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {criteria.map((c) => (
                    <tr key={c.criterion_id}>
                      <td>
                        {c.name}
                        {c.computed_by === "server_efficiency" && <span className="muted small"> · calculado pelo sistema</span>}
                      </td>
                      <td className="num muted">{String(c.weight)}</td>
                      {teams.map((t) => {
                        const g = evs.find((e) => e.candidate_id === t)?.grades.find((x) => x.criterion_id === c.criterion_id);
                        const r = report.ranking.find((x) => x.candidate_id === t);
                        const val = g ? Number(g.grade) : Number(r?.judge_scores.find((s) => s.judge_id === j.judge_id)?.grades[c.criterion_id] ?? r?.grades[c.criterion_id] ?? NaN);
                        return (
                          <td key={t} className="center">
                            {Number.isNaN(val) ? "—" : <span className={`grade g${Math.round(val)}`}>{val.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {judges.length > 1 && (
                    <tr className="total">
                      <td>Nota deste juiz</td>
                      <td />
                      {teams.map((t) => (
                        <td key={t} className="center">
                          <strong>{score(entryScore(t))}</strong>
                        </td>
                      ))}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <button className="link small" onClick={() => setOpen(open === j.judge_id ? null : (j.judge_id ?? null))}>
              {open === j.judge_id ? "Ocultar justificativas" : "Ver justificativas"}
            </button>
            {open === j.judge_id && (
              <div className="justifs">
                {evs.map((e) => (
                  <div key={e.candidate_id} className="justif" style={{ ["--team" as string]: team(e.candidate_id).color }}>
                    <strong>{team(e.candidate_id).name}</strong>
                    <ul>
                      {e.grades.map((g) => (
                        <li key={g.criterion_id}>
                          <span className="muted">{criteria.find((c) => c.criterion_id === g.criterion_id)?.name ?? g.criterion_id}:</span> {hz.text(g.justification)}{" "}
                          <Chips ids={g.evidence_ids} onEvidence={onEvidence} />
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {report.critiques.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Críticas entre equipes</h3>
          <div className="critiques">
            {report.critiques.map((c, i) => (
              <div key={i} className="critique" style={{ ["--team" as string]: team(c.author_candidate_id).color }}>
                <div className="critique-head">
                  <strong>{team(c.author_candidate_id).name}</strong>
                  <Icon name="chevron" size={14} />
                  <strong>{team(c.target_candidate_id).name}</strong>
                </div>
                <ul>
                  {c.objections.map((o, j) => (
                    <li key={j}>
                      <span className={`sev ${o.severity}`}>{o.severity === "high" ? "Grave" : o.severity === "medium" ? "Média" : "Leve"}</span>
                      <span>{hz.text(o.point)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Custos */

function CostsTab({ report, detail, team }: Props & { team: (id: string) => { name: string; color: string } }) {
  const c = report.cost;
  const buckets = detail.budget_buckets;
  const rows = Object.entries(c.per_candidate).map(([cid, v]) => {
    const b = buckets.find((x) => x.bucket_key === `candidate:${cid}`);
    return { cid, spent: Number(v), cap: b?.cap ? Number(b.cap) : null, calls: b?.calls_used ?? 0, eco: c.secondary_calls?.[cid] ?? 0, saved: Number(c.secondary_savings?.[cid] ?? 0) };
  });
  const common = buckets.find((x) => x.bucket_key === "common");
  // Barras comparam as equipes entre si (o teto de cada uma aparece no texto ao lado).
  const maxSpent = Math.max(...rows.map((r) => r.spent), common ? Number(common.spent) : 0, 1e-12);

  return (
    <div className="stack">
      <div className="tiles">
        <div className="tile">
          <span>Total</span>
          <strong>{usd(c.total)}</strong>
          <em>{c.quality === "estimated" ? "estimativa por tabela de preços" : c.quality === "provider_reported" ? "informado pelo provedor" : "parte desconhecida"}</em>
        </div>
        <div className="tile">
          <span>Juízes</span>
          <strong>{usd(c.judge)}</strong>
          <em>parte da cota comum</em>
        </div>
        <div className="tile green">
          <span>Economia estimada</span>
          <strong>{usd(rows.reduce((s, r) => s + r.saved, 0))}</strong>
          <em>usando o modelo econômico</em>
        </div>
        <div className="tile">
          <span>Teto</span>
          <strong>{c.cap ? usd(c.cap, 2) : "—"}</strong>
          <em>{c.strict ? "bloqueio rígido" : "apenas indicativo"}</em>
        </div>
      </div>
      <div className="panel">
        <h3 className="panel-title">Gasto por equipe</h3>
        <div className="cost-rows">
          {rows.map((r) => (
            <div key={r.cid} className="cost-row" style={{ ["--team" as string]: team(r.cid).color }}>
              <div className="cost-name">
                <span className="dot" /> {team(r.cid).name}
              </div>
              <div className="cost-bar">
                <div style={{ width: `${(r.spent / maxSpent) * 100}%` }} />
              </div>
              <div className="cost-val">
                <strong>{usd(r.spent)}</strong>
                <span>
                  de {r.cap ? usd(r.cap, 2) : "—"} · {r.calls} chamadas{r.eco ? ` · ${r.eco} no econômico (−${usd(r.saved)})` : ""}
                </span>
              </div>
            </div>
          ))}
          {common && (
            <div className="cost-row" style={{ ["--team" as string]: "#94a3b8" }}>
              <div className="cost-name">
                <span className="dot" /> Comum (evidências + juízes)
              </div>
              <div className="cost-bar">
                <div style={{ width: `${(Number(common.spent) / maxSpent) * 100}%` }} />
              </div>
              <div className="cost-val">
                <strong>{usd(common.spent)}</strong>
                <span>
                  de {common.cap ? usd(common.cap, 2) : "—"} · {common.calls_used} chamadas
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Detalhes tecnicos */

function DetailsTab({ report, detail, events }: Props) {
  const hz = hzOf(detail);
  const notes = [...report.limitations.map((t) => ["Limitação", t]), ...report.operational_changes.map((t) => ["Operacional", t]), ...report.evidence_gaps.map((t) => ["Lacuna", t])];
  return (
    <div className="stack">
      <div className="panel">
        <h3 className="panel-title">Execução</h3>
        <dl className="kv">
          <dt>ID</dt>
          <dd className="mono">{detail.run_id}</dd>
          <dt>Seed</dt>
          <dd className="mono">{detail.seed}</dd>
          <dt>Início</dt>
          <dd>{when(detail.started_at)}</dd>
          <dt>Fim</dt>
          <dd>{when(detail.finished_at)}</dd>
          <dt>Embaralhamento do juiz</dt>
          <dd className="mono">{report.judge_shuffle_seed ?? "—"}</dd>
        </dl>
      </div>
      {notes.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">Observações</h3>
          <ul className="notes">
            {notes.map(([k, t], i) => (
              <li key={i}>
                <span className="badge info">{k}</span> {hz.text(t)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <details className="panel collapsible">
        <summary>Configuração congelada (hashes)</summary>
        <div className="mono hashes">
          {Object.entries(detail.snapshot_hashes).map(([k, v]) => (
            <div key={k}>
              <span className="muted">{k}</span> {v}
            </div>
          ))}
        </div>
      </details>
      <details className="panel collapsible">
        <summary>Linha do tempo bruta ({events.length} eventos)</summary>
        <div className="timeline" style={{ marginTop: 12 }}>
          {events.map((e) => (
            <div key={e.seq}>
              <span className="t">#{String(e.seq).padStart(3, " ")}</span> {new Date(e.ts).toLocaleTimeString("pt-BR")} <strong>{e.type}</strong>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

/* ------------------------------------------------------------------ container */

const TABS = [
  { key: "result", label: "Resultado", icon: "star" },
  { key: "proposals", label: "Propostas", icon: "file" },
  { key: "evaluation", label: "Avaliação", icon: "check" },
  { key: "costs", label: "Custos", icon: "dollar" },
  { key: "details", label: "Detalhes técnicos", icon: "grid" },
] as const;

export default function Results(props: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("result");
  const [mode, setMode] = useState<NextMode>(null);
  // Leva ao painel de proximo passo (na aba Resultado) ja com a opcao escolhida aberta.
  const goNext = (m: NextMode) => {
    setTab("result");
    setMode(m);
    setTimeout(() => document.getElementById("next-steps")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  const flow: Flow = { mode, setMode, goNext };
  const cands = props.detail.snapshot.candidates ?? [];
  const team = (id: string) => {
    const i = cands.findIndex((c) => c.candidate_id === id);
    return { name: cands[i]?.name ?? id, color: cands[i]?.color ?? TEAM_COLORS[Math.max(0, i) % TEAM_COLORS.length] };
  };
  const refinement = props.detail.snapshot.refinement;
  return (
    <div className="results">
      {refinement && (
        <div className="refine-banner">
          <Icon name="edit" size={16} />
          <div>
            <strong>Repescagem {refinement.round}</strong> · seu feedback para{" "}
            {refinement.feedback.map((f, i) => (
              <span key={f.candidate_id}>
                {i > 0 && ", "}
                <span className="dot" style={{ background: team(f.candidate_id).color }} /> {team(f.candidate_id).name}: <em>“{f.comment}”</em>
              </span>
            ))}
            {refinement.general_comment && <div className="muted small">Geral: “{refinement.general_comment}”</div>}
            {cands.some((c) => !refinement.feedback.some((f) => f.candidate_id === c.candidate_id)) && (
              <div className="muted small">
                Fora da disputa:{" "}
                {cands
                  .filter((c) => !refinement.feedback.some((f) => f.candidate_id === c.candidate_id))
                  .map((c) => c.name)
                  .join(", ")}
              </div>
            )}
          </div>
        </div>
      )}
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
            <Icon name={t.icon} size={14} /> {t.label}
          </button>
        ))}
      </div>
      <div className="tab-body" key={tab}>
        {tab === "result" && <ResultTab {...props} team={team} flow={flow} />}
        {tab === "proposals" && <ProposalsTab {...props} team={team} flow={flow} />}
        {tab === "evaluation" && <EvaluationTab {...props} team={team} />}
        {tab === "costs" && <CostsTab {...props} team={team} />}
        {tab === "details" && <DetailsTab {...props} />}
      </div>
    </div>
  );
}
