"""Tabela de precos versionada. Preco x tokens e estimativa, nao fatura confirmada."""

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path

NANO = Decimal("0.000000001")
MILLION = Decimal("1000000")


def to_nano(value: Decimal) -> int:
    return int((value / NANO).to_integral_value(rounding=ROUND_CEILING))


def from_nano(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(value) * NANO).quantize(NANO)


@dataclass(frozen=True)
class Price:
    input_per_1m: Decimal
    output_per_1m: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        raw = (Decimal(input_tokens) * self.input_per_1m + Decimal(output_tokens) * self.output_per_1m) / MILLION
        return raw.quantize(NANO, rounding=ROUND_HALF_UP)


class PriceTable:
    def __init__(self, version: str, currency: str, entries: dict[tuple[str, str], Price | None]) -> None:
        self.version = version
        self.currency = currency
        self._entries = entries

    def get(self, provider: str, option: str) -> Price | None:
        return self._entries.get((provider, option))

    def known(self, provider: str, option: str) -> bool:
        return self.get(provider, option) is not None

    def options(self, provider: str) -> list[str]:
        return [o for (p, o) in self._entries if p == provider]

    def max_price(self, provider: str, options: list[str]) -> Price | None:
        """Teto de preco entre rotas permitidas (para roteamento 'auto')."""
        prices = [p for p in (self.get(provider, o) for o in options) if p is not None]
        if not prices:
            return None
        return Price(max(p.input_per_1m for p in prices), max(p.output_per_1m for p in prices))


# Precos SIMULADOS para o provedor mock. Nao representam nenhum provedor real.
MOCK_PRICES: dict[tuple[str, str], Price | None] = {
    ("mock", "mock-default"): Price(Decimal("0.50"), Decimal("1.50")),
    ("mock", "mock-cheap"): Price(Decimal("0.10"), Decimal("0.40")),
    ("mock", "mock-reasoning"): Price(Decimal("2.00"), Decimal("8.00")),
}

NEURALAKE_OPTIONS = ["auto", "text", "code", "reasoning", "reasoning-pro", "multimodal"]


def load_price_table(prices_file: Path | None) -> PriceTable:
    """Mock: precos embutidos. NeuraLake: desconhecidos por padrao; arquivo JSON opcional os define.

    Formato do arquivo: {"version": "...", "currency": "USD", "neuralake": {"auto": {"input_per_1m": "x", "output_per_1m": "y"}}}
    """
    entries: dict[tuple[str, str], Price | None] = dict(MOCK_PRICES)
    version = "mock-prices-v1+neuralake-unknown"
    currency = "USD"
    for opt in NEURALAKE_OPTIONS:
        entries[("neuralake", opt)] = None
    if prices_file and Path(prices_file).exists():
        data = json.loads(Path(prices_file).read_text(encoding="utf-8"))
        version = f"mock-prices-v1+{data.get('version', 'neuralake-file')}"
        currency = data.get("currency", "USD")
        for opt, p in (data.get("neuralake") or {}).items():
            if p and "input_per_1m" in p and "output_per_1m" in p:
                entries[("neuralake", opt)] = Price(Decimal(str(p["input_per_1m"])), Decimal(str(p["output_per_1m"])))
    return PriceTable(version, currency, entries)
