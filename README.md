# Agentathon — MVP P0

Plataforma que executa um **hackathon entre equipes de agentes de IA**: recebe um desafio (objetivo, evidências,
restrições tipadas, rubrica e orçamento), gera propostas concorrentes, permite uma rodada limitada de crítica e
revisão, executa verificações objetivas, submete as propostas anonimizadas a um Judge com rubrica fixa e calcula o
ranking em código, com trilha de execução e consumo rastreáveis. Entrega apoio à decisão; **não executa** a proposta
vencedora. A especificação completa está em [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Estado honesto do que existe

| Área | Situação |
|---|---|
| Fluxo completo ponta a ponta em **modo simulado** (evidências → pensantes → delegação → barreira única de sincronização → propostas → crítica em anel → revisão → verificadores → Judge anônimo → ranking → relatório) | **Pronto e testado** (60 testes automatizados; `scripts/smoke_mock.py`; cliente agente; smoke de UI com Playwright). |
| API completa (catálogo, fontes, runs, SSE com reconexão, cancelamento, relatório JSON/Markdown, retry, OpenAPI) | **Pronta e testada.** |
| Controles críticos: reserva atômica de orçamento, limites de chamadas/tempo/tentativas, idempotência, `interrupted` em reinício, cancelamento honesto, autorização por proprietário, isolamento do Judge, sanitização de eventos | **Prontos e testados** (seção "Critérios de aceite" abaixo). |
| Interface Next.js (configurar, acompanhar por eventos reais, comparar, histórico, exportar) | **Pronta**; validada em build de produção + smoke automatizado no Chromium. |
| **Adaptador NeuraLake** (OpenAI-compatible, erros tipados, reparação, usage, modelo informado, preços versionados, teto para `auto`) | **Implementado e testado sem rede** (servidor HTTP falso). **Teste real PENDENTE**: não há `AGENTATHON_NEURALAKE_API_KEY` neste ambiente. A demo real só pode ser declarada validada após uma execução real registrada (`scripts/smoke_real.py`). |
| Docker Compose | Arquivos prontos; **não verificados** (Docker indisponível nesta máquina). |
| Cross Memory (NeuraLake), segundo provedor, baseline de agente único, ledger de créditos, A2A/MCP | **Não implementados** (P1/futuro, conforme o escopo). |

Tudo que é simulado leva o selo **SIMULADO** (no conteúdo do mock, no relatório, na UI e no Markdown). Custos em modo
simulado usam uma tabela de preços fictícia (`mock-prices-v1`) e não comprovam a integração real.

## Como rodar em modo simulado (sem chaves)

Requisitos: Python 3.12+ (testado com 3.13), Node 20+ (testado com 24). Windows/PowerShell nos exemplos; em bash troque
`.venv\Scripts\python.exe` por `.venv/bin/python`.

```powershell
# backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/api/requirements.lock.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api
# -> http://127.0.0.1:8000/docs (OpenAPI) · GET /health não chama modelo

# frontend (outro terminal)
cd apps/web
npm ci
npm run dev        # http://localhost:3000  (NEXT_PUBLIC_API_BASE_URL default http://127.0.0.1:8000)
```

Na UI, clique em **Carregar exemplo (SIMULADO)** e depois em **Iniciar arena**. O banco SQLite e os anexos ficam em
`./data` (configurável por `AGENTATHON_DATA_DIR`). Migrações Alembic rodam automaticamente na inicialização.

### Cliente agente (jornada sem navegador)

```powershell
.venv\Scripts\python.exe examples/agent_client.py --base-url http://127.0.0.1:8000 --out data/relatorio.md
# fontes próprias: --file caminho.pdf --file notas.md --objective "..."
```

Equivalente em cURL:

```bash
curl -s http://127.0.0.1:8000/api/v1/catalog | head -c 400
curl -s -X POST http://127.0.0.1:8000/api/v1/demo/prepare > demo.json            # fontes sintéticas + configuração pronta
python -c "import json;print(json.dumps(json.load(open('demo.json'))['challenge']))" > challenge.json
curl -s -X POST -H 'Content-Type: application/json' -H 'Idempotency-Key: exemplo-1' \
     --data @challenge.json http://127.0.0.1:8000/api/v1/runs                      # 202 {run_id, links}
curl -s http://127.0.0.1:8000/api/v1/runs/<run_id>                                 # snapshot, status, artefatos, métricas
curl -N http://127.0.0.1:8000/api/v1/runs/<run_id>/events                          # SSE (Last-Event-ID para reconectar)
curl -s "http://127.0.0.1:8000/api/v1/runs/<run_id>/report?format=md"
```

Upload de fontes: `POST /api/v1/sources` (multipart `file` TXT/MD/PDF textual, ou campo `text`) e `POST /api/v1/sources/text`
(JSON). Limites: 5 fontes por desafio, 10 MiB por arquivo, 100 páginas por PDF; PDF sem camada textual é marcado
`needs_ocr` e rejeitado na validação do desafio (OCR fora do MVP).

### Cenários simulados (`mock_scenario`)

`default` (roteiro da demo), `unauthorized_specialist`, `judge_invalid_then_valid`, `judge_fails`,
`transient_error_once`, `timeout_unknown_usage`, `tie`, `all_ineligible`, `insufficient_evidence`. O mock é
determinístico (mesma entrada + seed ⇒ mesmos artefatos) e **ancorado nas evidências reais** do pacote: as métricas
declaradas vêm de números presentes nos trechos, por isso o roteiro (crítica aponta violação de restrição na v1 do
segundo candidato; revisão corrige) emerge das regras e não de respostas gravadas.

## Integração real (NeuraLake) — configurável, teste real pendente

1. Copie `.env.example` para `.env` e preencha `AGENTATHON_NEURALAKE_API_KEY` (somente no backend; nunca vai ao
   frontend, aos modelos, aos logs ou aos eventos).
2. Preços: por padrão o backend carrega `fixtures/prices/neuralake.public-2026-09-30.json` (tabela pública consultada em
   30/09/2026, **estimativa, não fatura**; `auto` é reservado pelo teto das rotas). Aponte
   `AGENTATHON_NEURALAKE_PRICES_FILE` para uma tabela própria quando confirmar os preços no ambiente. Sem preço conhecido,
   o modo de orçamento **estrito** é bloqueado (`price_unknown`); `budget.strict=false` permite orçamento indicativo
   mantendo limites de tokens/chamadas/tempo.
3. Reinicie o backend: `GET /api/v1/catalog` passa a listar `modes: ["mock","real"]` e o seletor da UI habilita "Real".
4. Smoke real (gasta tokens; exige confirmação explícita):
   ```powershell
   .venv\Scripts\python.exe scripts/smoke_real.py --confirm-spend            # 1 chamada mínima (text)
   .venv\Scripts\python.exe scripts/smoke_real.py --confirm-spend --full --cap 0.20   # arena real mínima, relatório em data/
   ```
Sem credencial, `POST /runs` em modo real devolve `422 provider_unavailable` com instrução acionável e **não troca
para mock**. Em modo real, `response_format=json_object` fica desativado (`AGENTATHON_NEURALAKE_JSON_MODE=false`) porque a
compatibilidade não foi confirmada; o backend valida o JSON e permite uma reparação por chamada lógica.

Itens a confirmar no ambiente real antes de declarar compatibilidade testada: parâmetros aceitos, formato de `usage`,
campo `model` efetivo, request id, limites de contexto por capacidade e comportamento do roteador `auto`.

## Testes e verificação

```powershell
.venv\Scripts\python.exe -m pytest -q                 # 60 testes (unitários, orçamento, fluxo, controles de API, NeuraLake sem rede)
cd apps/web; npm run typecheck; npm run build         # tipos gerados + build de produção
node scripts/ui_smoke.mjs http://127.0.0.1:3000       # smoke de UI (requer playwright + chromium instalados)
.venv\Scripts\python.exe scripts/smoke_mock.py        # fluxo simulado in-process com saída do relatório
```

Regenerar tipos do frontend a partir dos contratos Pydantic: `python -m app.export_openapi` (em `apps/api`) e
`npm run gen:types` (em `apps/web`).

### Critérios de aceite (ARCHITECTURE.md §19) → testes

| Critério | Teste |
|---|---|
| Mesmo input + seed ⇒ mesmos artefatos, sem chamada externa | `test_same_input_same_seed_is_deterministic` |
| 2–4 candidatos, modelos e instruções refletidos | `test_candidate_count_models_and_instructions_reflected` |
| Especialista não autorizado rejeitado por regra | `test_unauthorized_specialist_is_rejected_by_rule` |
| Reserva atômica impede soma além do saldo | `test_parallel_reservations_cannot_exceed_balance` |
| Timeout com consumo desconhecido ⇒ reserva pendente, erro visível, inconclusivo | `test_timeout_with_unknown_usage_keeps_reservation_pending`, `test_reconcile_known_unknown_and_release` |
| Erro transitório/resposta inválida ⇒ no máximo uma tentativa extra, contabilizada | `test_transient_error_retries_at_most_once`, `test_judge_out_of_range_rejected_then_repaired` |
| Restrição obrigatória falha ⇒ inelegível mesmo com nota alta | `test_mandatory_constraint_failure_makes_ineligible`, `test_ranking_ineligible_even_with_high_grade` |
| Restrição sem evidência ⇒ pendente/inconclusivo | `test_constraint_without_evidence_is_pending_inconclusive`, `test_qualitative_mandatory_constraint_warns_and_pends` |
| Judge fora de faixa / critério ausente rejeitado | `test_grades_out_of_range_or_missing_rejected`, `test_judge_out_of_range_rejected_then_repaired` |
| Judge falha após reparação ⇒ propostas preservadas, sem vencedor | `test_judge_failure_after_repair_preserves_proposals` |
| Empate / todos inelegíveis | `test_tie_yields_co_leadership`, `test_ranking_tie_and_no_eligible_and_unknown_cost` |
| Recarga/SSE reconecta sem duplicar nem gastar | `test_sse_reconnect_resumes_without_duplicates_or_new_calls` (+ `ui_smoke.mjs`) |
| Idempotency-Key (mesmo payload / payload diferente) | `test_idempotency_key_same_payload_returns_same_run_and_conflict_on_change` |
| POSTs simultâneos ⇒ um único job | `test_concurrent_posts_same_key_persist_single_job` |
| Reinício ⇒ `interrupted`, artefatos preservados, sem repetir chamadas | `test_server_restart_marks_running_job_interrupted_without_repeating_calls` |
| Cancelamento com chamadas em voo | `test_cancel_during_in_flight_calls_finishes_honestly`, `test_cancel_queued_job_prevents_dispatch` |
| Resultado tardio não reabre o job | `test_late_result_does_not_reopen_terminal_run` |
| Documento hostil não altera regras nem expõe chaves | `test_hostile_document_cannot_change_rules_or_leak_secrets`, `test_private_strategy_not_exposed_and_judge_gets_anonymous_input` |
| Cliente não autorizado negado (run/eventos/fonte/relatório/SSE) | `test_unauthorized_client_denied_everywhere` |
| Cliente agente completa o exemplo por API | `test_agent_client_completes_journey_without_ui` |
| Modo real sem credencial ⇒ erro acionável, sem fallback | `test_real_mode_without_credential_is_actionable_error_no_mock_fallback` |
| Orçamento insuficiente / política comum de cortes | `test_budget_insufficient_rejected_and_tight_budget_degrades_by_common_policy` |

## Docker Compose (não verificado localmente)

```bash
docker compose up --build      # api em 127.0.0.1:8000, web em 127.0.0.1:3000, volume agentathon-data
```
As portas são publicadas apenas em loopback; o backend em modo local aceita clientes da rede do Compose via
`AGENTATHON_AUTH_LOCAL_TRUST_ANY_CLIENT=true`. Para exposição em rede: `AGENTATHON_AUTH_MODE=token`,
`AGENTATHON_API_TOKENS=token:owner`, HTTPS e limitação de requisições em um proxy (não incluídos).

## Arquitetura implementada

```
apps/api/app/
  contracts/      Pydantic: ChallengeConfig, artefatos (EvidencePack, TaskPlan, Proposal, Critique, Verification,
                  Evaluation, Report), views da API -> OpenAPI -> tipos do frontend
  api/            rotas, autenticação (local/token), intake (validação, resolução automática, snapshot + hashes), Markdown
  orchestration/  coordenador (gate de chamadas, tentativas, reconciliação, eventos), fases, grafo LangGraph, executor
  agents/         prompts versionados por papel (hash entra no snapshot)
  providers/      catálogo, MockAdapter determinístico, NeuraLakeAdapter
  evidence/       extração TXT/MD/PDF, pacote com IDs estáveis e localizadores, recuperação lexical, cálculo tipado
  evaluation/     verificadores objetivos, anonimização/validação do Judge, ranking determinístico
  budget/         tabela de preços versionada, ledger (reservas atômicas, provisões, pendências)
  storage/        SQLAlchemy async + Alembic, eventos, artefatos
apps/web/         Next.js (App Router): configuração, execução (SSE), resultado, histórico
fixtures/demo/    documentos SINTÉTICOS + challenge.json;  fixtures/prices/  tabela pública NeuraLake
examples/agent_client.py · scripts/smoke_mock.py · scripts/smoke_real.py · scripts/ui_smoke.mjs · tests/
```

Estados do job: `queued → running → completed | partial | failed | cancelled | interrupted`. `decision_status`
separado: `ranked | tie | no_eligible_candidate | inconclusive | not_evaluated`. Defaults: 2 candidatos (2–4), até 2
tarefas especializadas por candidato, 1 rodada de crítica (0–1), 2 chamadas simultâneas (≤4), 2 tentativas por chamada
lógica, 32 chamadas por execução, 300 s por execução, 60 s por chamada. Rubrica padrão com 6 critérios (pesos somam
100), eficiência calculada pelo servidor: `10 * max(0, 1 - custo/cota)`; `score = Σ(peso × nota) / 10` em Decimal.

## Decisões e desvios registrados

- **LangGraph** é usado como grafo linear com roteamento condicional (cancelamento/falha pulam para verificação); não há
  checkpointer — transições e artefatos são persistidos explicitamente pelas fases, como pede a especificação.
- **Fases 1 e 2 do plano** foram implementadas juntas no código (o executor faz parte da API de jobs); os commits separam
  "fundação" e "critérios de aceite do fluxo".
- **Artefatos** ficam em uma tabela genérica `artifacts (run_id, kind, candidate_id, version, visibility, payload)` com
  payloads validados pelos contratos Pydantic, em vez de uma tabela por objeto. Planos/estratégias são `private` e não
  saem em eventos nem no detalhe (apenas um resumo com tarefas aceitas/rejeitadas).
- **Dinheiro**: Decimal na API (serializado como string) e inteiros em nano-USD no banco, permitindo `UPDATE`
  condicional atômico para reservas, provisões e pendências.
- **Cotas**: teto dividido em cota comum (30% por padrão) e cotas por candidato iguais (ou por `quota_weight`
  declarado). Consolidação (por candidato) e Judge (comum) recebem provisões protegidas convertidas em reserva sem
  contagem dupla. Cortes seguem política comum: delegação limitada pelos slots livres e rodada de crítica desabilitada
  para todos quando não cabe para todos.
- **Eficiência exige `budget.total_cap`**: sem teto, a validação inicial pede para definir o teto ou remover o critério
  (não há quota inventada nem renormalização silenciosa). O preset da demo usa teto simulado de 1,00 USD.
- **Judge**: uma chamada comparativa com todas as propostas anonimizadas (`P1..Pn`, ordem embaralhada com seed
  registrada, nomes de equipe removidos por scrub, sem provedor/modelo/instruções). Critério ausente ou label
  desconhecido é tratado como resposta inválida e consome a única reparação permitida.
- **Especialista de cálculo** não usa inferência: o pensante pede a função tipada e o coordenador executa em código
  (`sum, subtract, multiply, divide, percent_of, percent_change, annual_from_monthly, monthly_from_annual, tco, min, max,
  average, per_unit`), exigindo entradas com `evidence_ids` existentes. A pesquisa documental usa recuperação lexical
  determinística sobre o pacote + uma chamada de resumo estruturado.
- **Verificação objetiva**: uma métrica declarada só vale como prova se citar uma derivação com o mesmo resultado ou um
  trecho de fonte que contenha o número; caso contrário o resultado é `unknown` (pendente).
- **Preços NeuraLake** vêm da página pública (30/09/2026) rotulados como estimativa; a tabela é versionada e o snapshot
  registra `prices_version`. `auto` reserva pelo teto das capacidades e concilia pelo uso informado.
- **Idempotência**: replay com a mesma chave/payload devolve `200` com `created=false` (a criação devolve `202`).
- Rotas adicionais além da tabela da especificação: `GET /runs/{id}/events/list` (polling), `POST /runs/{id}/retry`
  (nova tentativa explícita vinculada ao run anterior), `POST /sources/text`, `POST /demo/prepare`.
- **Frontend** usa os tipos "-Output" gerados do OpenAPI (todos os campos presentes) e envia valores monetários como
  string. Sem lógica de negócio duplicada: elegibilidade, score e decisão vêm do backend.
- **Autenticação**: modo `local` é workspace único restrito a loopback (`AGENTATHON_AUTH_LOCAL_TRUST_ANY_CLIENT` só
  para Docker com portas em loopback). Modo `token` exige Bearer (nunca em query string) com autorização por
  proprietário em runs, fontes, eventos, relatório e SSE. A UI não implementa sessão/token (uso local).
- **Ambiente de desenvolvimento**: Node 24 e Git (MinGit) foram instalados de forma portátil em
  `%LOCALAPPDATA%\Programs` e adicionados ao PATH do usuário porque não existiam na máquina; não fazem parte do repositório.

## Roteiro de demonstração (§18)

1. UI → **Carregar exemplo (SIMULADO)** (ou `POST /demo/prepare` pelo cliente agente): empresa fictícia escolhendo a
   arquitetura de um chatbot interno; restrições `custo_mensal_max ≤ 8000 BRL` e `prazo_piloto_max ≤ 90 dias`.
2. **Iniciar arena**: pacote de evidências v1 → dois pensantes planejam → especialistas (pesquisa e cálculo tipado) →
   barreira única congela o pacote v2 → propostas v1.
3. A crítica da Equipe Equilíbrio aponta conflito da proposta da Equipe Custo com a restrição de custo (9.800 > 8.000);
   a revisão v2 corrige e fica registrada como "revisada após crítica".
4. Verificadores marcam `pass` com evidência; Judge avalia propostas anônimas; ranking em código com eficiência do
   servidor; o cliente recebe JSON e a tela mostra motivos, evidências clicáveis e consumo por bucket.
5. Cenários alternativos prontos: `tie`, `all_ineligible`, `insufficient_evidence`, `judge_fails`, `timeout_unknown_usage`.

## Pendências e limitações conhecidas

- **Teste real NeuraLake pendente** (sem credencial). Compatibilidade de parâmetros/usage/`auto` não confirmada. Sem teste por API
- Docker Compose não executado nesta máquina.
- Sem OCR; PDFs digitalizados são rejeitados com explicação.
- UI apenas para uso local (sem sessão autenticada/CSRF); para rede, usar clientes com token.
- SQLite exige instância única; SSE em produção requer proxy sem buffering.
- Retomada automática de jobs interrompidos não existe (por desenho): `POST /runs/{id}/retry` cria novo run vinculado.
- Anonimização do Judge reduz viés, mas um modelo pode se identificar por estilo; não há garantia de imparcialidade.
- Itens P1 (segundo provedor, baseline de agente único, ledger de créditos, Cross Memory) não iniciados.
