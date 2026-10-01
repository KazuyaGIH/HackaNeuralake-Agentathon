"""Preparacao da entrada do Judge (anonimizacao + embaralhamento com seed) e validacao da saida."""

import random
import re
from typing import Any

from app.contracts.artifacts import Evaluation, JudgeOutput, Proposal, Verification
from app.contracts.challenge import Rubric


class JudgeOutputError(ValueError):
    pass


def judge_criteria(rubric: Rubric) -> list[dict[str, Any]]:
    return [
        {"criterion_id": c.criterion_id, "name": c.name, "description": c.description}
        for c in rubric.criteria
        if c.computed_by == "judge"
    ]


def _scrub(obj: Any, names: list[str]) -> Any:
    """Remove nomes de equipes do texto (defesa adicional; nao garante anonimato se o modelo se identificar de outra forma)."""
    if isinstance(obj, str):
        out = obj
        for n in names:
            if n:
                out = re.sub(re.escape(n), "[equipe]", out, flags=re.IGNORECASE)
        return out
    if isinstance(obj, list):
        return [_scrub(v, names) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub(v, names) for k, v in obj.items()}
    return obj


def anonymize(proposals: list[Proposal], verifications: dict[str, Verification], seed: int, names: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Retorna (propostas anonimas embaralhadas, verificacoes anonimas, mapa label->candidate_id)."""
    order = sorted(proposals, key=lambda p: p.candidate_id)
    rng = random.Random(seed)
    rng.shuffle(order)
    label_map: dict[str, str] = {}
    anon: list[dict[str, Any]] = []
    anon_ver: list[dict[str, Any]] = []
    scrub_names = sorted((names or {}).values(), key=len, reverse=True)
    for i, p in enumerate(order, start=1):
        label = f"P{i}"
        label_map[label] = p.candidate_id
        data = p.model_dump(mode="json", exclude={"candidate_id", "call_ids", "invalid_evidence_ids", "revised_from_critique", "version"})
        anon.append({"label": label, **_scrub(data, scrub_names)})
        v = verifications.get(p.candidate_id)
        if v is not None:
            anon_ver.append(
                {"label": label, "eligibility": str(v.eligibility), "checks": [c.model_dump(mode="json") for c in v.checks],
                 "invalid_evidence_ids": v.invalid_evidence_ids}
            )
    return anon, anon_ver, label_map


def parse_judge_output(raw: dict[str, Any], rubric: Rubric, label_map: dict[str, str], proposals: dict[str, Proposal], rubric_hash: str, pack_version: int, call_ids: list[str]) -> list[Evaluation]:
    out = JudgeOutput.model_validate(raw)
    expected = {c["criterion_id"] for c in judge_criteria(rubric)}
    seen_labels: set[str] = set()
    evaluations: list[Evaluation] = []
    for ev in out.evaluations:
        if ev.label not in label_map:
            raise JudgeOutputError(f"label desconhecido na saida do Judge: {ev.label}")
        if ev.label in seen_labels:
            raise JudgeOutputError(f"label duplicado na saida do Judge: {ev.label}")
        seen_labels.add(ev.label)
        ids = [g.criterion_id for g in ev.grades]
        if len(ids) != len(set(ids)):
            raise JudgeOutputError(f"criterio duplicado em {ev.label}")
        missing = expected - set(ids)
        extra = set(ids) - expected
        if missing or extra:
            raise JudgeOutputError(
                f"{ev.label}: criterios ausentes {sorted(missing)} / desconhecidos {sorted(extra)}"
            )
        cid = label_map[ev.label]
        evaluations.append(
            Evaluation(
                candidate_id=cid, proposal_version=proposals[cid].version, judge_label=ev.label, rubric_hash=rubric_hash,
                pack_version=pack_version, grades=ev.grades, objections=ev.objections, assumptions=ev.assumptions,
                uncertainties=ev.uncertainties, status="complete", call_ids=call_ids,
            )
        )
    missing_labels = set(label_map) - seen_labels
    if missing_labels:
        raise JudgeOutputError(f"Judge nao avaliou as propostas {sorted(missing_labels)}")
    return evaluations
