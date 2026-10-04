"""Testes unitarios dos controles criticos: formula de ranking, elegibilidade, calculo tipado, extracao e contratos."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts.artifacts import (
    CalcInput,
    CalculationSpec,
    CriterionGrade,
    Evaluation,
    EvidenceItem,
    EvidencePack,
    Proposal,
    ProposalMetric,
)
from app.contracts.challenge import ChallengeConfig, Constraint, Rubric, RubricCriterion, default_rubric
from app.contracts.common import CheckResult, CostQuality, DecisionStatus, Eligibility, EvidenceType
from app.evaluation.ranking import CandidateInput, RankingError, compute_ranking, efficiency_grade, score, validate_grades
from app.evaluation.verifiers import verify_proposal
from app.evidence.calc import CalculationError, run_calculation
from app.evidence.extract import ExtractionError, extract
from app.evidence.pack import SourceText, build_pack

RUBRIC = default_rubric()


def _pack() -> EvidencePack:
    text = (
        "Opcao B: custo mensal recorrente estimado de R$ 6.500 por mes no volume previsto, com regiao brasileira disponivel.\n\n"
        "Opcao B: implantacao em 60 dias, incluindo indexacao dos documentos internos e testes com o RH e a TI.\n\n"
        "Opcao A: assinatura SaaS com custo mensal recorrente de R$ 9.800 por mes para todos os colaboradores ativos."
    )
    src = SourceText("s1", "doc", "text/markdown", text, "a" * 64, None, False, [])
    return build_pack([src])


def _proposal(metrics: dict[str, ProposalMetric], evidence_ids: list[str]) -> Proposal:
    return Proposal(title="t", recommendation="r", metrics=metrics, evidence_ids=evidence_ids, candidate_id="c1", version=1)


# ------------------------------------------------------------------ formula de ranking


def test_score_formula_known_inputs() -> None:
    grades = {"adherence": Decimal(10), "evidence_quality": Decimal(10), "reasoning": Decimal(10), "completeness": Decimal(10), "efficiency": Decimal(10), "uncertainty": Decimal(10)}
    assert score(RUBRIC, grades) == Decimal(100)
    grades["adherence"] = Decimal(5)
    assert score(RUBRIC, grades) == Decimal(85)  # 30 * 5 / 10 = 15 perdidos
    grades = {k: Decimal("7.5") for k in grades}
    assert score(RUBRIC, grades) == Decimal(75)


def test_efficiency_grade_rule() -> None:
    assert efficiency_grade(Decimal("0"), Decimal("1")) == Decimal(10)
    assert efficiency_grade(Decimal("0.25"), Decimal("1")) == Decimal("7.5")
    assert efficiency_grade(Decimal("2"), Decimal("1")) == Decimal(0)
    with pytest.raises(RankingError):
        efficiency_grade(Decimal("1"), Decimal("0"))


def test_grades_out_of_range_or_missing_rejected() -> None:
    with pytest.raises(RankingError, match="ausentes"):
        validate_grades(RUBRIC, {"adherence": Decimal(5)})
    full = {c.criterion_id: Decimal(5) for c in RUBRIC.criteria}
    full["adherence"] = Decimal(12)
    with pytest.raises(RankingError, match="fora da faixa"):
        validate_grades(RUBRIC, full)
    with pytest.raises(ValidationError):
        CriterionGrade(criterion_id="x", grade=Decimal(11), justification="j")


def test_rubric_weights_must_sum_100() -> None:
    with pytest.raises(ValidationError, match="somar 100"):
        Rubric(criteria=[RubricCriterion(criterion_id="a", name="a", weight=Decimal(50))])
    with pytest.raises(ValidationError, match="duplicado"):
        Rubric(criteria=[RubricCriterion(criterion_id="a", name="a", weight=Decimal(50)), RubricCriterion(criterion_id="a", name="b", weight=Decimal(50))])


def _eval(cid: str, grade: int) -> Evaluation:
    return Evaluation(candidate_id=cid, proposal_version=1, judge_label="P1", rubric_hash="h", pack_version=2, status="complete",
                      grades=[CriterionGrade(criterion_id=c.criterion_id, grade=Decimal(grade), justification="j") for c in RUBRIC.criteria if c.computed_by == "judge"])


def _ver(cid: str, elig: Eligibility):
    from app.contracts.artifacts import Verification

    return Verification(candidate_id=cid, proposal_version=1, checks=[], valid_evidence_ids=[], invalid_evidence_ids=[], eligibility=elig, reasons=["motivo"] if elig != Eligibility.ELIGIBLE else [])


def test_ranking_ineligible_even_with_high_grade() -> None:
    inputs = [
        CandidateInput("c1", "A", 1, _ver("c1", Eligibility.INELIGIBLE), _eval("c1", 10), Decimal("0.01"), Decimal("1"), CostQuality.ESTIMATED),
        CandidateInput("c2", "B", 1, _ver("c2", Eligibility.ELIGIBLE), _eval("c2", 6), Decimal("0.01"), Decimal("1"), CostQuality.ESTIMATED),
    ]
    res = compute_ranking(RUBRIC, inputs)
    assert res.decision_status == DecisionStatus.RANKED
    assert res.winner_candidate_id == "c2"
    a = next(e for e in res.entries if e.candidate_id == "c1")
    assert a.eligibility == Eligibility.INELIGIBLE and a.score_0_100 > Decimal(90) and a.disqualification_reason


def test_ranking_tie_and_no_eligible_and_unknown_cost() -> None:
    tie = compute_ranking(RUBRIC, [
        CandidateInput("c1", "A", 1, _ver("c1", Eligibility.ELIGIBLE), _eval("c1", 8), Decimal("0.1"), Decimal("1"), CostQuality.ESTIMATED),
        CandidateInput("c2", "B", 1, _ver("c2", Eligibility.ELIGIBLE), _eval("c2", 8), Decimal("0.1"), Decimal("1"), CostQuality.ESTIMATED),
    ])
    assert tie.decision_status == DecisionStatus.TIE and tie.winner_candidate_id is None and set(tie.co_leaders) == {"c1", "c2"}
    assert [e.rank for e in sorted(tie.entries, key=lambda e: e.candidate_id)] == [1, 1]

    none = compute_ranking(RUBRIC, [CandidateInput("c1", "A", 1, _ver("c1", Eligibility.INELIGIBLE), _eval("c1", 9), Decimal("0.1"), Decimal("1"), CostQuality.ESTIMATED)])
    assert none.decision_status == DecisionStatus.NO_ELIGIBLE_CANDIDATE and none.winner_candidate_id is None

    pending = compute_ranking(RUBRIC, [CandidateInput("c1", "A", 1, _ver("c1", Eligibility.PENDING), _eval("c1", 9), Decimal("0.1"), Decimal("1"), CostQuality.ESTIMATED)])
    assert pending.decision_status == DecisionStatus.INCONCLUSIVE

    unknown = compute_ranking(RUBRIC, [CandidateInput("c1", "A", 1, _ver("c1", Eligibility.ELIGIBLE), _eval("c1", 9), None, Decimal("1"), CostQuality.UNKNOWN)])
    assert unknown.decision_status == DecisionStatus.INCONCLUSIVE and unknown.winner_candidate_id is None
    assert unknown.entries[0].efficiency is not None and unknown.entries[0].efficiency.grade is None


def test_ranking_panel_weighted_mean_and_missing_judge() -> None:
    from app.evaluation.ranking import PanelJudge

    panel = [PanelJudge("j1", "Padrao", Decimal(3), RUBRIC), PanelJudge("j2", "Outro", Decimal(1), RUBRIC)]

    def ev(cid: str, jid: str, grade: int) -> Evaluation:
        return _eval(cid, grade).model_copy(update={"judge_id": jid})

    full = compute_ranking(panel, [
        CandidateInput("c1", "A", 1, _ver("c1", Eligibility.ELIGIBLE), {"j1": ev("c1", "j1", 10), "j2": ev("c1", "j2", 0)}, Decimal("0"), Decimal("1"), CostQuality.ESTIMATED),
        CandidateInput("c2", "B", 1, _ver("c2", Eligibility.ELIGIBLE), {"j1": ev("c2", "j1", 5), "j2": ev("c2", "j2", 10)}, Decimal("0"), Decimal("1"), CostQuality.ESTIMATED),
    ])
    a = next(e for e in full.entries if e.candidate_id == "c1")
    # j1: tudo 10 -> 100; j2: notas 0 + eficiencia 10 (peso 10) -> 10. Media (3*100 + 1*10) / 4.
    assert [s.score_0_100 for s in a.judge_scores] == [Decimal(100), Decimal(10)]
    assert a.score_0_100 == Decimal(310) / Decimal(4) and a.grades == {}
    assert full.winner_candidate_id == "c1"

    # Juiz que falhou por inteiro sai do painel para todos, com motivo registrado.
    partial = compute_ranking(panel, [
        CandidateInput("c1", "A", 1, _ver("c1", Eligibility.ELIGIBLE), {"j1": ev("c1", "j1", 8)}, Decimal("0"), Decimal("1"), CostQuality.ESTIMATED),
        CandidateInput("c2", "B", 1, _ver("c2", Eligibility.ELIGIBLE), {"j1": ev("c2", "j1", 6)}, Decimal("0"), Decimal("1"), CostQuality.ESTIMATED),
    ])
    assert partial.winner_candidate_id == "c1" and any("painel incompleto" in r for r in partial.reasons)


def test_ranking_without_evaluation_is_not_evaluated() -> None:
    res = compute_ranking(RUBRIC, [CandidateInput("c1", "A", 1, _ver("c1", Eligibility.ELIGIBLE), None, Decimal("0"), Decimal("1"), CostQuality.ESTIMATED)])
    assert res.decision_status == DecisionStatus.NOT_EVALUATED and res.winner_candidate_id is None


# ------------------------------------------------------------------ verificadores objetivos


def test_constraint_fail_pass_unknown() -> None:
    pack = _pack()
    ids = [i.evidence_id for i in pack.items]
    c = Constraint(constraint_id="custo", description="d", kind="numeric_max", metric_key="monthly_cost_brl", limit=Decimal(8000), unit="BRL")
    ok = verify_proposal(_proposal({"monthly_cost_brl": ProposalMetric(value=Decimal(6500), unit="BRL", evidence_ids=[ids[0]])}, ids[:1]), [c], pack)
    assert ok.checks[0].result == CheckResult.PASS and ok.eligibility == Eligibility.ELIGIBLE
    bad = verify_proposal(_proposal({"monthly_cost_brl": ProposalMetric(value=Decimal(9800), unit="BRL", evidence_ids=[ids[2]])}, ids), [c], pack)
    assert bad.checks[0].result == CheckResult.FAIL and bad.eligibility == Eligibility.INELIGIBLE
    # alegacao sem evidencia que sustente o numero -> unknown -> pendente (nao aprovada por presuncao)
    claim = verify_proposal(_proposal({"monthly_cost_brl": ProposalMetric(value=Decimal(5000), unit="BRL", evidence_ids=[ids[0]])}, ids), [c], pack)
    assert claim.checks[0].result == CheckResult.UNKNOWN and claim.eligibility == Eligibility.PENDING
    missing = verify_proposal(_proposal({}, ids), [c], pack)
    assert missing.checks[0].result == CheckResult.UNKNOWN and missing.eligibility == Eligibility.PENDING
    invalid = verify_proposal(_proposal({}, ["ev-nao-existe"]), [], pack)
    assert invalid.invalid_evidence_ids == ["ev-nao-existe"]


def test_qualitative_mandatory_is_unknown() -> None:
    pack = _pack()
    c = Constraint(constraint_id="priv", description="d", kind="qualitative", mandatory=True)
    v = verify_proposal(_proposal({}, []), [c], pack)
    assert v.checks[0].result == CheckResult.UNKNOWN and v.eligibility == Eligibility.PENDING


# ------------------------------------------------------------------ calculo tipado


def test_calculation_typed_functions() -> None:
    known = {"e1", "e2"}
    spec = CalculationSpec(function="tco", unit="BRL", inputs=[CalcInput(name="setup", value=Decimal(40000), evidence_ids=["e1"]), CalcInput(name="monthly", value=Decimal(7200), evidence_ids=["e2"]), CalcInput(name="months", value=Decimal(12), evidence_ids=["e1"])])
    d = run_calculation(spec, known)
    assert d.result == Decimal(126400) and d.formula == "setup + monthly * months" and d.input_evidence_ids == ["e1", "e2"]
    with pytest.raises(CalculationError, match="desconhecida"):
        run_calculation(CalculationSpec(function="__import__", unit="x", inputs=[CalcInput(name="a", value=Decimal(1), evidence_ids=["e1"])]), known)
    with pytest.raises(CalculationError, match="inexistentes"):
        run_calculation(CalculationSpec(function="sum", unit="x", inputs=[CalcInput(name="a", value=Decimal(1), evidence_ids=["zzz"])]), known)
    with pytest.raises(CalculationError, match="sem evidencia"):
        run_calculation(CalculationSpec(function="sum", unit="x", inputs=[CalcInput(name="a", value=Decimal(1))]), known)
    with pytest.raises(CalculationError, match="zero"):
        run_calculation(CalculationSpec(function="divide", unit="x", inputs=[CalcInput(name="numerator", value=Decimal(1), evidence_ids=["e1"]), CalcInput(name="denominator", value=Decimal(0), evidence_ids=["e1"])]), known)


# ------------------------------------------------------------------ extracao e pacote


def test_extract_text_and_reject_binary() -> None:
    out = extract("# Titulo\n\nParagrafo com 1.234 valores.".encode(), filename="a.md", declared_type=None, max_pdf_pages=100)
    assert out.media_type == "text/markdown" and out.status == "ok" and out.pages is None
    with pytest.raises(ExtractionError):
        extract(b"\x00\x01\x02binario", filename="x.bin", declared_type="application/octet-stream", max_pdf_pages=100)
    with pytest.raises(ExtractionError):
        extract(b"nao e pdf", filename="x.pdf", declared_type="application/pdf", max_pdf_pages=100)


def test_pack_ids_are_stable_and_located() -> None:
    p1, p2 = _pack(), _pack()
    assert [i.evidence_id for i in p1.items] == [i.evidence_id for i in p2.items]
    assert p1.pack_hash == p2.pack_hash
    assert all(i.type == EvidenceType.SOURCE_CLAIM and i.locator.line_start for i in p1.items)


def test_pdf_extraction_with_text_layer() -> None:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    import io

    buf = io.BytesIO()
    w.write(buf)
    out = extract(buf.getvalue(), filename="vazio.pdf", declared_type="application/pdf", max_pdf_pages=100)
    assert out.pages == 1 and out.status == "needs_ocr" and any("OCR" in w for w in out.warnings)


# ------------------------------------------------------------------ contratos


def test_challenge_config_validation() -> None:
    with pytest.raises(ValidationError, match="modo real exige"):
        ChallengeConfig(objective="x" * 20, mode="real")
    with pytest.raises(ValidationError):
        ChallengeConfig(objective="x" * 20, candidate_count=5)
    with pytest.raises(ValidationError):
        ChallengeConfig(objective="x" * 20, candidate_count=1)
    with pytest.raises(ValidationError, match="numerica"):
        Constraint(constraint_id="c", description="d", kind="numeric_max")
    cfg = ChallengeConfig(objective="Escolher a melhor opcao", candidate_count=4)
    assert cfg.rubric.criteria[0].weight == Decimal(30)


# ------------------------------------------------------------------ revisao: regressao nao substitui a original


def _cost_constraint() -> Constraint:
    return Constraint(constraint_id="custo", description="d", kind="numeric_max", metric_key="monthly_cost_brl", limit=Decimal(8000), unit="BRL")


def _versioned(value: int | None, evidence_id: str | None, version: int) -> Proposal:
    metrics = {"monthly_cost_brl": ProposalMetric(value=Decimal(value), unit="BRL", evidence_ids=[evidence_id] if evidence_id else [])} if value is not None else {}
    return Proposal(title="t", recommendation="r", metrics=metrics, evidence_ids=[evidence_id] if evidence_id else [], candidate_id="c1", version=version)


def test_revision_with_verified_regression_keeps_original() -> None:
    from app.evaluation.verifiers import accept_revision, revision_regressions

    pack = _pack()
    ids = [i.evidence_id for i in pack.items]
    original = _versioned(6500, ids[0], 1)   # R$ 6.500 comprovado, dentro do teto
    revised = _versioned(9800, ids[2], 2)    # R$ 9.800 comprovado, acima do teto
    kept, reasons = accept_revision(original, revised, [_cost_constraint()], pack)
    assert kept is original and kept.version == 1
    assert reasons and "custo" in reasons[0]
    assert revision_regressions(verify_proposal(original, [_cost_constraint()], pack), verify_proposal(revised, [_cost_constraint()], pack))


def test_revision_fixing_invalid_original_is_accepted() -> None:
    from app.evaluation.verifiers import accept_revision

    pack = _pack()
    ids = [i.evidence_id for i in pack.items]
    original = _versioned(9800, ids[2], 1)   # inelegivel
    revised = _versioned(6500, ids[0], 2)    # elegivel
    kept, reasons = accept_revision(original, revised, [_cost_constraint()], pack)
    assert kept is revised and reasons == []


def test_revision_losing_proof_is_pending_not_rejected() -> None:
    """Ausencia de prova na revisao nao e tratada como erro comprovado: a revisao segue, mas fica pendente."""
    from app.evaluation.verifiers import accept_revision

    pack = _pack()
    ids = [i.evidence_id for i in pack.items]
    original = _versioned(6500, ids[0], 1)
    revised = _versioned(None, None, 2)
    kept, reasons = accept_revision(original, revised, [_cost_constraint()], pack)
    assert kept is revised and reasons == []
    assert verify_proposal(kept, [_cost_constraint()], pack).eligibility == Eligibility.PENDING


def test_no_validated_candidate_is_inconclusive_with_reasons() -> None:
    res = compute_ranking(RUBRIC, [
        CandidateInput("c1", "A", 1, _ver("c1", Eligibility.INELIGIBLE), _eval("c1", 10), Decimal("0.01"), Decimal("1"), CostQuality.ESTIMATED),
        CandidateInput("c2", "B", 1, _ver("c2", Eligibility.PENDING), _eval("c2", 9), Decimal("0.01"), Decimal("1"), CostQuality.ESTIMATED),
    ])
    assert res.decision_status == DecisionStatus.INCONCLUSIVE and res.winner_candidate_id is None
    assert any("pendentes" in r for r in res.reasons)
    # ranking provisorio continua existindo (pendente antes de inelegivel), sem vencedor oficial
    ranks = {e.candidate_id: e.rank for e in res.entries}
    assert ranks["c2"] == 1 and ranks["c1"] == 2
