"""Construcao do pacote comum de evidencias (EvidencePack) com IDs estaveis e localizadores."""

import hashlib
import json
import re
from dataclasses import dataclass

from app.contracts.artifacts import EvidenceItem, EvidenceLocator, EvidencePack, SourceSummary
from app.contracts.common import EvidenceType
from app.evidence.extract import EXTRACTOR_VERSION

MAX_CHUNK_CHARS = 700
MIN_CHUNK_CHARS = 80
MAX_ITEMS_PER_SOURCE = 400
PAGE_MARK = re.compile(r"\[\[PAGINA (\d+)\]\]")


@dataclass
class SourceText:
    source_id: str
    title: str
    media_type: str
    text: str
    sha256: str
    pages: int | None
    truncated: bool
    warnings: list[str]


def _chunks(text: str) -> list[tuple[str, int, int, int | None]]:
    """Divide em paragrafos ate MAX_CHUNK_CHARS. Retorna (trecho, linha_inicial, linha_final, pagina)."""
    lines = text.split("\n")
    out: list[tuple[str, int, int, int | None]] = []
    buf: list[str] = []
    start = 1
    page: int | None = None
    buf_page: int | None = None

    def flush(end_line: int) -> None:
        nonlocal buf, start
        joined = "\n".join(buf).strip()
        if joined:
            if out and len(out[-1][0]) < MIN_CHUNK_CHARS and out[-1][3] == buf_page:
                prev = out[-1]
                out[-1] = (prev[0] + "\n" + joined, prev[1], end_line, prev[3])
            else:
                out.append((joined, start, end_line, buf_page))
        buf = []

    for i, line in enumerate(lines, start=1):
        m = PAGE_MARK.fullmatch(line.strip())
        if m:
            flush(i - 1)
            page = int(m.group(1))
            start = i + 1
            continue
        if not line.strip():
            flush(i - 1)
            start = i + 1
            continue
        if not buf:
            start = i
            buf_page = page
        buf.append(line)
        if sum(len(b) for b in buf) >= MAX_CHUNK_CHARS:
            flush(i)
            start = i + 1
    flush(len(lines))
    return out


def build_pack(sources: list[SourceText]) -> EvidencePack:
    items: list[EvidenceItem] = []
    summaries: list[SourceSummary] = []
    gaps: list[str] = []
    for src in sources:
        chunks = _chunks(src.text)
        if len(chunks) > MAX_ITEMS_PER_SOURCE:
            gaps.append(
                f"fonte '{src.title}' gerou {len(chunks)} trechos; apenas os {MAX_ITEMS_PER_SOURCE} primeiros foram indexados"
            )
            chunks = chunks[:MAX_ITEMS_PER_SOURCE]
        prefix = src.sha256[:6]
        for idx, (excerpt, l0, l1, page) in enumerate(chunks, start=1):
            items.append(
                EvidenceItem(
                    evidence_id=f"ev-{prefix}-{idx:03d}",
                    source_id=src.source_id,
                    type=EvidenceType.SOURCE_CLAIM,
                    excerpt=excerpt[:4000],
                    locator=EvidenceLocator(page=page, line_start=l0, line_end=l1),
                    provenance=f"extractor:v{EXTRACTOR_VERSION}:{src.source_id}",
                )
            )
        summaries.append(
            SourceSummary(
                source_id=src.source_id, title=src.title, media_type=src.media_type, pages=src.pages,
                chars=len(src.text), sha256=src.sha256, truncated=src.truncated, warnings=list(src.warnings),
            )
        )
        if src.truncated:
            gaps.append(f"fonte '{src.title}' foi truncada; trechos finais nao estao no pacote")
        if not chunks:
            gaps.append(f"fonte '{src.title}' nao produziu trechos utilizaveis")
    if not sources:
        gaps.append("nenhuma fonte anexada: as propostas dependerao de hipoteses explicitas")
    pack = EvidencePack(
        version=1, frozen=False, sources=summaries, items=items, gaps=gaps, extractor_version=EXTRACTOR_VERSION
    )
    pack.pack_hash = pack_hash(pack)
    return pack


def pack_hash(pack: EvidencePack) -> str:
    payload = pack.model_dump(mode="json", exclude={"pack_hash"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def freeze_with_derivations(pack: EvidencePack, derived: list[EvidenceItem], extra_gaps: list[str]) -> EvidencePack:
    """Barreira unica de atualizacao: incorpora derivacoes compartilhaveis validadas e congela a versao final."""
    known = pack.ids()
    merged = list(pack.items)
    for item in derived:
        if item.evidence_id in known:
            continue
        merged.append(item)
        known.add(item.evidence_id)
    final = EvidencePack(
        version=pack.version + 1, frozen=True, sources=pack.sources, items=merged,
        assumptions=list(pack.assumptions), gaps=list(pack.gaps) + extra_gaps, extractor_version=pack.extractor_version,
    )
    final.pack_hash = pack_hash(final)
    return final
