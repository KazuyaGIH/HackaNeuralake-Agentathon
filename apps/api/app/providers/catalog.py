"""Catalogo do servidor: provedores, opcoes, capacidades, precos, presets e limites. Nunca contem segredos."""

from dataclasses import dataclass, field

from app import APP_VERSION
from app.budget.prices import PriceTable
from app.config import Settings
from app.contracts.challenge import (
    JUDGE_PERSONAS,
    MAX_ATTEMPTS,
    MAX_CANDIDATES,
    MAX_CONCURRENT_CALLS,
    MAX_CRITIQUE_ROUNDS,
    MAX_JUDGES,
    MAX_SOURCES,
    MAX_SPECIALIST_TASKS,
    MAX_TOTAL_CALLS,
    MIN_CANDIDATES,
    default_rubric,
    persona_rubric,
)
from app.contracts.common import REAL_PROVIDERS, Provider, SpecialistKind
from app.contracts.runs import CatalogJudgePersona, CatalogModelOption, CatalogPreset, CatalogResponse
from app.providers.registry import PROVIDERS, server_key, thinking_headroom

CATALOG_VERSION = "2026-09-30.1"

MOCK_SCENARIOS = [
    "default",
    "unauthorized_specialist",
    "judge_invalid_then_valid",
    "judge_fails",
    "transient_error_once",
    "timeout_unknown_usage",
    "tie",
    "all_ineligible",
    "insufficient_evidence",
]


@dataclass(frozen=True)
class ModelOptionSpec:
    provider: Provider
    option: str
    label: str
    kind: str
    capabilities: tuple[str, ...]
    max_context_tokens: int | None
    max_output_tokens: int
    supports_json_mode: bool


MODEL_OPTIONS: list[ModelOptionSpec] = [
    ModelOptionSpec(Provider.MOCK, "mock-default", "Simulado padrão", "fixed_model", ("text", "json"), 128000, 8000, True),
    ModelOptionSpec(Provider.MOCK, "mock-cheap", "Simulado econômico", "fixed_model", ("text", "json"), 32000, 4000, True),
    ModelOptionSpec(Provider.MOCK, "mock-reasoning", "Simulado raciocínio", "fixed_model", ("text", "json", "reasoning"), 128000, 8000, True),
]
for _prov, _spec in PROVIDERS.items():
    for _m in _spec.models:
        MODEL_OPTIONS.append(
            ModelOptionSpec(
                _prov, _m.option, _m.label, "routing_capability" if _prov == Provider.NEURALAKE else "fixed_model",
                ("text", "json-requested") + (("reasoning",) if _m.reasoning else ()),
                None, 8000, False,
            )
        )


@dataclass(frozen=True)
class PresetSpec:
    preset: str
    label: str
    description: str
    instructions: str
    model_option_by_provider: dict[str, str]
    allowed_specialists: tuple[SpecialistKind, ...] = (SpecialistKind.DOCUMENT_RESEARCH, SpecialistKind.CALCULATION)
    max_specialist_tasks: int = MAX_SPECIALIST_TASKS
    color: str = "#2563eb"
    # Modelo economico por provedor para tarefas internas simples; ausente = equipe usa so o principal.
    secondary_by_provider: dict[str, str] = field(default_factory=dict)


PRESETS: list[PresetSpec] = [
    PresetSpec(
        "balanced", "Equilíbrio",
        "Equilibra custo, prazo e qualidade; usa pesquisa e cálculo quando há dados.",
        "Voce e o pensante de uma equipe concorrente. Busque a alternativa com melhor equilibrio entre custo, prazo, "
        "risco e qualidade. Cite evidencias por ID. Declare metricas numericas exigidas pelas restricoes com unidade e "
        "evidencia. Registre hipoteses e lacunas explicitamente.",
        {"mock": "mock-default", "neuralake": "auto"},
        color="#2563eb",
        secondary_by_provider={"mock": "mock-cheap", "neuralake": "text"},
    ),
    PresetSpec(
        "cost", "Custo",
        "Prioriza menor custo total e simplicidade operacional.",
        "Voce e o pensante de uma equipe concorrente focada em custo. Prefira a alternativa de menor custo total que "
        "respeite todas as restricoes obrigatorias. Quantifique custos com evidencias por ID e explicite o que foi "
        "sacrificado em troca da economia.",
        {"mock": "mock-cheap", "neuralake": "text"},
        color="#16a34a",
    ),
    PresetSpec(
        "robust", "Robustez",
        "Prioriza privacidade, resiliência e qualidade das respostas, aceitando custo maior dentro do teto.",
        "Voce e o pensante de uma equipe concorrente focada em robustez. Priorize privacidade, confiabilidade e "
        "qualidade, mantendo-se dentro das restricoes obrigatorias. Explicite riscos residuais, dependencias e "
        "planos de contingencia, sempre com evidencias por ID.",
        {"mock": "mock-reasoning", "neuralake": "reasoning"},
        color="#d97706",
        secondary_by_provider={"mock": "mock-cheap", "neuralake": "text"},
    ),
    PresetSpec(
        "explorer", "Exploração",
        "Considera alternativas menos óbvias e questiona premissas.",
        "Voce e o pensante de uma equipe concorrente exploratoria. Questione premissas do desafio, considere ao menos "
        "uma alternativa nao convencional e compare-a com a opcao dominante usando evidencias por ID.",
        {"mock": "mock-default", "neuralake": "reasoning-pro"},
        color="#9333ea",
        secondary_by_provider={"mock": "mock-cheap", "neuralake": "text"},
    ),
]

# Modelos de cada estrategia nos demais provedores reais vem do registro (OpenAI, Gemini, Claude).
PRESETS = [
    PresetSpec(
        p.preset, p.label, p.description, p.instructions,
        {**p.model_option_by_provider, **{str(prov): s.preset_main[p.preset] for prov, s in PROVIDERS.items() if p.preset in s.preset_main}},
        p.allowed_specialists, p.max_specialist_tasks, p.color,
        {**p.secondary_by_provider, **{str(prov): s.preset_secondary[p.preset] for prov, s in PROVIDERS.items() if p.preset in s.preset_secondary}},
    )
    for p in PRESETS
]

SPECIALISTS = [
    {
        "kind": SpecialistKind.DOCUMENT_RESEARCH,
        "label": "Pesquisa nos documentos",
        "description": "Recupera trechos do pacote comum de evidencias por consulta e resume achados com IDs. Sem busca externa.",
        "uses_inference": True,
    },
    {
        "kind": SpecialistKind.CALCULATION,
        "label": "Calculo tipado",
        "description": "Executa funcoes numericas pre-definidas com entradas tipadas referenciando evidencias. Sem eval/codigo gerado.",
        "uses_inference": False,
    },
]


@dataclass
class Catalog:
    settings: Settings
    prices: PriceTable
    unavailable: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Sem chave no servidor o provedor fica "indisponivel no servidor"; o usuario ainda pode trazer a propria chave.
        for prov in REAL_PROVIDERS:
            if not server_key(prov, self.settings):
                self.unavailable[str(prov)] = (
                    f"{PROVIDERS[prov].label}: conecte a sua chave na aba Orcamento e modo "
                    f"(ou defina AGENTATHON_{str(prov).upper()}_API_KEY no servidor)."
                )

    def provider_enabled(self, provider: Provider | str) -> bool:
        return str(provider) not in self.unavailable

    def option_spec(self, provider: Provider | str, option: str) -> ModelOptionSpec | None:
        return next((m for m in MODEL_OPTIONS if m.provider == provider and m.option == option), None)

    def preset(self, name: str) -> PresetSpec | None:
        return next((p for p in PRESETS if p.preset == name), None)

    def specialist_kinds(self) -> set[str]:
        return {str(s["kind"]) for s in SPECIALISTS}

    def response(self, demo_available: bool) -> CatalogResponse:
        options = []
        for m in MODEL_OPTIONS:
            price = self.prices.get(m.provider, m.option)
            enabled = self.provider_enabled(m.provider)
            options.append(
                CatalogModelOption(
                    provider=m.provider, option=m.option, label=m.label, kind=m.kind,
                    capabilities=list(m.capabilities), max_context_tokens=m.max_context_tokens,
                    max_output_tokens=m.max_output_tokens, supports_json_mode=m.supports_json_mode,
                    price_input_per_1m=price.input_per_1m if price else None,
                    price_output_per_1m=price.output_per_1m if price else None,
                    price_version=self.prices.version, price_known=price is not None, enabled=enabled,
                    unavailable_reason=self.unavailable.get(str(m.provider)),
                    thinking_tokens=thinking_headroom(m.provider, m.option),
                )
            )
        return CatalogResponse(
            app_version=APP_VERSION,
            catalog_version=CATALOG_VERSION,
            modes=["mock"] + (["real"] if any(self.provider_enabled(p) for p in REAL_PROVIDERS) else []),
            providers={
                "mock": {"enabled": True, "label": "Simulado (determinístico, sem rede)", "simulated": True},
                **{
                    str(prov): {
                        "enabled": self.provider_enabled(prov),
                        "requires_password": bool(self.settings.real_mode_password),
                        # Sem chave no servidor, o usuario pode trazer a propria (header X-<Provedor>-Key).
                        "accepts_client_key": True,
                        "label": spec.label,
                        "key_hint": spec.key_hint,
                        "simulated": False,
                        "unavailable_reason": self.unavailable.get(str(prov)),
                        "default_model": spec.judge_default,
                    }
                    for prov, spec in PROVIDERS.items()
                },
            },
            model_options=options,
            specialists=[{**s, "kind": str(s["kind"])} for s in SPECIALISTS],
            presets=[
                CatalogPreset(
                    preset=p.preset, label=p.label, description=p.description, instructions=p.instructions,
                    model_option_by_provider=p.model_option_by_provider,
                    secondary_by_provider=p.secondary_by_provider,
                    allowed_specialists=[str(k) for k in p.allowed_specialists],
                    max_specialist_tasks=p.max_specialist_tasks,
                )
                for p in PRESETS
            ],
            limits={
                "candidates": {"min": MIN_CANDIDATES, "max": MAX_CANDIDATES, "default": 2},
                "judges": {"min": 1, "max": MAX_JUDGES, "default": 1},
                "specialist_tasks_per_candidate": {"max": MAX_SPECIALIST_TASKS, "default": 2},
                "critique_rounds": {"max": MAX_CRITIQUE_ROUNDS, "default": 1},
                "concurrent_calls": {"max": MAX_CONCURRENT_CALLS, "default": 2},
                "attempts_per_call": {"max": MAX_ATTEMPTS, "default": 2},
                "total_calls": {"max": MAX_TOTAL_CALLS, "default": 32},
                "run_deadline_s": {"default": 300, "server_max": self.settings.server_max_deadline_s},
                "call_timeout_s": {"default": 60},
                "sources": {"max": MAX_SOURCES, "max_upload_mb": self.settings.max_upload_mb, "max_pdf_pages": self.settings.max_pdf_pages},
            },
            default_rubric=default_rubric().model_dump(mode="json"),
            judge_personas=[
                CatalogJudgePersona(persona=key, name=p["name"], description=p["description"], instructions=p["instructions"],
                                    rubric=persona_rubric(key).model_dump(mode="json"))
                for key, p in JUDGE_PERSONAS.items()
            ],
            mock_scenarios=MOCK_SCENARIOS,
            demo_preset_available=demo_available,
        )
