"""Agente de calculo: funcoes numericas pre-definidas com entradas tipadas. Sem eval, shell ou codigo gerado."""

import re
from collections.abc import Callable
from decimal import Decimal, DivisionByZero, InvalidOperation

from app.contracts.artifacts import CalcInput, CalculationSpec, Derivation, EvidenceItem

Fn = Callable[[dict[str, Decimal]], tuple[Decimal, str]]


class CalculationError(ValueError):
    """Entrada invalida: funcao desconhecida, referencia inexistente, valor sem origem ou nao encontrado na origem."""


class MissingInputError(CalculationError):
    """Informacao ausente: a funcao exige uma entrada que nao foi fornecida (vira pendencia, nao erro de calculo)."""


_REQUIRED: dict[str, tuple[str, ...]] = {
    "subtract": ("a", "b"), "divide": ("numerator", "denominator"), "percent_of": ("value", "percent"),
    "percent_change": ("old", "new"), "annual_from_monthly": ("monthly",), "monthly_from_annual": ("annual",),
    "tco": ("setup", "monthly", "months"), "per_unit": ("total", "units"),
}


def _need(inputs: dict[str, Decimal], *names: str) -> list[Decimal]:
    missing = [n for n in names if n not in inputs]
    if missing:
        raise MissingInputError(f"entradas obrigatorias ausentes: {', '.join(missing)}")
    return [inputs[n] for n in names]


def _sum(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    if not i:
        raise CalculationError("sum exige ao menos uma entrada")
    return sum(i.values(), Decimal("0")), " + ".join(i.keys())


def _subtract(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    a, b = _need(i, "a", "b")
    return a - b, "a - b"


def _multiply(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    if not i:
        raise CalculationError("multiply exige ao menos uma entrada")
    out = Decimal("1")
    for v in i.values():
        out *= v
    return out, " * ".join(i.keys())


def _divide(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    a, b = _need(i, "numerator", "denominator")
    if b == 0:
        raise CalculationError("divisao por zero")
    return a / b, "numerator / denominator"


def _percent_of(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    v, p = _need(i, "value", "percent")
    return v * p / Decimal("100"), "value * percent / 100"


def _percent_change(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    a, b = _need(i, "old", "new")
    if a == 0:
        raise CalculationError("valor antigo zero: variacao percentual indefinida")
    return (b - a) / a * Decimal("100"), "(new - old) / old * 100"


def _annual_from_monthly(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    (m,) = _need(i, "monthly")
    return m * Decimal("12"), "monthly * 12"


def _monthly_from_annual(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    (a,) = _need(i, "annual")
    return a / Decimal("12"), "annual / 12"


def _tco(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    setup, monthly, months = _need(i, "setup", "monthly", "months")
    if months < 0:
        raise CalculationError("months negativo")
    return setup + monthly * months, "setup + monthly * months"


def _min(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    if not i:
        raise CalculationError("min exige entradas")
    return min(i.values()), f"min({', '.join(i.keys())})"


def _max(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    if not i:
        raise CalculationError("max exige entradas")
    return max(i.values()), f"max({', '.join(i.keys())})"


def _average(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    if not i:
        raise CalculationError("average exige entradas")
    return sum(i.values(), Decimal("0")) / Decimal(len(i)), f"avg({', '.join(i.keys())})"


def _per_unit(i: dict[str, Decimal]) -> tuple[Decimal, str]:
    total, units = _need(i, "total", "units")
    if units == 0:
        raise CalculationError("units zero")
    return total / units, "total / units"


FUNCTIONS: dict[str, Fn] = {
    "sum": _sum,
    "subtract": _subtract,
    "multiply": _multiply,
    "divide": _divide,
    "percent_of": _percent_of,
    "percent_change": _percent_change,
    "annual_from_monthly": _annual_from_monthly,
    "monthly_from_annual": _monthly_from_annual,
    "tco": _tco,
    "min": _min,
    "max": _max,
    "average": _average,
    "per_unit": _per_unit,
}

MAX_ABS = Decimal("1e15")


def catalog_text() -> str:
    """Catalogo exato (derivado de FUNCTIONS/_REQUIRED) para o planejador: funcao e nomes de entrada aceitos."""
    parts = []
    for name in FUNCTIONS:
        req = _REQUIRED.get(name)
        parts.append(f"{name}({', '.join(req)})" if req else f"{name}(1 a 8 entradas com nomes livres)")
    return (
        "; ".join(parts)
        + ". Cada entrada: {name, value (numero), unit, evidence_ids}; o campo name deve ser EXATAMENTE o nome do parametro "
        "(nao uma descricao). Exemplo: {\"function\": \"tco\", \"unit\": \"BRL\", \"inputs\": [{\"name\": \"setup\", \"value\": \"40000\", "
        "\"unit\": \"BRL\", \"evidence_ids\": [\"<id do trecho com 40000>\"]}, {\"name\": \"monthly\", \"value\": \"7200\", \"unit\": \"BRL\", "
        "\"evidence_ids\": [\"<id do trecho com 7200>\"]}, {\"name\": \"months\", \"value\": \"12\", \"unit\": \"meses\", \"evidence_ids\": "
        "[\"<id do trecho com 12>\"]}]}. Nenhuma outra funcao existe (sem comparacoes)."
    )

_NUM = re.compile(r"(?<![\w.,])-?\d[\d.,]*")


def _readings(token: str) -> set[Decimal]:
    """Leituras possiveis de um numero escrito em pt-BR ou en (ex.: '1.200,50', '1,200.50', '0,5', '12')."""
    t = token.rstrip(".,")
    out: set[Decimal] = set()
    for thousands, dec in ((".", ","), (",", ".")):
        s = t.replace(thousands, "").replace(dec, ".") if t.count(dec) <= 1 else None
        if s is None:
            continue
        try:
            out.add(Decimal(s))
        except InvalidOperation:
            pass
    return out


def numbers_in(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for m in _NUM.finditer(text):
        out |= _readings(m.group(0))
    return out


def _supported_values(item: EvidenceItem) -> set[Decimal]:
    if item.derivation is not None:
        return {Decimal(item.derivation.result)}
    return numbers_in(item.excerpt)


def resolve_brief_refs(spec: CalculationSpec, brief: list[EvidenceItem]) -> tuple[CalculationSpec, list[str]]:
    """Entrada sem evidence_ids cujo valor aparece literalmente no enunciado/contexto/restricoes recebe a referencia desse
    trecho (dado fornecido pelo cliente). Valores que nao aparecem continuam sem origem e serao rejeitados."""
    resolved: list[str] = []
    inputs = []
    for i in spec.inputs:
        if not i.evidence_ids:
            hits = [b.evidence_id for b in brief if Decimal(i.value) in numbers_in(b.excerpt)]
            if hits:
                i = i.model_copy(update={"evidence_ids": hits[:1]})
                resolved.append(f"{i.name}={i.value}<-{hits[0]}")
        inputs.append(i)
    return spec.model_copy(update={"inputs": inputs}), resolved


def run_calculation(spec: CalculationSpec, known_evidence_ids: set[str], evidence: dict[str, EvidenceItem] | None = None) -> Derivation:
    """Executa o calculo. Com `evidence`, cada valor precisa aparecer em ao menos uma evidencia citada (nao basta um ID valido)."""
    fn = FUNCTIONS.get(spec.function)
    if fn is None:
        raise CalculationError(f"funcao desconhecida: {spec.function}. Permitidas: {', '.join(sorted(FUNCTIONS))}")
    names = [i.name for i in spec.inputs]
    if len(names) != len(set(names)):
        raise CalculationError("nomes de entrada duplicados")
    bad_refs = sorted({e for i in spec.inputs for e in i.evidence_ids if e not in known_evidence_ids})
    if bad_refs:
        raise CalculationError(f"entradas referenciam evidencias inexistentes: {', '.join(bad_refs)}")
    unsupported = [i.name for i in spec.inputs if not i.evidence_ids]
    if unsupported:
        raise CalculationError(f"entradas sem evidencia de origem: {', '.join(unsupported)}")
    if evidence is not None:
        mismatched = [
            f"{i.name}={i.value}" for i in spec.inputs
            if not any(Decimal(i.value) in _supported_values(evidence[e]) for e in i.evidence_ids if e in evidence)
        ]
        if mismatched:
            raise CalculationError(f"valores nao encontrados nas evidencias citadas: {', '.join(mismatched)}")
    values = {i.name: Decimal(i.value) for i in spec.inputs}
    if fn_need := _REQUIRED.get(spec.function):
        if unknown := [n for n in values if n not in fn_need]:
            raise CalculationError(f"nomes de entrada invalidos para {spec.function}: {', '.join(unknown)} (esperado: {', '.join(fn_need)})")
        if absent := [n for n in fn_need if n not in values]:
            raise MissingInputError(f"informacao ausente para {spec.function}: {', '.join(absent)}")
    if any(abs(v) > MAX_ABS for v in values.values()):
        raise CalculationError("entrada fora da faixa suportada")
    try:
        result, formula = fn(values)
    except (InvalidOperation, DivisionByZero) as exc:
        raise CalculationError(f"erro numerico: {exc}") from exc
    return Derivation(
        function=spec.function,
        formula=formula,
        inputs=[CalcInput(**i.model_dump()) for i in spec.inputs],
        result=result.quantize(Decimal("0.000001")) if result.as_tuple().exponent < -6 else result,
        unit=spec.unit,
        input_evidence_ids=sorted({e for i in spec.inputs for e in i.evidence_ids}),
    )
