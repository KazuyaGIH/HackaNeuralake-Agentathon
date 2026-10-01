"use client";

import Icon from "../Icon";
import { STAGES, initial, progressPct, type LiveState } from "./live";

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `US$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
}

export function Stepper({ live, compact = false }: { live: LiveState; compact?: boolean }) {
  return (
    <div className={`stepper ${compact ? "compact" : ""}`}>
      {STAGES.filter((s) => live.stages[s.key] !== "skipped").map((s, i, arr) => {
        const st = live.stages[s.key];
        return (
          <div key={s.key} className={`step-node ${st}`}>
            <div className="step-dot">
              {st === "done" ? <Icon name="check" size={13} /> : st === "fail" ? <Icon name="x" size={13} /> : <span>{i + 1}</span>}
            </div>
            <div className="step-label">{s.label}</div>
            {i < arr.length - 1 && <div className="step-line" />}
          </div>
        );
      })}
    </div>
  );
}

export default function LiveView({ live, paced }: { live: LiveState; paced: boolean }) {
  const pct = progressPct(live);
  const stage = STAGES.find((s) => s.key === live.current);
  const feed = live.feed.slice(-7).reverse();

  return (
    <div className="live">
      <div className="panel live-head">
        <div className="live-status">
          <div className="orb">
            <span />
            <span />
            <span />
          </div>
          <div>
            <div className="eyebrow">{paced ? "Reproduzindo a execução" : "Em andamento"}</div>
            <div className="live-title">
              {stage?.running ?? "Preparando"}
              <span className="dots">
                <i />
                <i />
                <i />
              </span>
            </div>
          </div>
          <div className="live-stats">
            <div>
              <span>Gasto</span>
              <strong>{fmtUsd(live.spent)}</strong>
            </div>
            <div>
              <span>Chamadas de IA</span>
              <strong>
                {live.calls}
                <em> / {live.callsCap}</em>
              </strong>
            </div>
          </div>
        </div>
        <div className="live-progress">
          <div style={{ width: `${pct}%` }} />
        </div>
        <Stepper live={live} />
      </div>

      <div className="live-grid">
        <div className="lanes">
          {live.lanes.map((l) => {
            const pctSpent = l.cap ? Math.min(100, ((l.spent ?? 0) / l.cap) * 100) : null;
            return (
              <div key={l.id} className={`lane ${l.working ? "working" : ""}`} style={{ ["--team" as string]: l.color }}>
                <div className="lane-head">
                  <div className="lane-avatar">{initial(l.name)}</div>
                  <div className="lane-name">
                    <strong>{l.name}</strong>
                    <span>
                      {l.model}
                      {l.secondary ? ` + ${l.secondary}` : ""}
                    </span>
                  </div>
                  {l.eligibility && (
                    <span className={`badge ${l.eligibility === "eligible" ? "ok" : l.eligibility === "ineligible" ? "bad" : "warn"}`}>
                      {l.eligibility === "eligible" ? "Cumpre as regras" : l.eligibility === "ineligible" ? "Desclassificada" : "Sem prova"}
                    </span>
                  )}
                </div>
                <div className="lane-activity" key={l.activity}>
                  {l.working && <span className="spinner" />}
                  <span>{l.activity}</span>
                </div>
                {l.detail && (
                  <div className="lane-detail">
                    {l.tier === "secondary" && <span className="model-chip second">econômico</span>}
                    {l.tier === "main" && <span className="model-chip main">principal</span>}
                    <span>{l.detail}</span>
                  </div>
                )}
                <div className="lane-foot">
                  <div className="lane-bar">{pctSpent !== null && <div style={{ width: `${pctSpent}%` }} />}</div>
                  <span>{fmtUsd(l.spent ?? 0)}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="panel feed">
          <h3 className="panel-title">Atividade</h3>
          <ul>
            {feed.map((f) => (
              <li key={f.seq} className={`feed-item ${f.tone}`}>
                <span className="feed-dot" style={f.color ? { background: f.color } : undefined} />
                <span className="feed-text">{f.text}</span>
                <span className="feed-time">{new Date(f.ts).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
              </li>
            ))}
            {feed.length === 0 && <li className="feed-item muted">Aguardando o primeiro evento…</li>}
          </ul>
        </div>
      </div>
    </div>
  );
}
