"""Recuperacao deterministica de trechos do pacote por sobreposicao lexical (sem rede, sem embeddings)."""

import math
import re
import unicodedata
from collections import Counter

from app.contracts.artifacts import EvidenceItem

_TOKEN = re.compile(r"[a-z0-9]{2,}")
_STOP = {
    "de", "da", "do", "das", "dos", "e", "ou", "a", "o", "as", "os", "um", "uma", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "que", "se", "ao", "aos", "the", "of", "and", "to", "in", "for", "is", "are",
    "qual", "quais", "como", "sobre", "entre", "mais", "menos", "ser", "ter", "seu", "sua", "seus", "suas",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(normalize(text)) if t not in _STOP]


def retrieve(query: str, items: list[EvidenceItem], k: int = 6) -> list[EvidenceItem]:
    q = tokens(query)
    if not q or not items:
        return items[:k]
    n = len(items)
    docs = [Counter(tokens(i.excerpt)) for i in items]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    scored: list[tuple[float, int]] = []
    for idx, d in enumerate(docs):
        length = sum(d.values()) or 1
        score = 0.0
        for term in q:
            tf = d.get(term, 0)
            if tf:
                idf = math.log((n + 1) / (df[term] + 0.5))
                score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / 120))
        if score > 0:
            scored.append((score, idx))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [items[i] for _, i in scored[:k]]
