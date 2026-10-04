"""Monta RELATORIO_BENCHMARK_AGENTATHON.md: narrativa + tabelas geradas + apendices (pre-registro, desafios, codigo)."""

import json
import re
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "out"
DEST = Path(r"C:\Users\gugak\HackaNeuralake-Agentathon\RELATORIO_BENCHMARK_AGENTATHON.md")
sys.path.insert(0, str(BENCH))
from challenges import CHALLENGES  # noqa: E402


def demote(md: str, levels: int = 1) -> str:
    return re.sub(r"^(#+) ", lambda m: "#" * (len(m.group(1)) + levels) + " ", md, flags=re.M)


def code(path: Path, lang: str = "python") -> str:
    return f"```{lang}\n{path.read_text(encoding='utf-8').rstrip()}\n```\n"


parts = [(BENCH / "narrative.md").read_text(encoding="utf-8").rstrip(), "\n\n---\n\n# Apêndices\n"]

parts.append("\n## Apêndice A — Tabelas completas da rodada principal (geradas por `analyze.py main`)\n\n")
parts.append(demote((OUT / "analysis_main.md").read_text(encoding="utf-8"), 2))
parts.append("\n## Apêndice B — Tabelas completas da rodada complementar com o mesmo teto (`analyze.py budget`)\n\n")
parts.append(demote((OUT / "analysis_budget.md").read_text(encoding="utf-8"), 2))

parts.append("\n## Apêndice C — Pré-registro (escrito antes das execuções; alterações datadas)\n\n")
parts.append(demote((BENCH / "PREREGISTRO.md").read_text(encoding="utf-8"), 2))

parts.append("\n## Apêndice D — Desafios, documentos e gabaritos\n\n")
for ch in CHALLENGES:
    parts.append(f"### {ch['id']} — {ch['name']} ({ch['complexity']})\n\n")
    parts.append(f"- **Objetivo enviado às três configurações:** {ch['objective']}\n- **Contexto:** {ch['context']}\n")
    parts.append(f"- **Restrições (tipadas):**\n\n```json\n{json.dumps(ch['constraints'], ensure_ascii=False, indent=1)}\n```\n")
    parts.append(f"- **Gabarito:** opção `{ch['truth_option']}`; métricas `{json.dumps(ch['truth_metrics'], ensure_ascii=False)}`; opções que atendem às restrições obrigatórias: {ch['valid_options']}; lacuna esperada: {ch['gap_terms'] or '—'}.\n")
    parts.append("- **Documentos:** " + ", ".join(f"`{t}`" for t, _ in ch["docs"]) + " (texto integral no código de `challenges.py`, Apêndice G; os documentos do I1 são as fixtures `fixtures/demo/01–03` do repositório + `04_custos_implantacao.md`).\n\n")
parts.append("""Cálculo dos gabaritos:
- **S1:** Alfa 25×38×12 = 11.400; **Beta 25×30×12 + 1.800 = 10.800**; Gama 1.000×12 = 12.000. Teto 11.000 ⇒ só Beta.
- **S2:** Atlas 1.200×2,10 = 2.520, mas 7 dias (> 5); **Boreal 1.200×2,40 = 2.880, 4 dias**; Cometa 1.500 + 1.200×1,20 = 2.940, 5 dias.
- **I1:** A 9.800/mês (> 8.000); **B 6.500/mês, 60 dias, 1º ano 18.000 + 12×6.500 = 96.000**; C 120 dias e 1º ano 50.000 + 86.400 = 136.400.
- **I2:** Norte 224.000 + 36.000 = 260.000, mas 20 semanas e 200 h de QA; **Sul 231.000 + 12×3.800 = 276.600, 16 semanas, 280 h**; Leste 225.000 + 12.000 + 12×(2.500 + 1.000) = 279.000.
- **X1:** **Andes 60×95×24 + 15.000 = 151.800, 45 dias, SLA 99,5%** (a planilha preliminar com implantação de 9.000 está superada); Boreal com preço reajustado e hospedagem no Brasil 60×(88+6)×24 + 25.000 = 160.360 (válida, porém mais cara; com o preço antigo e dados nos EUA daria 140.200, mas viola o requisito); Cobalto 140.800, mas 90 dias e SLA não informado.
- **X2:** com as estimativas de parada da auditoria (regra da diretoria): Big bang 480.000 + 5×60.000 = 780.000 (> 700.000); Faseada 560.000 + 60.000 = 620.000, mas 8 meses; **Híbrida 520.000 + 2×60.000 = 640.000, 7 meses**; custo de treinamento da Híbrida pendente.

""")

parts.append("## Apêndice E — Parâmetros\n\n")
parts.append("""| Parâmetro | Valor |
|---|---|
| Provedor | NeuraLake, `https://api.neuralake.cloud/v1/chat/completions` (chave do `.env`, nunca registrada) |
| Modelo de geração (A, B e C, todos os papéis, inclusive juiz interno) | `text` (alias fixo; a API não aceita nomes de modelo e não informa o modelo subjacente) |
| Amostragem | `temperature = 0.2` (fixa no adaptador do Agentathon); sem `reasoning_effort`; sem `response_format` |
| Limite de saída | proposta/revisão 2.000; plano/crítica 1.500; pesquisa 800; juiz 3.000 tokens |
| Tentativas | 2 por chamada lógica (inicial + 1 repetição/reparo de JSON), igual ao Agentathon |
| Timeout por chamada | 120 s (juiz do Agentathon: 3× por desenho do coordenador) |
| Ferramentas | pesquisa documental (recuperação lexical + especialista) e cálculo tipado (13 funções), máx. 2 tarefas, mesmo catálogo |
| C — arena | 2 equipes (presets Equilíbrio e Custo), 1 rodada de crítica, 1 juiz Padrão (rubrica padrão com eficiência), teto US$ 2,00, 32 chamadas, 2 simultâneas, prazo 600 s |
| C$ / B+ (complementar) | tetos do Apêndice C; B+ até 4 rodadas de autocrítica + revisão |
| Avaliador externo | `reasoning-pro`, streaming, saída até 8.000 tokens, 3 passadas em rotação (2 na complementar) |
| Preços — tabela pública (30/09/2026, arquivo do repositório) | text 0,50 / 0,75; reasoning-pro 2,00 / 4,50 US$ por milhão (entrada/saída) |
| Preços — implícitos no `estimated_cost` da API | text ≈ 0,10 / 0,30 US$ por milhão (verificado: 3.216 entrada + 725 saída ⇒ US$ 0,0005391) |
| Trava de gasto do benchmark | parar se o custo pela tabela pública passasse de US$ 15 |

""")

parts.append("## Apêndice F — Comandos de reprodução\n\n")
parts.append("""Na pasta do repositório, com `AGENTATHON_NEURALAKE_API_KEY` no `.env`. Salve os arquivos do Apêndice G numa pasta (ex.: `bench\\`).

```powershell
.venv\\Scripts\\python.exe bench\\harness.py pilot I1          # teste pequeno (A, B, C em I1)
.venv\\Scripts\\python.exe bench\\harness.py main               # 6 desafios x 3 configs x 3 repetições, ordem intercalada
.venv\\Scripts\\python.exe bench\\evaluate.py llm main          # avaliador externo (repita até não haver pendências)
.venv\\Scripts\\python.exe bench\\analyze.py main               # tabelas -> bench\\out\\analysis_main.md
# rodada complementar: tetos em bench\\caps.json, ex.: {"S1":0.025,"S2":0.025,"I1":0.04,"I2":0.03,"X1":0.03,"X2":0.03}
.venv\\Scripts\\python.exe bench\\harness.py budget bench\\caps.json 2
.venv\\Scripts\\python.exe bench\\evaluate.py llm budget
.venv\\Scripts\\python.exe bench\\analyze.py budget
.venv\\Scripts\\python.exe bench\\build_report.py              # monta este relatório
```

Saídas brutas (não versionadas, ficam em `bench\\out\\`): `runs.jsonl` (uma linha por execução, com a entrega completa, o pacote de evidências e, em C, ranking, propostas, críticas e chamadas do motor), `calls.jsonl` (uma linha por tentativa HTTP, com `usage` bruto), `calls_eval.jsonl` (avaliador), `evals.jsonl` (notas por passada). O banco do motor fica em `bench\\data\\agentathon.db`.

""")

parts.append("## Apêndice G — Código do benchmark (integral)\n\n")
for name in ["challenges.py", "harness.py", "evaluate.py", "analyze.py", "build_report.py"]:
    parts.append(f"### `{name}`\n\n" + code(BENCH / name) + "\n")

DEST.write_text("".join(parts), encoding="utf-8")
print("ok", DEST, DEST.stat().st_size)
