"use client";

import type { Report, RunDetail } from "@/lib/api";
import { CHECK_LABEL, DECISION_LABEL, ELIGIBILITY_LABEL, money, num } from "@/lib/format";

type Props = { report: Report; detail: RunDetail; onEvidence: (id: string) => void };

const ELIG_CLASS: Record<string, string> = { eligible: "ok", ineligible: "bad", pending: "warn" };
const CHECK_CLASS: Record<string, string> = { pass: "ok", fail: "bad", unknown: "warn" };

export default function ResultsView({ report, detail, onEvidence }: Props) {
  const candidates = detail.snapshot.candidates ?? [];
  const nameOf = (id: string) => candidates.find((c) => c.candidate_id === id)?.name ?? id;
  const colorOf = (id: string) => candidates.find((c) => c.candidate_id === id)?.color ?? "#2563eb";
  const judges = detail.snapshot.judges ?? [];
  const panel = judges.length > 1;
  const criteria = (judges[0]?.rubric ?? detail.snapshot.rubric).criteria;
  const criteriaOf = (judgeId: string) => (judges.find((j) => j.judge_id === judgeId)?.rubric ?? detail.snapshot.rubric).criteria;
  const columns = panel
    ? judges.map((j) => ({ key: j.judge_id ?? j.name, title: j.name, sub: `peso ${j.weight}`, hint: j.instructions }))
    : criteria.map((c) => ({ key: c.criterion_id, title: c.name, sub: String(c.weight), hint: c.description }));
  const ranking = [...report.ranking].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || a.candidate_id.localeCompare(b.candidate_id));
  const finalProposals = report.proposals;
  const Chips = ({ ids }: { ids: string[] }) => (
    <span className="chips">
      {ids.map((id) => (
        <button key={id} className="chip" onClick={() => onEvidence(id)} title="ver trecho">
          {id}
        </button>
      ))}
    </span>
  );

  return (
    <div>
      <section className="panel">
        <div className="row spread">
          <h2 style={{ margin: 0 }}>Resultado</h2>
          <span className="row">
            <span className="badge accent">{DECISION_LABEL[report.decision_status] ?? report.decision_status}</span>
            {report.simulated && <span className="badge seal">SIMULADO</span>}
            {report.replay && <span className="badge seal">REPLAY</span>}
          </span>
        </div>
        {report.winner_candidate_id ? (
          <p>
            Primeiro colocado relativo: <strong>{nameOf(report.winner_candidate_id)}</strong> — não significa aprovação absoluta.
          </p>
        ) : report.co_leaders.length > 0 ? (
          <p>
            Co-liderança: <strong>{report.co_leaders.map(nameOf).join(", ")}</strong> (empate não é quebrado arbitrariamente).
          </p>
        ) : (
          <p>
            <strong>Sem vencedor validado.</strong>
          </p>
        )}
        <ul className="tight">
          {report.decision_reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Candidato</th>
              <th className="num">Score 0–100</th>
              <th>Elegibilidade</th>
              {columns.map((c) => (
                <th key={c.key} className="num" title={c.hint}>
                  {c.title} <span className="muted">({c.sub})</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ranking.map((e) => (
              <tr key={e.candidate_id} className={e.rank === 1 && e.eligibility === "eligible" ? "leader" : ""}>
                <td>
                  {e.rank ?? "–"}
                  {e.co_leader ? "*" : ""}
                </td>
                <td>
                  <span style={{ borderLeft: `4px solid ${colorOf(e.candidate_id)}`, paddingLeft: 6 }}>{e.candidate_name}</span>
                  {e.disqualification_reason && <div className="hint">{e.disqualification_reason}</div>}
                  {e.notes.map((n, i) => (
                    <div key={i} className="hint">
                      {n}
                    </div>
                  ))}
                </td>
                <td className="num">
                  <strong>{num(e.score_0_100)}</strong>
                </td>
                <td>
                  <span className={`badge ${ELIG_CLASS[e.eligibility]}`}>{ELIGIBILITY_LABEL[e.eligibility]}</span>
                </td>
                {panel
                  ? judges.map((j) => (
                      <td key={j.judge_id ?? j.name} className="num">
                        {num(e.judge_scores.find((s) => s.judge_id === j.judge_id)?.score_0_100)}
                      </td>
                    ))
                  : criteria.map((c) => (
                      <td key={c.criterion_id} className="num">
                        {num(e.grades[c.criterion_id], 1)}
                        {c.computed_by === "server_efficiency" && e.efficiency && (
                          <div className="hint">
                            {money(e.efficiency.cost, report.cost.currency)} / {money(e.efficiency.quota, report.cost.currency)}
                          </div>
                        )}
                      </td>
                    ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Verificações objetivas</h2>
        <div className="grid two">
          {report.verifications.map((v) => (
            <div key={v.candidate_id} className="card" style={{ borderLeftColor: colorOf(v.candidate_id) }}>
              <h3>
                {nameOf(v.candidate_id)} <span className="muted">v{v.proposal_version}</span> <span className={`badge ${ELIG_CLASS[v.eligibility]}`}>{ELIGIBILITY_LABEL[v.eligibility]}</span>
              </h3>
              {v.checks.map((c) => (
                <div key={c.constraint_id} style={{ marginBottom: 6 }}>
                  <span className={`badge ${CHECK_CLASS[c.result]}`}>{CHECK_LABEL[c.result]}</span> <code>{c.constraint_id}</code> {c.mandatory ? "" : "(não obrigatória)"}
                  <div className="hint">{c.reason}</div>
                  {c.evidence_ids.length > 0 && <Chips ids={c.evidence_ids} />}
                </div>
              ))}
              {v.invalid_evidence_ids.length > 0 && <div className="hint">Referências inexistentes removidas: {v.invalid_evidence_ids.join(", ")}</div>}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Propostas lado a lado</h2>
        <div className="grid two">
          {finalProposals.map((p) => (
            <div key={p.candidate_id} className="card" style={{ borderLeftColor: colorOf(p.candidate_id) }}>
              <h3>
                {nameOf(p.candidate_id)} <span className="muted">v{p.version}</span> {p.revised_from_critique && <span className="badge info">revisada após crítica</span>}
              </h3>
              <strong>{p.title}</strong>
              <p>{p.recommendation}</p>
              {Object.keys(p.metrics).length > 0 && (
                <>
                  <h3>Métricas declaradas</h3>
                  <ul className="tight">
                    {Object.entries(p.metrics).map(([k, m]) => (
                      <li key={k}>
                        <code>{k}</code> = {m.value} {m.unit} <Chips ids={m.evidence_ids} />
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {(
                [
                  ["Passos", p.steps],
                  ["Premissas", p.assumptions],
                  ["Trade-offs", p.tradeoffs],
                  ["Riscos", p.risks],
                  ["Pendências", p.open_items],
                ] as [string, string[]][]
              ).map(([title, items]) =>
                items.length ? (
                  <details key={title}>
                    <summary>
                      {title} ({items.length})
                    </summary>
                    <ul className="tight">
                      {items.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </details>
                ) : null,
              )}
              <div style={{ marginTop: 6 }}>
                <span className="hint">Evidências citadas:</span> <Chips ids={p.evidence_ids} />
                {p.invalid_evidence_ids.length > 0 && <div className="hint">IDs inválidos removidos: {p.invalid_evidence_ids.join(", ")}</div>}
              </div>
            </div>
          ))}
        </div>
      </section>

      {report.critiques.length > 0 && (
        <section className="panel">
          <h2 style={{ marginTop: 0 }}>Críticas cruzadas (anel determinístico)</h2>
          <div className="grid two">
            {report.critiques.map((c, i) => (
              <div key={i} className="card" style={{ borderLeftColor: colorOf(c.author_candidate_id) }}>
                <h3>
                  {nameOf(c.author_candidate_id)} → {nameOf(c.target_candidate_id)} <span className="muted">(v{c.target_version})</span>
                </h3>
                <ul className="tight">
                  {c.objections.map((o, j) => (
                    <li key={j}>
                      <span className={`badge ${o.severity === "high" ? "bad" : o.severity === "medium" ? "warn" : "info"}`}>{o.severity}</span> {o.point}{" "}
                      {o.constraint_id && <code>{o.constraint_id}</code>} <Chips ids={o.evidence_ids} />
                    </li>
                  ))}
                </ul>
                {c.strengths.length > 0 && <div className="hint">Pontos fortes: {c.strengths.join("; ")}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      {report.evaluations.length > 0 && (
        <section className="panel">
          <h2 style={{ marginTop: 0 }}>{panel ? "Avaliação dos juízes" : "Avaliação do Judge"}</h2>
          <p className="hint">Propostas anonimizadas e embaralhadas com seed {report.judge_shuffle_seed}; justificativas são resumos verificáveis, não cadeia de pensamento.</p>
          <div className="grid two">
            {report.evaluations.map((ev) => (
              <div key={`${ev.candidate_id}:${ev.judge_id}`} className="card" style={{ borderLeftColor: colorOf(ev.candidate_id) }}>
                <h3>
                  {nameOf(ev.candidate_id)} <span className="muted">({ev.judge_label})</span> {panel && <span className="badge accent">{ev.judge_name}</span>}
                </h3>
                <table>
                  <tbody>
                    {ev.grades.map((g) => (
                      <tr key={g.criterion_id}>
                        <td>{criteriaOf(ev.judge_id).find((c) => c.criterion_id === g.criterion_id)?.name ?? <code>{g.criterion_id}</code>}</td>
                        <td className="num">
                          <strong>{num(g.grade, 1)}</strong>
                        </td>
                        <td>
                          {g.justification} <Chips ids={g.evidence_ids} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {ev.objections.length > 0 && <div className="hint">Objeções: {ev.objections.join("; ")}</div>}
                {ev.uncertainties.length > 0 && <div className="hint">Incertezas: {ev.uncertainties.join("; ")}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Consumo</h2>
        <dl className="kv">
          <dt>Total da arena</dt>
          <dd>
            {money(report.cost.total, report.cost.currency)} <span className="badge info">{report.cost.quality}</span> · {report.cost.calls_used}/{report.cost.calls_cap} chamadas · teto{" "}
            {report.cost.cap ? money(report.cost.cap, report.cost.currency) : "sem teto"} ({report.cost.strict ? "estrito" : "indicativo"})
          </dd>
          <dt>Comum (preparação + Judge)</dt>
          <dd>
            {money(report.cost.common, report.cost.currency)} · Judge {money(report.cost.judge, report.cost.currency)}
          </dd>
          {Object.entries(report.cost.per_candidate).map(([cid, v]) => (
            <dt key={cid} style={{ display: "contents" }}>
              <span className="muted">{nameOf(cid)}</span>
              <span>{money(v, report.cost.currency)}</span>
            </dt>
          ))}
          {Number(report.cost.pending_unknown_reserved) > 0 && (
            <>
              <dt>Reservas pendentes (consumo desconhecido)</dt>
              <dd className="badge warn">{money(report.cost.pending_unknown_reserved, report.cost.currency)}</dd>
            </>
          )}
        </dl>
        {Object.keys(report.diversity_observed).length > 0 && (
          <p className="hint">
            Diversidade observada:{" "}
            {Object.entries(report.diversity_observed)
              .map(([p, ms]) => `${p}: ${ms.join(", ")}`)
              .join(" · ")}
          </p>
        )}
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Limitações, mudanças operacionais e lacunas</h2>
        <ul className="tight">
          {report.limitations.map((l, i) => (
            <li key={`l${i}`}>{l}</li>
          ))}
          {report.operational_changes.map((o, i) => (
            <li key={`o${i}`}>
              <span className="badge info">operacional</span> {o}
            </li>
          ))}
          {report.evidence_gaps.map((g, i) => (
            <li key={`g${i}`}>
              <span className="badge warn">lacuna</span> {g}
            </li>
          ))}
        </ul>
        <h3>Próximos passos</h3>
        <ul className="tight">
          {report.next_steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
