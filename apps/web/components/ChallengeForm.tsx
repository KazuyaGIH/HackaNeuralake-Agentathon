"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type CandidateConfig, type CatalogResponse, type ChallengeConfig, type Constraint, type SourceCreateResponse } from "@/lib/api";

const PREFILL_KEY = "agentathon:prefill";

function emptyConfig(catalog: CatalogResponse | null): ChallengeConfig {
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
    critique_rounds: 1,
    seed: null,
    mock_scenario: "default",
    tags: [],
  };
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
    allowed_specialists: preset.allowed_specialists as CandidateConfig["allowed_specialists"],
    max_specialist_tasks: preset.max_specialist_tasks,
    max_output_tokens: 2000,
    quota_weight: "1",
    color: null,
  };
}

export default function ChallengeForm() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [cfg, setCfg] = useState<ChallengeConfig>(() => emptyConfig(null));
  const [sources, setSources] = useState<SourceCreateResponse[]>([]);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .catalog()
      .then((c) => {
        setCatalog(c);
        const raw = typeof window !== "undefined" ? window.sessionStorage.getItem(PREFILL_KEY) : null;
        if (raw) {
          window.sessionStorage.removeItem(PREFILL_KEY);
          const pre = JSON.parse(raw) as { challenge: ChallengeConfig; sources?: SourceCreateResponse[] };
          setCfg({ ...pre.challenge, seed: null });
          setSources(pre.sources ?? []);
          setNotice("Configuração duplicada de uma execução anterior. Revise e inicie uma nova arena (novo orçamento).");
        } else {
          setCfg(emptyConfig(c));
        }
      })
      .catch((e: Error) => setError({ message: `Não foi possível carregar o catálogo do servidor: ${e.message}` }));
  }, []);

  const enabledOptions = useMemo(() => (catalog?.model_options ?? []).filter((m) => m.enabled), [catalog]);
  const weightSum = useMemo(() => cfg.rubric.criteria.reduce((s, c) => s + Number(c.weight || 0), 0), [cfg.rubric]);
  const realAvailable = catalog?.providers?.neuralake?.enabled === true;

  const update = (patch: Partial<ChallengeConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const updateBudget = (patch: Partial<ChallengeConfig["budget"]>) => setCfg((c) => ({ ...c, budget: { ...c.budget, ...patch } }));

  async function loadDemo() {
    setBusy(true);
    setError(null);
    try {
      const demo = await api.demoPrepare();
      setCfg({ ...demo.challenge, candidates: null, judge: null });
      const list: SourceCreateResponse[] = demo.challenge.source_ids.map((id, i) => ({
        source_id: id, title: demo.documents[i] ?? id, media_type: "text/markdown", size_bytes: 0, sha256: "", extraction_status: "ok", pages: null, chars: 0, warnings: [],
      }));
      setSources(list);
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
      for (const f of Array.from(files)) {
        const src = await api.uploadFile(f);
        setSources((s) => (s.some((x) => x.source_id === src.source_id) ? s : [...s, src]));
        setCfg((c) => (c.source_ids.includes(src.source_id) ? c : { ...c, source_ids: [...c.source_ids, src.source_id] }));
      }
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, hint: err.hint });
    } finally {
      setBusy(false);
    }
  }

  async function onPaste() {
    if (!pasteText.trim()) return;
    setBusy(true);
    try {
      const src = await api.uploadText(pasteTitle || "texto colado", pasteText);
      setSources((s) => (s.some((x) => x.source_id === src.source_id) ? s : [...s, src]));
      setCfg((c) => (c.source_ids.includes(src.source_id) ? c : { ...c, source_ids: [...c.source_ids, src.source_id] }));
      setPasteText("");
      setPasteTitle("");
    } catch (e) {
      setError({ message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  function removeSource(id: string) {
    setSources((s) => s.filter((x) => x.source_id !== id));
    update({ source_ids: cfg.source_ids.filter((x) => x !== id) });
  }

  function setConstraint(i: number, patch: Partial<Constraint>) {
    const next = cfg.constraints.map((c, idx) => (idx === i ? { ...c, ...patch } : c));
    update({ constraints: next });
  }

  function switchConfigMode(mode: "auto" | "manual") {
    if (!catalog) return;
    if (mode === "manual") {
      const n = cfg.candidate_count ?? 2;
      const cands = cfg.candidates && cfg.candidates.length >= 2 ? cfg.candidates : Array.from({ length: n }, (_, i) => defaultCandidate(i, catalog, cfg.mode));
      update({ config_mode: "manual", candidates: cands });
    } else {
      update({ config_mode: "auto", candidates: null });
    }
  }

  function setCandidate(i: number, patch: Partial<CandidateConfig>) {
    const cands = (cfg.candidates ?? []).map((c, idx) => (idx === i ? { ...c, ...patch } : c));
    update({ candidates: cands });
  }

  function applyPreset(i: number, presetName: string) {
    const preset = catalog?.presets.find((p) => p.preset === presetName);
    if (!preset) return setCandidate(i, { preset: null });
    const cand = (cfg.candidates ?? [])[i];
    setCandidate(i, {
      preset: preset.preset as CandidateConfig["preset"],
      instructions: preset.instructions,
      model_option: preset.model_option_by_provider[cand.provider] ?? cand.model_option,
      allowed_specialists: preset.allowed_specialists as CandidateConfig["allowed_specialists"],
      max_specialist_tasks: preset.max_specialist_tasks,
    });
  }

  function switchMode(mode: "mock" | "real") {
    const provider = mode === "mock" ? "mock" : "neuralake";
    const cands = cfg.candidates?.map((c) => {
      const preset = catalog?.presets.find((p) => p.preset === c.preset);
      return { ...c, provider: provider as CandidateConfig["provider"], model_option: preset?.model_option_by_provider[provider] ?? (mode === "mock" ? "mock-default" : "auto") };
    });
    update({ mode, candidates: cands ?? null, judge: null, mock_scenario: "default" });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const payload: ChallengeConfig = { ...cfg, title: cfg.title || null, seed: cfg.seed === null || (cfg.seed as unknown) === "" ? null : Number(cfg.seed) };
      if (payload.config_mode === "auto") payload.candidates = null;
      const key = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
      const res = await api.createRun(payload, key);
      router.push(`/runs/${res.run_id}`);
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, hint: err.hint });
      setBusy(false);
    }
  }

  if (!catalog && !error) return <p className="muted">Carregando catálogo…</p>;

  return (
    <div>
      {notice && <div className="notice">{notice}</div>}
      {error && (
        <div className="error">
          <strong>Erro:</strong> {error.message}
          {error.hint && <div className="hint">{error.hint}</div>}
        </div>
      )}

      <section className="panel">
        <div className="row spread">
          <h2 style={{ margin: 0 }}>1. Desafio</h2>
          <button onClick={loadDemo} disabled={busy}>
            Carregar exemplo (SIMULADO)
          </button>
        </div>
        <div className="field">
          <label>Título (opcional)</label>
          <input value={cfg.title ?? ""} onChange={(e) => update({ title: e.target.value })} />
        </div>
        <div className="field">
          <label>Problema / objetivo *</label>
          <textarea value={cfg.objective} onChange={(e) => update({ objective: e.target.value })} placeholder="O que precisa ser decidido? Mínimo de 10 caracteres." />
        </div>
        <div className="field">
          <label>Contexto</label>
          <textarea value={cfg.context ?? ""} onChange={(e) => update({ context: e.target.value })} />
        </div>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>2. Evidências (anexos)</h2>
        <p className="hint">
          TXT, Markdown ou PDF com camada textual · até {catalog?.limits?.sources?.max ?? 5} fontes, {catalog?.limits?.sources?.max_upload_mb ?? 10} MiB cada,{" "}
          {catalog?.limits?.sources?.max_pdf_pages ?? 100} páginas por PDF. PDFs digitalizados exigem OCR (fora do MVP) e são rejeitados na validação.
        </p>
        <div className="grid two">
          <div>
            <label>Upload de arquivos</label>
            <input type="file" multiple accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf" onChange={(e) => onUpload(e.target.files)} disabled={busy} />
          </div>
          <div>
            <label>Texto colado</label>
            <input placeholder="Título" value={pasteTitle} onChange={(e) => setPasteTitle(e.target.value)} />
            <textarea placeholder="Cole aqui o conteúdo" value={pasteText} onChange={(e) => setPasteText(e.target.value)} style={{ marginTop: 6 }} />
            <button className="small" onClick={onPaste} disabled={busy || !pasteText.trim()} style={{ marginTop: 6 }}>
              Adicionar texto
            </button>
          </div>
        </div>
        <div className="chips" style={{ marginTop: 10 }}>
          {sources.length === 0 && <span className="muted">Nenhuma fonte anexada: as propostas dependerão de hipóteses explícitas.</span>}
          {sources.map((s) => (
            <span key={s.source_id} className={`chip ${s.extraction_status !== "ok" ? "bad" : ""}`} title={s.warnings.join("; ")}>
              {s.title} {s.chars ? `· ${s.chars} chars` : ""} {s.extraction_status !== "ok" ? `· ${s.extraction_status}` : ""}{" "}
              <button className="small" onClick={() => removeSource(s.source_id)} style={{ marginLeft: 6 }}>
                ×
              </button>
            </span>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="row spread">
          <h2 style={{ margin: 0 }}>3. Restrições obrigatórias (tipadas)</h2>
          <button
            className="small"
            onClick={() => update({ constraints: [...cfg.constraints, { constraint_id: `restricao_${cfg.constraints.length + 1}`, description: "", kind: "numeric_max", metric_key: "", limit: "0", unit: "", mandatory: true }] })}
          >
            + restrição
          </button>
        </div>
        <p className="hint">
          Restrições numéricas exigem que a proposta declare a métrica com unidade e evidência que sustente o valor; alegação sem prova vira <em>unknown</em> (candidatura pendente).
          Restrições qualitativas não têm verificador objetivo: se obrigatórias, o resultado será sempre <em>unknown</em>.
        </p>
        {cfg.constraints.map((c, i) => (
          <div key={i} className="inline" style={{ marginBottom: 8, alignItems: "end" }}>
            <div>
              <label>ID</label>
              <input value={c.constraint_id} onChange={(e) => setConstraint(i, { constraint_id: e.target.value })} />
            </div>
            <div style={{ gridColumn: "span 2" }}>
              <label>Descrição</label>
              <input value={c.description} onChange={(e) => setConstraint(i, { description: e.target.value })} />
            </div>
            <div>
              <label>Tipo</label>
              <select value={c.kind} onChange={(e) => setConstraint(i, { kind: e.target.value as Constraint["kind"] })}>
                <option value="numeric_max">máximo numérico</option>
                <option value="numeric_min">mínimo numérico</option>
                <option value="qualitative">qualitativa</option>
              </select>
            </div>
            {c.kind !== "qualitative" && (
              <>
                <div>
                  <label>Métrica (chave)</label>
                  <input value={c.metric_key ?? ""} onChange={(e) => setConstraint(i, { metric_key: e.target.value })} placeholder="monthly_cost_brl" />
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
              <label>Obrigatória</label>
              <input type="checkbox" checked={c.mandatory} onChange={(e) => setConstraint(i, { mandatory: e.target.checked })} />
            </div>
            <div>
              <button className="small danger" onClick={() => update({ constraints: cfg.constraints.filter((_, idx) => idx !== i) })}>
                remover
              </button>
            </div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="row spread">
          <h2 style={{ margin: 0 }}>4. Rubrica do Judge</h2>
          <span className={`badge ${weightSum === 100 ? "ok" : "bad"}`}>soma dos pesos: {weightSum} / 100</span>
        </div>
        <p className="hint">Notas de 0 a 10 por critério; score = Σ(peso × nota) / 10. O critério de eficiência é calculado pelo servidor (consumo/cota) e exige teto de orçamento.</p>
        <table>
          <thead>
            <tr>
              <th>Critério</th>
              <th>Descrição</th>
              <th className="num">Peso</th>
              <th>Avaliado por</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cfg.rubric.criteria.map((c, i) => (
              <tr key={c.criterion_id}>
                <td>
                  <strong>{c.name}</strong>
                  <div className="mono muted">{c.criterion_id}</div>
                </td>
                <td className="muted">{c.description}</td>
                <td className="num" style={{ width: 90 }}>
                  <input
                    value={String(c.weight)}
                    onChange={(e) => update({ rubric: { ...cfg.rubric, criteria: cfg.rubric.criteria.map((x, idx) => (idx === i ? { ...x, weight: e.target.value } : x)) } })}
                  />
                </td>
                <td>{c.computed_by === "server_efficiency" ? <span className="badge info">servidor</span> : <span className="badge accent">Judge</span>}</td>
                <td>
                  <button className="small" onClick={() => update({ rubric: { ...cfg.rubric, criteria: cfg.rubric.criteria.filter((_, idx) => idx !== i) } })}>
                    remover
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>5. Modo, orçamento e limites</h2>
        <div className="inline">
          <div>
            <label>Modo de execução</label>
            <select value={cfg.mode} onChange={(e) => switchMode(e.target.value as "mock" | "real")}>
              <option value="mock">Simulado (mock, sem rede)</option>
              <option value="real" disabled={!realAvailable}>
                Real — NeuraLake {realAvailable ? "" : "(indisponível)"}
              </option>
            </select>
            {!realAvailable && <div className="hint">{catalog?.providers?.neuralake?.unavailable_reason}</div>}
          </div>
          {cfg.mode === "mock" && (
            <div>
              <label>Cenário simulado</label>
              <select value={cfg.mock_scenario} onChange={(e) => update({ mock_scenario: e.target.value })}>
                {catalog?.mock_scenarios.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label>Teto monetário ({cfg.budget.currency})</label>
            <input value={cfg.budget.total_cap ?? ""} onChange={(e) => updateBudget({ total_cap: e.target.value || null })} placeholder="ex.: 1.00" />
          </div>
          <div>
            <label>Cota comum (%)</label>
            <input value={String(cfg.budget.common_share_pct)} onChange={(e) => updateBudget({ common_share_pct: e.target.value })} />
          </div>
          <div>
            <label>Orçamento estrito</label>
            <input type="checkbox" checked={cfg.budget.strict} onChange={(e) => updateBudget({ strict: e.target.checked })} />
            <div className="hint">Estrito bloqueia chamadas sem cobertura; exige preços conhecidos.</div>
          </div>
        </div>
        <div className="inline" style={{ marginTop: 8 }}>
          <div>
            <label>Limite de chamadas (total)</label>
            <input type="number" min={4} max={32} value={cfg.budget.max_total_calls} onChange={(e) => updateBudget({ max_total_calls: Number(e.target.value) })} />
          </div>
          <div>
            <label>Chamadas simultâneas</label>
            <input type="number" min={1} max={4} value={cfg.budget.max_concurrent_calls} onChange={(e) => updateBudget({ max_concurrent_calls: Number(e.target.value) })} />
          </div>
          <div>
            <label>Prazo da execução (s)</label>
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
            <label>Rodadas de crítica/revisão</label>
            <select value={cfg.critique_rounds} onChange={(e) => update({ critique_rounds: Number(e.target.value) })}>
              <option value={0}>0</option>
              <option value={1}>1</option>
            </select>
          </div>
          <div>
            <label>Seed (opcional)</label>
            <input value={cfg.seed ?? ""} onChange={(e) => update({ seed: e.target.value === "" ? null : (Number(e.target.value) as unknown as number) })} />
          </div>
        </div>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>6. Participantes</h2>
        <p className="hint">
          <strong>Número de candidatos</strong> (equipes concorrentes, 2–4) é diferente de <strong>especialistas disponíveis</strong> ({(catalog?.specialists ?? []).map((s) => s.label).join(", ")}) e do{" "}
          <strong>limite de chamadas</strong> (teto total de inferência da execução, não um objetivo de consumo).
        </p>
        <div className="row">
          <label style={{ margin: 0 }}>
            <input type="radio" checked={cfg.config_mode === "auto"} onChange={() => switchConfigMode("auto")} /> Automático (presets escolhem estratégias e especialistas no catálogo fixo)
          </label>
          <label style={{ margin: 0 }}>
            <input type="radio" checked={cfg.config_mode === "manual"} onChange={() => switchConfigMode("manual")} /> Manual (fixar participantes, modelos e instruções)
          </label>
        </div>
        {cfg.config_mode === "auto" ? (
          <div className="inline" style={{ marginTop: 10 }}>
            <div>
              <label>Número de candidatos</label>
              <select value={cfg.candidate_count} onChange={(e) => update({ candidate_count: Number(e.target.value) })}>
                {[2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <div className="hint" style={{ alignSelf: "end" }}>
              Presets em ordem: {catalog?.presets.map((p) => p.label).join(" → ")}. Seleção limitada ao catálogo (P0); contratação dinâmica é P1.
            </div>
          </div>
        ) : (
          <div className="grid two" style={{ marginTop: 10 }}>
            {(cfg.candidates ?? []).map((c, i) => (
              <div key={i} className="card" style={{ borderLeftColor: c.color ?? "#2563eb" }}>
                <div className="row spread">
                  <input value={c.name} onChange={(e) => setCandidate(i, { name: e.target.value })} style={{ fontWeight: 600 }} />
                  <button className="small danger" disabled={(cfg.candidates?.length ?? 0) <= 2} onClick={() => update({ candidates: (cfg.candidates ?? []).filter((_, idx) => idx !== i) })}>
                    remover
                  </button>
                </div>
                <div className="inline" style={{ marginTop: 8 }}>
                  <div>
                    <label>Preset</label>
                    <select value={c.preset ?? ""} onChange={(e) => applyPreset(i, e.target.value)}>
                      <option value="">(personalizado)</option>
                      {catalog?.presets.map((p) => (
                        <option key={p.preset} value={p.preset}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label>Provedor / opção</label>
                    <select
                      value={`${c.provider}|${c.model_option}`}
                      onChange={(e) => {
                        const [provider, option] = e.target.value.split("|");
                        setCandidate(i, { provider: provider as CandidateConfig["provider"], model_option: option });
                      }}
                    >
                      {enabledOptions
                        .filter((m) => (cfg.mode === "mock" ? m.provider === "mock" : m.provider !== "mock"))
                        .map((m) => (
                          <option key={`${m.provider}|${m.option}`} value={`${m.provider}|${m.option}`}>
                            {m.label} {m.kind === "routing_capability" ? "· roteamento" : ""} {m.price_known ? "" : "· preço desconhecido"}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <label>Tarefas especializadas (máx.)</label>
                    <input type="number" min={0} max={2} value={c.max_specialist_tasks} onChange={(e) => setCandidate(i, { max_specialist_tasks: Number(e.target.value) })} />
                  </div>
                </div>
                <div className="field" style={{ marginTop: 8 }}>
                  <label>Instruções estratégicas (privadas; não vão ao Judge)</label>
                  <textarea value={c.instructions ?? ""} onChange={(e) => setCandidate(i, { instructions: e.target.value, preset: null })} />
                </div>
                <div className="row">
                  {(catalog?.specialists ?? []).map((s) => (
                    <label key={String(s.kind)} style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={(c.allowed_specialists ?? []).includes(s.kind as never)}
                        onChange={(e) => {
                          const set = new Set(c.allowed_specialists ?? []);
                          if (e.target.checked) set.add(s.kind as never);
                          else set.delete(s.kind as never);
                          setCandidate(i, { allowed_specialists: Array.from(set) as CandidateConfig["allowed_specialists"] });
                        }}
                      />{" "}
                      {s.label}
                    </label>
                  ))}
                </div>
              </div>
            ))}
            {(cfg.candidates?.length ?? 0) < 4 && catalog && (
              <button onClick={() => update({ candidates: [...(cfg.candidates ?? []), defaultCandidate(cfg.candidates?.length ?? 0, catalog, cfg.mode)] })}>+ candidato</button>
            )}
          </div>
        )}
        <div className="inline" style={{ marginTop: 12 }}>
          <div>
            <label>Judge — provedor / opção</label>
            <select
              value={cfg.judge ? `${cfg.judge.provider}|${cfg.judge.model_option}` : ""}
              onChange={(e) => {
                if (!e.target.value) return update({ judge: null });
                const [provider, option] = e.target.value.split("|");
                update({ judge: { provider: provider as CandidateConfig["provider"], model_option: option, max_output_tokens: 3000 } });
              }}
            >
              <option value="">(padrão do modo)</option>
              {enabledOptions
                .filter((m) => (cfg.mode === "mock" ? m.provider === "mock" : m.provider !== "mock"))
                .map((m) => (
                  <option key={`${m.provider}|${m.option}`} value={`${m.provider}|${m.option}`}>
                    {m.label}
                  </option>
                ))}
            </select>
          </div>
        </div>
      </section>

      <div className="row spread">
        <span className="hint">Ao iniciar, a configuração é validada e congelada (snapshot com hashes). Critérios não podem ser alterados durante a execução.</span>
        <button className="primary" onClick={submit} disabled={busy || cfg.objective.trim().length < 10 || weightSum !== 100}>
          {busy ? "Enviando…" : "Iniciar arena"}
        </button>
      </div>
    </div>
  );
}
