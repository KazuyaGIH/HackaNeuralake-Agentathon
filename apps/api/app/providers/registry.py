"""Registro dos provedores reais: modelos oferecidos, precos publicos e escolhas padrao por papel.

Precos sao estimativas por tabela publica (nao fatura): NeuraLake em fixtures/prices; OpenAI, Gemini e Claude
consultados nas paginas oficiais em 02/10/2026. Precos do Gemini Flash 3.x sao promocionais ate 31/12/2026.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.contracts.common import Provider


@dataclass(frozen=True)
class ModelSpec:
    option: str
    label: str
    input_per_1m: Decimal | None = None
    output_per_1m: Decimal | None = None
    reasoning: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    provider: Provider
    label: str
    key_hint: str
    models: tuple[ModelSpec, ...]
    # Modelo padrao por papel quando o usuario nao escolhe (juiz e "principal" das estrategias).
    judge_default: str
    preset_main: dict[str, str] = field(default_factory=dict)
    preset_secondary: dict[str, str] = field(default_factory=dict)


def _d(v: str) -> Decimal:
    return Decimal(v)


PROVIDERS: dict[Provider, ProviderSpec] = {
    Provider.NEURALAKE: ProviderSpec(
        Provider.NEURALAKE, "NeuraLake", "começa com nlk-",
        models=(
            ModelSpec("auto", "NeuraLake · automático (escolhe o modelo)"),
            ModelSpec("text", "NeuraLake · texto"),
            ModelSpec("code", "NeuraLake · código"),
            ModelSpec("reasoning", "NeuraLake · raciocínio", reasoning=True),
            ModelSpec("reasoning-pro", "NeuraLake · raciocínio avançado", reasoning=True),
            ModelSpec("multimodal", "NeuraLake · multimodal"),
        ),
        # Teste real (02/10/2026): "reasoning" deu 504 no gateway da NeuraLake ao julgar 2 propostas; "text" respondeu em ~25s.
        judge_default="text",
        preset_main={"balanced": "auto", "cost": "text", "robust": "reasoning", "explorer": "reasoning-pro"},
        preset_secondary={"balanced": "text", "robust": "text", "explorer": "text"},
    ),
    Provider.OPENAI: ProviderSpec(
        Provider.OPENAI, "OpenAI", "começa com sk-",
        models=(
            ModelSpec("gpt-6.1-sol", "OpenAI · GPT-6.1 Sol", _d("2.00"), _d("10.00"), reasoning=True),
            ModelSpec("gpt-6-astra", "OpenAI · GPT-6 Astra (mais forte)", _d("10.00"), _d("50.00"), reasoning=True),
            ModelSpec("gpt-6-luna", "OpenAI · GPT-6 Luna (econômico)", _d("0.10"), _d("0.50")),
            ModelSpec("gpt-5-mini", "OpenAI · GPT-5 mini", _d("0.25"), _d("2.00")),
        ),
        judge_default="gpt-6.1-sol",
        preset_main={"balanced": "gpt-6.1-sol", "cost": "gpt-6-luna", "robust": "gpt-6.1-sol", "explorer": "gpt-6.1-sol"},
        preset_secondary={"balanced": "gpt-6-luna", "robust": "gpt-6-luna", "explorer": "gpt-6-luna"},
    ),
    Provider.GEMINI: ProviderSpec(
        Provider.GEMINI, "Gemini", "começa com AIza",
        models=(
            ModelSpec("gemini-3.8-flash", "Gemini · 3.8 Flash", _d("0.75"), _d("3.75")),
            ModelSpec("gemini-2.5-pro", "Gemini · 2.5 Pro", _d("1.25"), _d("10.00"), reasoning=True),
            ModelSpec("gemini-2.5-flash-lite", "Gemini · 2.5 Flash-Lite (econômico)", _d("0.10"), _d("0.40")),
            ModelSpec("gemini-3.1-pro-preview", "Gemini · 3.1 Pro (prévia, só plano pago)", _d("2.00"), _d("12.00"), reasoning=True),
        ),
        # Padroes so com modelos que tem plano gratis na API do Gemini (consultado em 02/10/2026).
        judge_default="gemini-2.5-pro",
        preset_main={"balanced": "gemini-3.8-flash", "cost": "gemini-2.5-flash-lite", "robust": "gemini-2.5-pro", "explorer": "gemini-3.8-flash"},
        preset_secondary={"balanced": "gemini-2.5-flash-lite", "robust": "gemini-2.5-flash-lite", "explorer": "gemini-2.5-flash-lite"},
    ),
    Provider.ANTHROPIC: ProviderSpec(
        Provider.ANTHROPIC, "Claude", "começa com sk-ant-",
        models=(
            ModelSpec("claude-opus-5-5", "Claude · Opus 5.5", _d("4.00"), _d("20.00"), reasoning=True),
            ModelSpec("claude-sonnet-5-5", "Claude · Sonnet 5.5", _d("2.00"), _d("10.00"), reasoning=True),
            ModelSpec("claude-haiku-4-5", "Claude · Haiku 4.5 (econômico)", _d("1.00"), _d("5.00")),
        ),
        judge_default="claude-opus-5-5",
        preset_main={"balanced": "claude-opus-5-5", "cost": "claude-haiku-4-5", "robust": "claude-opus-5-5", "explorer": "claude-opus-5-5"},
        preset_secondary={"balanced": "claude-haiku-4-5", "robust": "claude-haiku-4-5", "explorer": "claude-haiku-4-5"},
    ),
}


def default_option(provider: Provider | str) -> str:
    """Modelo padrao do provedor para quem nao escolheu (o mock usa mock-default)."""
    spec = PROVIDERS.get(Provider(str(provider)))
    return spec.judge_default if spec else "mock-default"


def build_adapter(provider: Provider | str, api_key: str, settings):  # noqa: ANN001, ANN201 - Settings importado tarde
    p = Provider(str(provider))
    if p == Provider.NEURALAKE:
        from app.providers.neuralake import NeuraLakeAdapter

        return NeuraLakeAdapter(api_key=api_key, base_url=settings.neuralake_base_url, json_mode=settings.neuralake_json_mode)
    if p == Provider.OPENAI:
        from app.providers.openai_compat import OpenAIAdapter

        return OpenAIAdapter(api_key=api_key, base_url=settings.openai_base_url)
    if p == Provider.GEMINI:
        from app.providers.openai_compat import GeminiAdapter

        return GeminiAdapter(api_key=api_key, base_url=settings.gemini_base_url)
    if p == Provider.ANTHROPIC:
        from app.providers.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(api_key=api_key)
    raise ValueError(f"provedor sem adaptador real: {provider}")


def server_key(provider: Provider | str, settings) -> str | None:  # noqa: ANN001
    return {
        Provider.NEURALAKE: settings.neuralake_api_key,
        Provider.OPENAI: settings.openai_api_key,
        Provider.GEMINI: settings.gemini_api_key,
        Provider.ANTHROPIC: settings.anthropic_api_key,
    }.get(Provider(str(provider))) or None


# Header HTTP por provedor para a chave trazida pelo navegador.
KEY_HEADERS: dict[Provider, str] = {
    Provider.NEURALAKE: "x-neuralake-key",
    Provider.OPENAI: "x-openai-key",
    Provider.GEMINI: "x-gemini-key",
    Provider.ANTHROPIC: "x-anthropic-key",
}
