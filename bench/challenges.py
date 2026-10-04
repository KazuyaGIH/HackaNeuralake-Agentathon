"""Bateria de 6 desafios do benchmark (definidos ANTES das execucoes), com gabarito verificavel.

Cada desafio: documentos sinteticos, objetivo, restricoes tipadas (as mesmas para A, B e C) e gabarito:
- truth_option: opcao correta; options: apelidos para detectar a opcao escolhida no texto;
- truth_metrics: valores corretos das metricas exigidas pelas restricoes (da opcao correta);
- valid_options: opcoes que atendem todas as restricoes obrigatorias (para separar "erro grave" de "subotima");
- gap_terms: termos que devem aparecer juntos em algum item (pendencias/hipoteses/riscos) quando ha lacuna conhecida.
"""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "demo"

FORMAT_NOTE = (
    " Comece o campo title com o nome da opcao escolhida ({names}) e declare em metrics os valores da opcao escolhida "
    "para cada metrica exigida pelas restricoes."
)

S1_DOC = """# Planos de videoconferência — cotação (empresa fictícia Vértice Contábil)

Documento sintético para teste. Empresa, fornecedores e preços são inventados.

A Vértice Contábil tem 25 colaboradores que precisam de licença de videoconferência por 12 meses. Reuniões com clientes chegam a 100 participantes.

## Plano Alfa (fornecedor fictício AlfaMeet)

- Preço: R$ 38 por usuário por mês.
- Sem taxa de implantação.
- Limite: 300 participantes por reunião.

## Plano Beta (fornecedor fictício BetaCall)

- Preço: R$ 30 por usuário por mês.
- Taxa única de implantação: R$ 1.800.
- Limite: 150 participantes por reunião.

## Plano Gama (fornecedor fictício GamaConf)

- Preço fixo: R$ 1.000 por mês para até 30 usuários.
- Sem taxa de implantação.
- Limite: 100 participantes por reunião.
"""

S2_DOC = """# Cotação de frete — envio de 1.200 kg (empresa fictícia Oficina Prisma)

Documento sintético para teste. Empresa, transportadoras e preços são inventados.

A Oficina Prisma precisa enviar uma carga de 1.200 kg de peças de São Paulo para Curitiba. A entrega deve ocorrer em no máximo 5 dias úteis e o frete não pode passar de R$ 3.000.

## Transportadora Atlas

- R$ 2,10 por kg.
- Prazo de entrega: 7 dias úteis.

## Transportadora Boreal

- R$ 2,40 por kg.
- Prazo de entrega: 4 dias úteis.

## Transportadora Cometa

- Taxa fixa de R$ 1.500 por envio mais R$ 1,20 por kg.
- Prazo de entrega: 5 dias úteis.
"""

I1_DOC4 = """# [SINTETICO] Custos de implantação estimados — Lumina Ferramentas Ltda. (empresa fictícia)

Documento sintético complementar. Valores inventados.

## Custos únicos de implantação por opção

- Opção A (NimbusChat): taxa de implantação e configuração de conectores de R$ 5.000, paga uma única vez.
- Opção B (Aurora API): indexação dos 340 documentos, testes com o RH e configuração de R$ 18.000, pagos uma única vez.
- Opção C (modelo aberto auto-hospedado): investimento inicial em hardware de R$ 40.000 (ver documento de opções) mais R$ 10.000 de ajuste do modelo, pagos uma única vez.

## Orientação da diretoria

O custo do primeiro ano (custos únicos de implantação mais 12 meses de custo mensal recorrente) não deve passar de R$ 100.000.
"""

I2_DOC1 = """# Propostas para desenvolvimento do aplicativo de agendamento (empresa fictícia Clínica Horizonte)

Documento sintético para teste. Empresa, fornecedores e valores são inventados.

## Fornecedor Norte

- Esforço estimado: 1.600 horas a R$ 140 por hora.
- Prazo de entrega: 20 semanas.
- Horas dedicadas a testes e QA: 200 horas (incluídas no esforço).
- Manutenção após a entrega: R$ 3.000 por mês.

## Fornecedor Sul

- Esforço estimado: 1.400 horas a R$ 165 por hora.
- Prazo de entrega: 16 semanas.
- Horas dedicadas a testes e QA: 280 horas (incluídas no esforço).
- Manutenção após a entrega: ver termos comerciais complementares.

## Fornecedor Leste

- Esforço estimado: 1.500 horas a R$ 150 por hora.
- Prazo de entrega: 14 semanas.
- Horas dedicadas a testes e QA: 300 horas (incluídas no esforço).
- Manutenção após a entrega: R$ 2.500 por mês.
"""

I2_DOC2 = """# Termos comerciais complementares (recebidos após as propostas)

Documento sintético para teste.

- Fornecedor Sul: manutenção após a entrega de R$ 3.800 por mês.
- Fornecedor Leste: cobra uma taxa única de configuração de ambiente de R$ 12.000 e uma licença da plataforma de R$ 1.000 por mês, que se soma à manutenção enquanto o aplicativo estiver em operação.
- Fornecedor Norte: sem custos adicionais além da proposta.

## Orientação da diretoria da clínica

Para o custo total, considerar o desenvolvimento, as taxas únicas e os 12 primeiros meses de custos mensais após a entrega. Teto do custo total: R$ 285.000.
"""

X1_DOC1 = """# Ata de reunião — requisitos do novo CRM (empresa fictícia Mercantil Ipê) — 20/08/2026

Documento sintético para teste.

- Usuários: 60 vendedores e gestores.
- Horizonte de análise: 24 meses.
- Requisito obrigatório: os dados de clientes devem ficar hospedados no Brasil (política interna de dados).
- Go-live em até 75 dias após a assinatura.
- SLA contratual mínimo de disponibilidade: 99,5%.
- Custo total em 24 meses (assinaturas mais implantação): até R$ 170.000.
- Em caso de divergência entre documentos, vale a informação mais recente formalizada pelo fornecedor.
"""

X1_DOC2 = """# Planilha preliminar de compras — CRM (julho/2026)

Documento sintético. Valores preliminares, sujeitos a confirmação nas propostas formais.

| CRM | Preço por usuário/mês | Implantação |
|---|---|---|
| CRM Andes | R$ 95 | R$ 9.000 |
| CRM Boreal | R$ 80 | R$ 25.000 |
| CRM Cobalto | R$ 70 | R$ 40.000 |
"""

X1_DOC3 = """# Propostas formais recebidas — CRM

Documento sintético para teste.

## CRM Andes — proposta formal de 05/08/2026

- R$ 95 por usuário por mês.
- Implantação: R$ 15.000 (inclui migração de dados; valor revisado em relação à estimativa preliminar).
- SLA contratual: 99,5%.
- Dados hospedados em São Paulo.
- Go-live em 45 dias.

## CRM Boreal — proposta formal de 10/08/2026

- R$ 80 por usuário por mês.
- Implantação: R$ 25.000.
- SLA contratual: 99,9%.
- Dados hospedados nos EUA (Virgínia).
- Go-live em 60 dias.

## CRM Cobalto — proposta formal de 12/08/2026

- R$ 70 por usuário por mês.
- Implantação: R$ 40.000.
- Dados hospedados no Brasil.
- Go-live em 90 dias.
- O fornecedor não informou o SLA contratual.
"""

X1_DOC4 = """# E-mail do CRM Boreal — 02/09/2026

Documento sintético para teste.

Prezados, informamos um reajuste: o valor por usuário passa a R$ 88 por mês para contratos assinados a partir de setembro de 2026. Também passamos a oferecer hospedagem dos dados no Brasil (São Paulo) por um adicional de R$ 6 por usuário por mês. As demais condições da proposta de 10/08/2026 permanecem.
"""

X2_DOC1 = """# Proposta da consultoria — migração do ERP (empresa fictícia Distribuidora Pampa) — 01/07/2026

Documento sintético para teste.

## Estratégias de migração

- Big bang: custo de implantação de R$ 480.000; duração de 5 meses; parada estimada das operações na virada: 2 dias.
- Faseada (uma unidade por vez): custo de implantação de R$ 560.000; duração de 8 meses; parada estimada: 1 dia.
- Híbrida (financeiro primeiro, depois logística): custo de implantação de R$ 520.000; duração de 7 meses; parada estimada: 1 dia.

## Treinamento

O treinamento dos usuários está incluído nas estratégias Big bang e Faseada. Para a estratégia Híbrida, o custo de treinamento ainda será orçado pela consultoria.
"""

X2_DOC2 = """# Parecer da auditoria independente — estimativas de parada — 15/09/2026

Documento sintético para teste.

Revisamos as estimativas de parada da consultoria com base em 14 migrações comparáveis do setor. Nossa estimativa de parada das operações na virada:

- Big bang: 5 dias.
- Faseada: 1 dia.
- Híbrida: 2 dias.

Os custos de implantação e os prazos apresentados pela consultoria foram considerados razoáveis.
"""

X2_DOC3 = """# Diretrizes da diretoria — migração do ERP

Documento sintético para teste.

- O go-live completo deve ocorrer em até 7 meses, antes do fechamento fiscal.
- Cada dia de parada das operações custa R$ 60.000 (vendas perdidas e horas extras).
- Custo total esperado = custo de implantação + dias de parada × R$ 60.000. Teto: R$ 700.000.
- Quando houver divergência entre a consultoria e a auditoria nas estimativas de parada, usar a auditoria.
- A diretoria aceita seguir sem o valor do treinamento fechado, desde que a recomendação deixe essa pendência explícita.
"""


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _num(cid, desc, kind, key, limit, unit, mandatory=True):
    return {"constraint_id": cid, "description": desc, "kind": kind, "metric_key": key, "limit": str(limit), "unit": unit, "mandatory": mandatory}


CHALLENGES = [
    {
        "id": "S1", "complexity": "simples", "name": "Plano de videoconferência",
        "objective": "Escolher o plano de videoconferência de menor custo total em 12 meses (mensalidades mais taxas) para os 25 colaboradores da Vértice Contábil, que permita reuniões de pelo menos 100 participantes e respeite o teto de custo."
        + FORMAT_NOTE.format(names="Alfa, Beta ou Gama"),
        "context": "Cotação sintética com três planos. Todos os valores são fictícios.",
        "docs": [("planos_videoconferencia.md", S1_DOC)],
        "constraints": [
            _num("custo_12m_max", "Custo total em 12 meses (mensalidades + taxas) para 25 usuários", "numeric_max", "cost_12m_brl", 11000, "BRL"),
            _num("participantes_min", "Capacidade mínima de participantes por reunião", "numeric_min", "max_participants", 100, "participantes"),
        ],
        "options": {"Alfa": ["plano alfa", "alfameet", "alfa"], "Beta": ["plano beta", "betacall", "beta"], "Gama": ["plano gama", "gamaconf", "gama"]},
        "truth_option": "Beta", "valid_options": ["Beta"],
        "truth_metrics": {"cost_12m_brl": 10800, "max_participants": 150},
        "gap_terms": [],
    },
    {
        "id": "S2", "complexity": "simples", "name": "Transportadora para 1.200 kg",
        "objective": "Escolher a transportadora de menor custo de frete para a carga de 1.200 kg da Oficina Prisma que cumpra o prazo máximo de entrega e o teto de custo."
        + FORMAT_NOTE.format(names="Atlas, Boreal ou Cometa"),
        "context": "Cotação sintética de frete. Todos os valores são fictícios.",
        "docs": [("cotacao_frete.md", S2_DOC)],
        "constraints": [
            _num("frete_max", "Custo do frete para 1.200 kg", "numeric_max", "freight_cost_brl", 3000, "BRL"),
            _num("prazo_max", "Prazo de entrega em dias úteis", "numeric_max", "delivery_days", 5, "dias"),
        ],
        "options": {"Atlas": ["transportadora atlas", "atlas"], "Boreal": ["transportadora boreal", "boreal"], "Cometa": ["transportadora cometa", "cometa"]},
        "truth_option": "Boreal", "valid_options": ["Boreal", "Cometa"],
        "truth_metrics": {"freight_cost_brl": 2880, "delivery_days": 4},
        "gap_terms": [],
    },
    {
        "id": "I1", "complexity": "intermediario", "name": "Arquitetura do chatbot (fixture do projeto + custos de implantação)",
        "objective": "Escolher a arquitetura do chatbot interno da Lumina Ferramentas (empresa fictícia) que atenda ao custo mensal máximo, ao prazo de implantação do piloto, ao teto de custo do primeiro ano (implantação + 12 meses) e às regras de privacidade, com qualidade aceitável de respostas sobre documentos internos."
        + FORMAT_NOTE.format(names="Opção A, Opção B ou Opção C"),
        "context": "Cenário sintético de demonstração (fixture do projeto) com um documento complementar de custos de implantação. Três opções: SaaS pronto, RAG com API em nuvem e modelo aberto auto-hospedado. Todos os valores são fictícios.",
        "docs": [("01_requisitos_chatbot.md", _fixture("01_requisitos_chatbot.md")), ("02_opcoes_arquitetura.md", _fixture("02_opcoes_arquitetura.md")),
                 ("03_politica_privacidade.md", _fixture("03_politica_privacidade.md")), ("04_custos_implantacao.md", I1_DOC4)],
        "constraints": [
            _num("custo_mensal_max", "Custo mensal recorrente máximo após a implantação", "numeric_max", "monthly_cost_brl", 8000, "BRL"),
            _num("prazo_piloto_max", "Prazo máximo de implantação do piloto", "numeric_max", "delivery_days", 90, "dias"),
            _num("custo_primeiro_ano_max", "Custo do primeiro ano (implantação + 12 meses de custo recorrente)", "numeric_max", "first_year_cost_brl", 100000, "BRL"),
            {"constraint_id": "privacidade_dados", "description": "Dados internos não podem treinar modelos de terceiros; preferência por processamento no Brasil", "kind": "qualitative", "mandatory": False},
        ],
        "options": {"A": [r"opcao a", "nimbuschat", "saas"], "B": [r"opcao b", "aurora"], "C": [r"opcao c", "auto-hospedado", "auto hospedado", "modelo aberto"]},
        "truth_option": "B", "valid_options": ["B"],
        "truth_metrics": {"monthly_cost_brl": 6500, "delivery_days": 60, "first_year_cost_brl": 96000},
        "gap_terms": [],
    },
    {
        "id": "I2", "complexity": "intermediario", "name": "Fornecedor de desenvolvimento do app",
        "objective": "Escolher o fornecedor para desenvolver o aplicativo de agendamento da Clínica Horizonte com o menor custo total em 12 meses (desenvolvimento + taxas únicas + 12 meses de custos mensais após a entrega) entre os que atendem todas as restrições."
        + FORMAT_NOTE.format(names="Norte, Sul ou Leste"),
        "context": "Propostas sintéticas de três fornecedores e um documento de termos complementares recebido depois. Todos os valores são fictícios.",
        "docs": [("propostas_fornecedores_app.md", I2_DOC1), ("termos_complementares.md", I2_DOC2)],
        "constraints": [
            _num("custo_total_12m_max", "Custo total em 12 meses (desenvolvimento + taxas únicas + 12 meses de custos mensais)", "numeric_max", "tco_12m_brl", 285000, "BRL"),
            _num("prazo_entrega_max", "Prazo de entrega do aplicativo", "numeric_max", "delivery_weeks", 18, "semanas"),
            _num("horas_qa_min", "Horas mínimas dedicadas a testes e QA", "numeric_min", "qa_hours", 250, "horas"),
        ],
        "options": {"Norte": ["fornecedor norte", "norte"], "Sul": ["fornecedor sul", "sul"], "Leste": ["fornecedor leste", "leste"]},
        "truth_option": "Sul", "valid_options": ["Sul", "Leste"],
        "truth_metrics": {"tco_12m_brl": 276600, "delivery_weeks": 16, "qa_hours": 280},
        "gap_terms": [],
    },
    {
        "id": "X1", "complexity": "complexo", "name": "CRM com documentos conflitantes",
        "objective": "Recomendar o CRM com o menor custo total em 24 meses (assinaturas + implantação) entre as opções que atendem todos os requisitos obrigatórios da ata, usando as condições comerciais mais recentes."
        + FORMAT_NOTE.format(names="Andes, Boreal ou Cobalto"),
        "context": "Ata de requisitos, planilha preliminar, propostas formais e um e-mail de atualização de um fornecedor. Há divergências entre documentos. Todos os valores são fictícios.",
        "docs": [("ata_requisitos_crm.md", X1_DOC1), ("planilha_preliminar_compras.md", X1_DOC2), ("propostas_formais_crm.md", X1_DOC3), ("email_boreal_atualizacao.md", X1_DOC4)],
        "constraints": [
            _num("custo_24m_max", "Custo total em 24 meses (assinaturas + implantação) para 60 usuários", "numeric_max", "tco_24m_brl", 170000, "BRL"),
            _num("golive_max", "Prazo de go-live após a assinatura", "numeric_max", "go_live_days", 75, "dias"),
            _num("sla_min", "SLA contratual mínimo de disponibilidade", "numeric_min", "sla_pct", "99.5", "%"),
            {"constraint_id": "dados_no_brasil", "description": "Dados de clientes hospedados no Brasil (requisito da ata; verificação qualitativa)", "kind": "qualitative", "mandatory": False},
        ],
        "options": {"Andes": ["crm andes", "andes"], "Boreal": ["crm boreal", "boreal"], "Cobalto": ["crm cobalto", "cobalto"]},
        "truth_option": "Andes", "valid_options": ["Andes", "Boreal"],
        "truth_metrics": {"tco_24m_brl": 151800, "go_live_days": 45, "sla_pct": 99.5},
        "gap_terms": [["cobalto", "sla"]],
    },
    {
        "id": "X2", "complexity": "complexo", "name": "Estratégia de migração do ERP",
        "objective": "Recomendar a estratégia de migração do ERP da Distribuidora Pampa com o menor custo total esperado que cumpra o prazo e o teto definidos pela diretoria."
        + FORMAT_NOTE.format(names="Big bang, Faseada ou Híbrida"),
        "context": "Proposta da consultoria, parecer de auditoria independente com estimativas divergentes e diretrizes da diretoria. Há informação incompleta. Todos os valores são fictícios.",
        "docs": [("proposta_consultoria_erp.md", X2_DOC1), ("parecer_auditoria_independente.md", X2_DOC2), ("diretrizes_diretoria.md", X2_DOC3)],
        "constraints": [
            _num("custo_esperado_max", "Custo total esperado (implantação + dias de parada × R$ 60.000)", "numeric_max", "expected_total_cost_brl", 700000, "BRL"),
            _num("golive_max", "Prazo até o go-live completo", "numeric_max", "go_live_months", 7, "meses"),
        ],
        "options": {"Big bang": ["big bang", "big-bang"], "Faseada": ["faseada"], "Hibrida": ["hibrida"]},
        "truth_option": "Hibrida", "valid_options": ["Hibrida"],
        "truth_metrics": {"expected_total_cost_brl": 640000, "go_live_months": 7},
        "gap_terms": [["treinamento"]],
    },
]

BY_ID = {c["id"]: c for c in CHALLENGES}
