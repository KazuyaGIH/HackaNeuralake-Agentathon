"""Verificacoes objetivas: restricoes tipadas e validade de referencias. Alegacao do candidato nao e prova."""

import re
from decimal import Decimal

from app.contracts.artifacts import ConstraintCheck, EvidencePack, Proposal, Verification
from app.contracts.challenge import Constraint
from app.contracts.common import CheckResult, ConstraintKind, Eligibility, EvidenceType

_NUM = re.compile(r"\d[\d.,]*")


def fmt_value(value: Decimal, unit: str | None) -> str:
    """Valor legivel para mensagens: 8000 BRL -> R$ 8.000; 90 dias -> 90 dias."""
    if value == value.to_integral_value():
        num = f"{int(value):,}".replace(",", ".")
    else:
        whole, frac = f"{value:.2f}".split(".")
        num = f"{int(whole):,}".replace(",", ".") + "," + frac
    u = (unit or "").strip()
    if u.upper() == "BRL":
        return f"R$ {num}"
    if u.upper() == "USD":
        return f"US$ {num}"
    return f"{num} {u}".strip()


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
                return True, f"comprovado pelo cálculo {eid}"
        elif item.type == EvidenceType.SOURCE_CLAIM:
            if value in _numbers_in(item.excerpt):
                return True, f"comprovado pelo trecho {eid}"
    return False, "nenhuma evidência citada comprova o valor declarado"


def check_constraint(constraint: Constraint, proposal: Proposal, pack: EvidencePack) -> ConstraintCheck:
    base = dict(constraint_id=constraint.constraint_id, mandatory=constraint.mandatory)
    if constraint.kind == ConstraintKind.QUALITATIVE:
        return ConstraintCheck(
            **base, unit=constraint.unit, result=CheckResult.UNKNOWN,
            reason="regra qualitativa: não há verificação automática, então fica sem prova",
        )
    metric = proposal.metrics.get(constraint.metric_key or "")
    if metric is None:
        return ConstraintCheck(
            **base, unit=constraint.unit, result=CheckResult.UNKNOWN,
            reason="a proposta não informa este valor",
        )
    if metric.unit.strip().lower() != (constraint.unit or "").strip().lower():
        return ConstraintCheck(
            **base, result=CheckResult.UNKNOWN, observed_value=metric.value, unit=metric.unit,
            evidence_ids=metric.evidence_ids,
            reason=f"unidade informada ({metric.unit}) diferente da exigida pela regra ({constraint.unit})",
        )
    supported, why = _metric_supported(metric.value, metric.evidence_ids, pack)
    if not supported:
        return ConstraintCheck(
            **base, result=CheckResult.UNKNOWN, observed_value=metric.value, unit=metric.unit,
            evidence_ids=metric.evidence_ids, reason=f"{fmt_value(metric.value, metric.unit)} informado, mas {why}",
        )
    limit = constraint.limit or Decimal("0")
    ok = metric.value <= limit if constraint.kind == ConstraintKind.NUMERIC_MAX else metric.value >= limit
    bound = "máximo" if constraint.kind == ConstraintKind.NUMERIC_MAX else "mínimo"
    verdict = "dentro do" if ok else ("acima do" if constraint.kind == ConstraintKind.NUMERIC_MAX else "abaixo do")
    return ConstraintCheck(
        **base, result=CheckResult.PASS if ok else CheckResult.FAIL, observed_value=metric.value, unit=metric.unit,
        evidence_ids=metric.evidence_ids,
        reason=f"{fmt_value(metric.value, metric.unit)}: {verdict} {bound} de {fmt_value(limit, constraint.unit)} ({why})",
    )


def verify_proposal(proposal: Proposal, constraints: list[Constraint], pack: EvidencePack) -> Verification:
    known = pack.ids()
    cited = set(proposal.evidence_ids)
    for m in proposal.metrics.values():
        cited.update(m.evidence_ids)
    valid = sorted(e for e in cited if e in known)
    invalid = sorted(e for e in cited if e not in known)
    checks = [check_constraint(c, proposal, pack) for c in constraints]
    desc = {c.constraint_id: c.description for c in constraints}
    reasons: list[str] = []
    mandatory = [c for c in checks if c.mandatory]
    if any(c.result == CheckResult.FAIL for c in mandatory):
        elig = Eligibility.INELIGIBLE
        reasons += [f"Quebra a regra “{desc[c.constraint_id]}”: {c.reason}" for c in mandatory if c.result == CheckResult.FAIL]
    elif any(c.result == CheckResult.UNKNOWN for c in mandatory):
        elig = Eligibility.PENDING
        reasons += [f"Sem prova para a regra “{desc[c.constraint_id]}”: {c.reason}" for c in mandatory if c.result == CheckResult.UNKNOWN]
    else:
        elig = Eligibility.ELIGIBLE
    if invalid:
        reasons.append(f"Cita evidências que não existem: {', '.join(invalid)}")
    return Verification(
        candidate_id=proposal.candidate_id, proposal_version=proposal.version, checks=checks,
        valid_evidence_ids=valid, invalid_evidence_ids=invalid, eligibility=elig, reasons=reasons,
    )
