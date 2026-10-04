"""Calculadora x proveniencia: dados do enunciado/restricoes citaveis; valores inventados continuam rejeitados."""

from decimal import Decimal

import pytest

from app.contracts.artifacts import CalcInput, CalculationSpec, EvidenceItem, EvidenceLocator
from app.contracts.challenge import Constraint
from app.contracts.common import ConstraintKind, EvidenceType
from app.evidence.calc import CalculationError, MissingInputError, run_calculation
from app.evidence.pack import brief_items, build_pack, freeze_with_derivations

OBJ = "Reduzir o custo de atendimento. Hoje gastamos R$ 18.500,00 por mes com 3 atendentes; avaliar 12 meses."
CONS = [Constraint(constraint_id="custo-max", description="Custo mensal maximo", kind=ConstraintKind.NUMERIC_MAX,
                   metric_key="monthly_cost_brl", limit=Decimal("15000"), unit="BRL")]


def _pack():
    return build_pack([], brief_items(OBJ, "Implantacao estimada em 0,5 mes.", CONS))


def _run(spec, pack):
    return run_calculation(spec, pack.ids(), {i.evidence_id: i for i in pack.items})


def _in(name, value, *ids):
    return CalcInput(name=name, value=Decimal(value), evidence_ids=list(ids))


def test_reproducao_sem_correcao_enunciado_nao_era_citavel():
    # comportamento antigo: sem fontes anexadas o pacote fica vazio e "12 meses" do enunciado nao tem origem
    old = build_pack([])
    spec = CalculationSpec(function="tco", unit="BRL", inputs=[_in("setup", "0", "ev-brief-obj-001"), _in("monthly", "18500", "ev-brief-obj-001"), _in("months", "12", "ev-brief-obj-001")])
    with pytest.raises(CalculationError, match="inexistentes"):
        run_calculation(spec, old.ids())


def test_brief_vira_evidencia_rastreavel():
    pack = _pack()
    by_id = {i.evidence_id: i for i in pack.items}
    assert by_id["ev-brief-obj-001"].provenance == "challenge:objective"
    assert by_id["ev-brief-obj-001"].locator.section == "enunciado"
    assert by_id["ev-brief-ctx-001"].provenance == "challenge:context"
    assert "15000" in by_id["ev-brief-rst-custo-max"].excerpt
    assert by_id["ev-brief-rst-custo-max"].provenance == "challenge:constraint:custo-max"


def test_constantes_legitimas_do_enunciado_calculam():
    pack = _pack()
    spec = CalculationSpec(function="multiply", unit="BRL", inputs=[_in("monthly", "18500", "ev-brief-obj-001"), _in("months", "12", "ev-brief-obj-001")])
    d = _run(spec, pack)
    assert d.result == Decimal("222000")
    assert d.input_evidence_ids == ["ev-brief-obj-001"]


def test_valores_de_restricao_e_contexto_decimal_ptbr():
    pack = _pack()
    d = _run(CalculationSpec(function="subtract", unit="BRL", inputs=[_in("a", "18500", "ev-brief-obj-001"), _in("b", "15000", "ev-brief-rst-custo-max")]), pack)
    assert d.result == Decimal("3500")
    d2 = _run(CalculationSpec(function="multiply", unit="mes", inputs=[_in("x", "0.5", "ev-brief-ctx-001"), _in("y", "3", "ev-brief-obj-001")]), pack)
    assert d2.result == Decimal("1.5")


def test_valor_inventado_com_id_valido_rejeitado():
    pack = _pack()
    spec = CalculationSpec(function="multiply", unit="BRL", inputs=[_in("monthly", "19999", "ev-brief-obj-001"), _in("months", "12", "ev-brief-obj-001")])
    with pytest.raises(CalculationError, match="nao encontrados") as exc:
        _run(spec, pack)
    assert not isinstance(exc.value, MissingInputError)


def test_referencia_inexistente_e_sem_origem_rejeitadas():
    pack = _pack()
    with pytest.raises(CalculationError, match="inexistentes"):
        _run(CalculationSpec(function="sum", unit="x", inputs=[_in("a", "12", "ev-brief-obj-999")]), pack)
    with pytest.raises(CalculationError, match="sem evidencia"):
        _run(CalculationSpec(function="sum", unit="x", inputs=[_in("a", "12")]), pack)


def test_dado_ausente_vira_pendencia():
    pack = _pack()
    with pytest.raises(MissingInputError, match="denominator"):
        _run(CalculationSpec(function="divide", unit="BRL", inputs=[_in("numerator", "18500", "ev-brief-obj-001")]), pack)


def test_verificador_aceita_enunciado_e_calculo_mas_nao_o_limite_da_regra():
    from app.evaluation.verifiers import _metric_supported
    pack = _pack()
    d = _run(CalculationSpec(function="multiply", unit="BRL", inputs=[_in("m", "18500", "ev-brief-obj-001"), _in("n", "12", "ev-brief-obj-001")]), pack)
    item = EvidenceItem(evidence_id="drv-c1-t1", type=EvidenceType.DERIVED_CALCULATION, excerpt="x", provenance="specialist:calculation:c1:t1", derivation=d)
    frozen = freeze_with_derivations(pack, [item], [])
    assert _metric_supported(Decimal("222000"), ["drv-c1-t1"], frozen)[0]
    assert _metric_supported(Decimal("18500"), ["ev-brief-obj-001"], frozen)[0]
    assert not _metric_supported(Decimal("15000"), ["ev-brief-rst-custo-max"], frozen)[0]


def test_resultado_calculado_e_citavel_por_outro_calculo():
    pack = _pack()
    d = _run(CalculationSpec(function="multiply", unit="BRL", inputs=[_in("m", "18500", "ev-brief-obj-001"), _in("n", "12", "ev-brief-obj-001")]), pack)
    item = EvidenceItem(evidence_id="drv-c1-t1", type=EvidenceType.DERIVED_CALCULATION, excerpt="x", locator=EvidenceLocator(section="derivacao"),
                        provenance="specialist:calculation:c1:t1", derivation=d)
    frozen = freeze_with_derivations(pack, [item], [])
    assert "drv-c1-t1" in frozen.ids()
    d2 = _run(CalculationSpec(function="per_unit", unit="BRL", inputs=[_in("total", "222000", "drv-c1-t1"), _in("units", "3", "ev-brief-obj-001")]), frozen)
    assert d2.result == Decimal("74000")
    with pytest.raises(CalculationError, match="nao encontrados"):
        _run(CalculationSpec(function="per_unit", unit="BRL", inputs=[_in("total", "200000", "drv-c1-t1"), _in("units", "3", "ev-brief-obj-001")]), frozen)
