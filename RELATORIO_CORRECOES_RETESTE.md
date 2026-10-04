# Relatório de correções e reteste — calculadora e proveniência

> **ATUALIZAÇÃO FINAL — 03/10/2026, 23h05 (America/Sao_Paulo).** Esta parte substitui as conclusões das seções antigas mais abaixo, que ficaram como histórico.
> Entregue com ~5 min de atraso: o trabalho começou às 22h27 (depois do horário de congelamento previsto, 22h20) e houve uma espera pela escolha do navegador.

## F1. Resumo

| Item | Estado |
|---|---|
| Calculadora chamada corretamente por IA real (NeuraLake `text`) | **Concluído em 1 execução de verificação.** `run_1021481f05d441bb`: `tco(setup=40000, monthly=7200, months=12)` = **126400** (correto: 40000 + 12×7200). A proposta da equipe 1 cita `drv-c1-task-001`, referência válida no pacote congelado. |
| Integração calculadora + revisão do Devin | Concluída. Revisão do Devin preservada e coberta pelos testes (4). |
| main no GitHub | `c4f6a07` → **`a54bf3a`** (fast-forward, sem force-push), às 22h34. |
| Publicação (Render, auto-deploy da main) | API publicada roda o código novo: uma arena **simulada** criada às 23h03 no servidor público (`run_19c7b8f2692c4020`) trouxe `ev-brief-*` no relatório, recurso que só existe a partir deste trabalho. A tela responde HTTP 200. |
| Verificação da tela publicada com API real | **Não feita.** Não houve tempo depois de escolhido o navegador. O teste de API simulada não comprova a interface nem uma arena real no site. |
| Bateria comparativa | 6 execuções (3 desafios × 2 configurações), commit `a54bf3a`. **Avaliação preliminar.** |
| Modo "uma equipe especializada" (B do pedido) | **Não suportado** (`MIN_CANDIDATES = 2`, juiz sempre roda). Comparado: generalista × arena completa. |
| Qualidade textual | Não avaliada (sem avaliador externo por IA). |

## F2. Commits

- **Código medido e publicado:** `a54bf3a`. Calculadora com catálogo exato, validação antes de executar e no máximo 1 reparo do plano, sobre a integração `848dbd2` e o relatório `2f1db4d`.
- **Integração:** merge `848dbd2` = `cb48f87` (calculadora/proveniência) + `6ef6ee9` (Devin, revisão).
- **Commit final:** acrescenta só este relatório, os logs e o harness da bateria em `bench/`. Não muda código do app.

## F3. Correções aplicadas (acumulado)

1. O enunciado, o contexto e as restrições viram evidências citáveis (`ev-brief-*`). O valor precisa constar no trecho citado. Constante sem ID só é aceita se aparecer literalmente no texto do cliente. O limite de uma restrição não comprova métrica. Dado ausente vira pendência; entrada inválida vira `failed`.
2. **Novo (`a54bf3a`):**
   - o planejador recebe o catálogo exato de funções e nomes de entrada, derivado de `FUNCTIONS`/`_REQUIRED` (`catalog_text()`), com um exemplo;
   - todo pedido de cálculo é validado em `validate_plan` com as mesmas regras de origem, antes de executar;
   - se houver pedido inválido, há **no máximo 1 chamada de reparo por plano** (`stage=plan_repair`), contada no orçamento e nos tokens, com o erro e o catálogo.
3. Devin: a revisão é rejeitada se passar a violar uma regra obrigatória antes comprovada.
4. Não mudaram: juiz, ranking, critérios de verificação. Nenhum gabarito no código. Nenhum valor inventado.

**Execuções reais de verificação da correção, fora da bateria:**
- `run_ff3c9adfc7ac4671` (antes do exemplo no catálogo): 7 chamadas, 2 delas de reparo, 23.948/4.716 tokens, US$ 0,0155. **0 cálculos**: a IA manteve nomes de entrada errados mesmo depois do reparo.
- `run_1021481f05d441bb` (catálogo com exemplo, mesmo código de `a54bf3a`): 6 chamadas, 22.597/3.449 tokens, US$ 0,0139. **3 de 5 cálculos concluídos.**
  - 2 de `tco` = 126400, corretos.
  - 1 `monthly_from_annual(8000)` = 666,67: tem origem válida, mas é **semanticamente errado** (8000 já é um limite mensal). A calculadora valida a origem, não o sentido.
  - 2 rejeitados por "setup=0" não constar no documento. Rejeição correta.

## F4. Bateria comparativa (avaliação preliminar)

**Amostra (escolhida antes de rodar):** S1 (simples), I1 (intermediário) e X1 (complexo), do benchmark anterior (Apêndice D do `RELATORIO_BENCHMARK_AGENTATHON.md`). 1 repetição, ordem intercalada (S1 A→Arena, I1 Arena→A, X1 A→Arena), sequencial. NeuraLake alias `text` em tudo. Mesmos documentos, mesmo enunciado, mesmas ferramentas corrigidas (catálogo, validação, reparo e calculadora importados do app) e mesmo formato final.

**Configurações:**
- **A — generalista** (no harness, "B"): 1 agente com plano, cálculo, proposta e 1 autorrevisão. A autorrevisão passa pela regra do Devin (`accept_revision`).
- **Arena completa** (no harness, "C"): 2 equipes (presets balanced e cost), 1 rodada de crítica, 1 juiz Padrão. Teto US$ 2,00 e 32 chamadas, 2 simultâneas, timeout de 120 s por chamada, 2 tentativas.

**Aprovação, definida antes de rodar e calculada só por código e gabarito:** todas as condições abaixo.
- Opção correta.
- Todas as métricas do gabarito corretas (tolerância de 0,5%).
- 0 referências inexistentes.
- Restrições numéricas obrigatórias cumpridas.

Os gabaritos não são enviados aos agentes. A nota do juiz interno não entra na aprovação.

| Execução | Config | Desafio | Chamadas (tent./reparos/falhas/plan_repair) | Tokens in/out/total | Tempo s | Cálculos pedidos/concluídos | Opção | Métricas | Aprovada | Decisão oficial | Custo tabela US$ | Custo API US$ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-B-r1 | A generalista | S1 | 6/1/0/2 | 13652/3347/16999 | 83,1 | 4/0 | Beta (ok) | 2/2 | **sim** | não aplicável | 0,0093 | 0,00237 |
| S1-C-r1 | Arena | S1 | 11/0/0/2 | 25212/4710/29922 | 72,6 | 5/2 | Beta (ok) | 2/2 | **sim** | inconclusiva | 0,0161 | 0,00393 |
| I1-C-r1 | Arena | I1 | 13/2/1/1 | 49228/5830/55058 (1 chamada com uso desconhecido) | 168,3 | 3/1 | B (ok) | 2/3 | não | inconclusiva | 0,0290 | 0,00667 |
| I1-B-r1 | A generalista | I1 | 4/0/0/0 | 16891/1891/18782 | 42,2 | 3/2 | B (ok) | 3/3 | **sim** | não aplicável | 0,0099 | 0,00226 |
| X1-B-r1 | A generalista | X1 | 5/0/0/1 | 13609/2590/16199 | 64,5 | 4/0 | Andes (ok) | 2/3 | não | não aplicável | 0,0087 | 0,00214 |
| X1-C-r1 | Arena | X1 | 12/1/0/3 | 35933/6996/42929 | 107,1 | 7/0 | Andes (ok) | 2/3 | não | inconclusiva | 0,0232 | 0,00569 |

| Config | Aprovadas/tentadas | Tokens totais | Média/exec | Tempo médio / mediano s | Tokens por aprovada | Custo tabela por aprovada | Custo API por aprovada | Cálculos concluídos/pedidos |
|---|---|---|---|---|---|---|---|---|
| A generalista | **2/3** | 51.980 | 17.327 | 63,2 / 64,5 | 25.990 | US$ 0,0140 | US$ 0,0034 | 2/11 |
| Arena completa | **1/3** | 127.909 (inclui 1 chamada de uso desconhecido, não somada) | 42.636 | 116,0 / 107,1 | 127.909 | US$ 0,0683 | US$ 0,0163 | 3/15 |

- **Variação de tokens da arena frente ao generalista**, só nos pares com uso conhecido (S1 e X1; I1 excluído por 1 chamada de uso desconhecido na arena): 100 × (72.851 / 33.198 − 1) = **+119%**. A arena consumiu mais e aprovou menos.
- **Decisão oficial da arena:** 3/3 **inconclusivas**, 0 com vencedor validado, 0 com erro.
- **Custo:**
  - "Custo tabela" vem da tabela de preços do repositório.
  - "Custo API" vem do `estimated_cost` informado pela NeuraLake.
  - Os dois divergem cerca de 4×, assim como no benchmark anterior. O preço da tabela ainda não foi conferido.
- **Falhas e desconhecidos:** 1 falha de chamada (I1 arena), 4 reparos de schema, 9 chamadas de reparo de plano no total e 1 chamada com uso desconhecido.
- **Cálculos:** 5 de 26 concluídos ao todo. A causa principal restante é a IA citar valores que não constam no trecho, ou usar nomes de entrada errados mesmo depois do reparo.

**Leitura:** amostra de 6 execuções, preliminar. Não permite afirmar superioridade de nenhuma configuração. Também não permite afirmar economia da arena, que **gastou mais**.

## F5. Verificação do produto publicado

- URLs: tela https://agentathon-k5h2.onrender.com (HTTP 200) · API https://agentathon-api.onrender.com/health (`ok`).
- **Versão publicada:** compatível com `a54bf3a`. A arena simulada pública `run_19c7b8f2692c4020` terminou `completed/ranked` e cita `ev-brief-*`, recurso que não existia em `c4f6a07`.
- **Não verificado:**
  - arena real (chave NeuraLake) pela interface publicada;
  - progresso na tela;
  - cálculo correto exibido na tela.
  Motivo: falta de tempo. Isso continua pendente; não declaro "produto funcionando" na interface.

## F6. Limitações

- A calculadora valida a origem, não o sentido do cálculo (caso `monthly_from_annual(8000)`).
- Com `text`, a maioria dos pedidos de cálculo ainda falha: 5 de 26 concluídos na bateria.
- As arenas terminaram inconclusivas.
- Não há modo "uma equipe só".
- A interface publicada não foi testada com API real.
- A amostra é de 1 repetição.

## F7. Três frases para o pitch (sustentadas)

1. "Cada número do Agentathon tem origem rastreável: o servidor recusa valores inventados e mostra de que trecho veio cada dado."
2. "Com a IA real da NeuraLake, a calculadora já produziu o custo total de 12 meses correto (R$ 126.400), citado na proposta."
3. "Medimos e publicamos: numa avaliação preliminar de 6 execuções, a arena gastou cerca de 2× mais tokens que um agente único sem aprovar mais entregas. Por isso, o próximo passo é usar a arena só onde ela agrega valor."

## F8. Números para o slide (avaliação preliminar, 3 desafios × 1 repetição, NeuraLake `text`)

- Agente único: **2/3 aprovadas**, ~17 mil tokens por execução, ~63 s em média.
- Arena completa: **1/3 aprovadas**, ~43 mil tokens por execução, ~116 s em média, 3/3 inconclusivas.
- Tokens: arena **+119%** frente ao agente único (pares S1 e X1).

## F9. Como reproduzir

```powershell
cd C:\Users\gugak\HackaNeuralake-Agentathon        # main em a54bf3a
.venv\Scripts\python.exe -m pytest -q              # 92 passed (sem gasto)
.venv\Scripts\python.exe scripts\smoke_mock.py     # arena simulada
# bateria real (gasta ~US$ 0,10 pela tabela): carregar AGENTATHON_* do .env no ambiente, depois
.venv\Scripts\python.exe bench\harness.py battery 1 S1,I1,X1
.venv\Scripts\python.exe bench\battery_summary.py battery
```

- Logs da bateria, sem credenciais (verificado): `bench/out/runs.jsonl`, `bench/out/calls.jsonl` e `bench/out/battery_rows.json`.
- Demo no site: abrir a tela, colar a chave da NeuraLake em "Orçamento e modo → Chaves das IAs", usar o desafio demo e pedir no objetivo o custo total de 12 meses por opção.

---

*Seções abaixo: histórico de 03/10, 20h54–21h55.*

## 1. Commits

| Item | Valor |
|---|---|
| Commit-base | `c4f6a07` (main) |
| Branch | `fix/calculadora-proveniencia` (worktree `C:\Users\gugak\Agentathon-calc`) |
| Commits | `cbebd08` correção principal · `db3e311` guarda no verificador + mock · `4f50a5d` resolução de constantes do enunciado + nome de entrada inválido · (este relatório) |
| Trabalho do Devin | **Não integrado: não recebi branch/commit/patch até 21h30.** Nenhuma branch de integração criada. |
| Merge na main / push / deploy | Não feitos. |

## 2. Causas confirmadas no código

1. **O enunciado, o contexto e as restrições nunca viravam evidência.** `build_pack` (`apps/api/app/evidence/pack.py`) indexava só os documentos anexados. Os números escritos pelo cliente no objetivo (ex.: "12 meses", "3 atendentes") ou no limite de uma restrição não tinham ID para citar. Por isso a calculadora recusava com "entradas sem evidencia de origem" ou "referenciam evidencias inexistentes". Reproduzido em `test_reproducao_sem_correcao_enunciado_nao_era_citavel`.
2. **Um ID válido bastava, mesmo que o número não estivesse no trecho.** `run_calculation` só conferia se o ID existia. Um valor inventado, citando um ID real, era aceito.
3. **Informação ausente e entrada inválida eram o mesmo erro.** Tudo virava `CalculationError` e `TaskResult.status="failed"`, sem registrar pendência.

## 3. Correções (arquivos alterados)

| Arquivo | Mudança |
|---|---|
| `apps/api/app/evidence/pack.py` | `brief_items()`: objetivo, contexto e cada restrição viram `EvidenceItem` no formato atual. São do tipo `source_claim`, com `source_id=None` e IDs estáveis: `ev-brief-obj-NNN`, `ev-brief-ctx-NNN` e `ev-brief-rst-<constraint_id>`. Têm localizador (`section` = enunciado/contexto/restricao:<id>, linhas) e `provenance` = `challenge:objective` / `challenge:context` / `challenge:constraint:<id>`. `build_pack(sources, brief=None)` é compatível com as chamadas antigas. |
| `apps/api/app/evidence/calc.py` | Novo parâmetro opcional `run_calculation(..., evidence=)`: cada valor de entrada precisa **constar** em um trecho citado (leitura pt-BR/en: `18.500,00`, `0,5`) ou ser o `result` de uma derivação citada. `MissingInputError(CalculationError)` vale para entrada obrigatória ausente. Nome de entrada errado conta como entrada inválida. `resolve_brief_refs()`: entrada **sem** ID cujo valor aparece literalmente no enunciado/contexto/restrições recebe o ID desse trecho. Qualquer outro valor continua sem origem e é rejeitado. |
| `apps/api/app/orchestration/phases.py` | `phase_evidence` inclui o enunciado no pacote. `_run_task` resolve as referências do enunciado (e registra em `operational_changes`), passa o mapa de evidências e devolve `status="skipped"` com `error="pendencia: ..."` para dado ausente. `phase_sync` leva essas pendências para `pack.gaps` ("Lacunas de evidencia" no relatório). |
| `apps/api/app/evaluation/verifiers.py` | 1 linha: o trecho de uma **restrição** (`challenge:constraint:*`) não comprova uma métrica. O limite é a meta, não uma medição. Sem isso, a correção abriria a brecha "custo = 15000, comprovado pela regra de máximo 15000". |
| `apps/api/app/providers/mock.py` | O mock não usa mais o trecho da restrição como prova de métrica (mesma regra do verificador). |
| `apps/api/app/agents/prompts.py` | Planejador: uma frase dizendo que o valor deve constar no trecho citado, que os dados do enunciado são `ev-brief-*` e que não se devem inventar valores. |
| `tests/test_calc_provenance.py` | 11 testes novos (abaixo). |

Contratos/schemas: **nenhum alterado** (sem campos novos em Pydantic, sem mudança de OpenAPI/frontend). Status usados: `completed` = cálculo concluído; `failed` = entrada inválida; `skipped` + `pendencia:` = informação ausente.

## 4. Testes executados (resultados reais)

- `tests/test_calc_provenance.py` (11 testes). **Positivos:** o enunciado vira evidência rastreável; constantes legítimas (18.500 × 12); limite de restrição e decimal pt-BR (0,5) usados no cálculo; derivação citável por outro cálculo e pelo verificador; constante sem ID resolvida pelo servidor. **Negativos:** valor inventado com ID válido; ID inexistente; entrada sem origem; valor sem ID que não está no enunciado (37); nome de entrada errado tratado como inválido, não como pendência; dado ausente vira `MissingInputError`; restrição não comprova métrica.
- Suíte completa: `.venv\Scripts\python.exe -m pytest -q` → **88 passed** (último run, 21h10).
  - Em um dos runs intermediários, `tests/test_api_controls.py::test_sse_reconnect_resumes_without_duplicates_or_new_calls` falhou uma vez. Passou nas 3 repetições isoladas e nos runs completos seguintes. Parece ser um teste instável de tempo (SSE), não relacionado à mudança. Não investiguei a fundo.
- `scripts/smoke_mock.py`: completou. As propostas citam `ev-brief-obj-001`, `ev-brief-rst-custo_mensal_max` e a derivação `drv-c1-t2`.

## 5. Execução ponta a ponta real (NeuraLake)

Script em scratchpad (`e2e_real_calc.py`) usando a API in-process e a integração existente (`/demo/prepare`, chave do `.env` local, não exposta). Configuração: desafio demo + frase no objetivo ("R$ 18.500 por mes com 3 atendentes; 12 meses"), 2 equipes `text` com `calculation` e `document_research` permitidos (até 2 tarefas), sem crítica, juiz `text`, teto US$ 0,20, máximo de 10 chamadas.

| Run | Commit | Status | Chamadas (incl. reparos) | Tokens entrada/saída | Custo (tabela do repo) |
|---|---|---|---|---|---|
| `run_10c2c71d993540a2` | `db3e311` | completed, ranked | 5 (0 reparos) | 16.832 / 2.807 | US$ 0,0105 |
| `run_7c851dc6bea545aa` | `4f50a5d` | completed, ranked | 5 (0 reparos) | 16.740 / 2.481 | US$ 0,0102 |

Cálculos pedidos pelo modelo e o que a calculadora fez:

- **Run 1 (4 pedidos, 0 concluídos):**
  - `tco` com "meses=12" sem ID → rejeitado. Motivou a correção `resolve_brief_refs`; não houve reteste desse caso específico com modelo real.
  - `less_than_or_equal_to` → função inexistente.
  - "4 meses" citando um trecho que diz "120 dias" → valor não está no trecho. **Rejeição correta.**
  - `monthly_from_annual` com nome de campo errado → classificado como pendência. Erro de classificação, corrigido em `4f50a5d`.
  - O modelo citou corretamente `ev-brief-rst-custo_mensal_max`.
- **Run 2 (4 pedidos, 0 concluídos):** todos rejeitados por **nome de entrada inválido**. O modelo usou nomes semânticos (`custo_mensal_opcao_b`) em vez de `annual`/`value`/`percent`. Os pedidos também não faziam sentido: `monthly_from_annual` sobre um valor que já é mensal; `percent_of(60 dias, 90 dias)`. As referências e os valores citados estavam corretos (incluindo `ev-brief-rst-prazo_piloto_max`).
- Nas duas execuções, as métricas finais das propostas foram comprovadas pelo verificador com trecho de documento (`ev-568295-005`), não com cálculo.

**Conclusão honesta:** a correção remove a causa "dado do enunciado sem origem", com testes. Mas, com o modelo `text`, os cálculos reais continuam falhando: agora por especificação errada da função (nomes de entrada e escolha da função), não por proveniência. Não mapeei os nomes por posição, porque isso transformaria pedidos sem sentido em números "comprovados". Não há evidência de ganho de qualidade nem de economia de tokens.

## 6. Smoke A/B — não testado

- **B (uma única equipe, sem disputa nem juiz):** não é suportado. `MIN_CANDIDATES = 2` (`contracts/challenge.py`) e o juiz sempre roda. Exigiria mudança fora de uma alteração mínima e isolada, então não simulei.
- **A (agente generalista com as mesmas ferramentas):** não existe no app. O harness do benchmark anterior ficou no scratchpad de outra sessão. Não houve tempo de reconstruir com as mesmas ferramentas corrigidas.

## 7. Limitações e pendências

- Trabalho do Devin não recebido/integrado. Os testes de integração das duas partes não foram feitos.
- `resolve_brief_refs` pode associar um número que aparece no enunciado por coincidência (ex.: "12" de "12 de agosto"). O alcance é limitado a textos fornecidos pelo cliente e a atribuição fica registrada em "Limitacoes e mudancas operacionais" do relatório da arena.
- Leitura de números: não interpreta extenso ("quatro meses") nem sufixos ("2 mil").
- Próximo passo sugerido (não feito): na validação do plano (`validate_plan`), rejeitar cedo nomes de entrada inválidos, ou devolver ao planejador a assinatura exigida, para o modelo corrigir. O prompt já lista as assinaturas e o modelo `text` as ignorou.
- Benchmark completo não repetido (fora do escopo de hoje).
- Gasto real hoje: 2 arenas, cerca de US$ 0,021 pela tabela do repositório.

## 7b. Integração com o trabalho do Devin (03/10, 21h49–21h55)

- A branch do Devin (`origin/devin/revisao-ranking-guardrails`, `58264fd` + `6ef6ee9`) já estava no GitHub desde cerca de 20h57. Não percebi isso durante a primeira sessão; as seções acima dizem "não recebido", o que estava errado.
- Branch de integração (local, não enviada): `integracao/calc-revisao`, pasta `C:\Users\gugak\Agentathon-integ`. Merge `848dbd2` = `cb48f87` (calculadora) + `6ef6ee9` (Devin) + este relatório.
- Conflito: só no bloco de imports de `phases.py` (as duas partes acrescentaram nomes). Resolvido mantendo os dois. Nenhuma outra mudança de código.
- Testes: `pytest -q` → **92 passed** (88 meus + 4 do Devin). `scripts\smoke_mock.py` → completou (exit 0).
- **Arena real na integração:** `run_429b68ba5acc4b34`, NeuraLake `text`, mesmo desafio e configuração da seção 5, mas **com 1 rodada de crítica** (teto de 14 chamadas).
  - Resultado: completed, ranked, vencedora relativa Alfa.
  - 10 chamadas: 2 de plano, 2 de proposta, 2 de crítica, 3 de revisão e 1 de juiz. Uma revisão veio com `schema_invalid` e foi refeita; o reparo está contado.
  - Tokens: 35.832 de entrada e 4.942 de saída. Custo US$ 0,0216 pela tabela do repositório. Cerca de 108 s.
  - Cálculos: **0 de 4**.
    - 2 usaram a função inexistente `less_than_or_equal`;
    - 1 teve nome de entrada inválido;
    - 1 usou "12" citando um trecho que diz "120 dias". A recusa está correta.
    - Os IDs `ev-brief-rst-*` foram citados com os valores certos.
  - Revisão (Devin): **nenhuma revisão foi rejeitada**, porque as versões 2 continuaram cumprindo as regras. A proteção não foi acionada neste teste real; ela só está coberta pelos 4 testes automáticos.
  - As métricas finais foram comprovadas por trecho de documento (`ev-568295-005`), não por cálculo. Não há gabarito para dizer se a recomendação está correta.

## 8. Como executar a demonstração

```powershell
cd C:\Users\gugak\Agentathon-calc
..\HackaNeuralake-Agentathon\.venv\Scripts\python.exe -m pytest -q tests/test_calc_provenance.py   # sem gasto
..\HackaNeuralake-Agentathon\.venv\Scripts\python.exe scripts\smoke_mock.py                       # arena simulada
```

O relatório da arena (Markdown) passa a citar `ev-brief-*` (enunciado/restrições) e, em "Lacunas de evidencia", lista as pendências de cálculo (conferido nos dois runs reais). A tela (frontend) não foi verificada visualmente. Para usar no site, é preciso fazer merge desta branch (não feito, aguardando aprovação).
