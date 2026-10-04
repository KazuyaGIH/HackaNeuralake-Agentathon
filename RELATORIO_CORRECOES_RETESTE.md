# Relatório de correções e reteste — calculadora e proveniência

Data: 03/10/2026, 20h54–21h30 (America/Sao_Paulo). Escopo: calculadora e proveniência. Juiz, ranking e política de revisão não foram alterados.

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

## 8. Como executar a demonstração

```powershell
cd C:\Users\gugak\Agentathon-calc
..\HackaNeuralake-Agentathon\.venv\Scripts\python.exe -m pytest -q tests/test_calc_provenance.py   # sem gasto
..\HackaNeuralake-Agentathon\.venv\Scripts\python.exe scripts\smoke_mock.py                       # arena simulada
```

O relatório da arena (Markdown) passa a citar `ev-brief-*` (enunciado/restrições) e, em "Lacunas de evidencia", lista as pendências de cálculo (conferido nos dois runs reais). A tela (frontend) não foi verificada visualmente. Para usar no site, é preciso fazer merge desta branch (não feito, aguardando aprovação).
