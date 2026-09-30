"""Verificacoes objetivas: restricoes tipadas e validade de referencias. Alegacao do candidato nao e prova."""

import re
from decimal import Decimal

from app.contracts.artifacts import ConstraintCheck, EvidencePack, Proposal, Verification
from app.contracts.challenge import Constraint
from app.contracts.common import CheckResult, ConstraintKind, Eligibility, EvidenceType

_NUM = re.compile(r"\d[\d.,]*")


def _numbers_in(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for m in _NUM.findall(text):
        raw = m.rstrip(".,")
        candidates = {raw.replace(".", "").replace(",", "."), raw.replace(",", "")}
        for c in candidates:
            try:
                out.add(Decimal(c))
            except Exception:  # noqa: BLE001
                continue
    return out


def _metric_supported(value: Decimal, evidence_ids: list[str], pack: EvidencePack) -> tuple[bool, str]:
    """Metrica esta sustentada se alguma evidencia citada e uma derivacao com o mesmo resultado
    ou um trecho de fonte que contem o numero declarado."""
    by_id = {i.evidence_id: i for i in pack.items}
    for eid in evidence_ids:
        item = by_id.get(eid)
        if item is None:
            continue
        if item.type == EvidenceType.DERIVED_CALCULATION and item.derivation is not None:
            if item.derivation.result == value:
                return True, f"derivacao {eid} ({item.derivation.formula}) = {value}"
        elif item.type == EvidenceType.SOURCE_CLAIM:
            if value in _numbers_in(item.excerpt):
                return True, f"trecho {eid} contem o valor {value}"
    return False, "nenhuma evidencia citada sustenta o valor declarado"


def check_constraint(constraint: Constraint, proposal: Proposal, pack: EvidencePack) -> ConstraintCheck:
    base = dict(constraint_id=constraint.constraint_id, mandatory=constraint.mandatory)
    if constraint.kind == ConstraintKind.QUALITATIVE:
        return ConstraintCheck(
            **base, unit=constraint.unit, result=CheckResult.UNKNOWN,
            reason="restricao sem verificador objetivo: avaliacao semantica nao satisfaz restricao obrigatoria verificavel",
        )
    metric = proposal.metrics.get(constraint.metric_key or "")
    if metric is None:
        return ConstraintCheck(
            **base, unit=constraint.unit, result=CheckResult.UNKNOWN,
            reason=f"proposta nao declara a metrica '{constraint.metric_key}'",
        )
    if metric.unit.strip().lower() != (constraint.unit or "").strip().lower():
        return ConstraintCheck(
            **base, result=CheckResult.UNKNOWN, observed_value=metric.value, unit=metric.unit,
            evidence_ids=metric.evidence_ids,
            reason=f"unidade declarada '{metric.unit}' difere da unidade da restricao '{constraint.unit}'",
        )
    supported, why = _metric_supported(metric.value, metric.evidence_ids, pack)
    if not supported:
        return ConstraintCheck(
            **base, result=CheckResult.UNKNOWN, observed_value=metric.value, unit=metric.unit,
            evidence_ids=metric.evidence_ids, reason=f"valor nao verificavel: {why}",
        )
    limit = constraint.limit or Decimal("0")
    ok = metric.value <= limit if constraint.kind == ConstraintKind.NUMERIC_MAX else metric.value >= limit
    op = "<=" if constraint.kind == ConstraintKind.NUMERIC_MAX else ">="
    return ConstraintCheck(
        **base, result=CheckResult.PASS if ok else CheckResult.FAIL, observed_value=metric.value, unit=metric.unit,
        evidence_ids=metric.evidence_ids,
        reason=f"{metric.value} {op} {limit} {constraint.unit}: {'ok' if ok else 'violado'} ({why})",
    )


def verify_proposal(proposal: Proposal, constraints: list[Constraint], pack: EvidencePack) -> Verification:
    known = pack.ids()
    cited = set(proposal.evidence_ids)
    for m in proposal.metrics.values():
        cited.update(m.evidence_ids)
    valid = sorted(e for e in cited if e in known)
    invalid = sorted(e for e in cited if e not in known)
    checks = [check_constraint(c, proposal, pack) for c in constraints]
    reasons: list[str] = []
    mandatory = [c for c in checks if c.mandatory]
    if any(c.result == CheckResult.FAIL for c in mandatory):
        elig = Eligibility.INELIGIBLE
        reasons += [f"restricao obrigatoria '{c.constraint_id}' violada: {c.reason}" for c in mandatory if c.result == CheckResult.FAIL]
    elif any(c.result == CheckResult.UNKNOWN for c in mandatory):
        elig = Eligibility.PENDING
        reasons += [f"restricao obrigatoria '{c.constraint_id}' sem prova: {c.reason}" for c in mandatory if c.result == CheckResult.UNKNOWN]
    else:
        elig = Eligibility.ELIGIBLE
    if invalid:
        reasons.append(f"referencias inexistentes citadas: {', '.join(invalid)}")
    return Verification(
        candidate_id=proposal.candidate_id, proposal_version=proposal.version, checks=checks,
        valid_evidence_ids=valid, invalid_evidence_ids=invalid, eligibility=elig, reasons=reasons,
    )
