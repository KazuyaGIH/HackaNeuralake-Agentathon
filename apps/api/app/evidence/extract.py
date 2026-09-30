"""Extracao de texto de fontes (TXT/Markdown/PDF com camada textual). Sem OCR no MVP."""

import io
from dataclasses import dataclass, field

EXTRACTOR_VERSION = "1"
MAX_CHARS_PER_SOURCE = 400_000
TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
PDF_TYPE = "application/pdf"


class ExtractionError(ValueError):
    pass


@dataclass
class Extracted:
    text: str
    pages: int | None
    media_type: str
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    status: str = "ok"
    page_offsets: list[int] = field(default_factory=list)  # indice de char onde comeca cada pagina (PDF)


def sniff_media_type(data: bytes, filename: str | None, declared: str | None) -> str:
    if data[:5] == b"%PDF-":
        return PDF_TYPE
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        raise ExtractionError("arquivo .pdf sem assinatura PDF valida")
    if name.endswith((".md", ".markdown")):
        return "text/markdown"
    if declared in TEXT_TYPES:
        return declared
    if b"\x00" in data[:4096]:
        raise ExtractionError("tipo de arquivo nao suportado (binario). Aceitos: TXT, Markdown e PDF textual.")
    return "text/plain"


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract(data: bytes, *, filename: str | None, declared_type: str | None, max_pdf_pages: int) -> Extracted:
    media_type = sniff_media_type(data, filename, declared_type)
    if media_type == PDF_TYPE:
        return _extract_pdf(data, max_pdf_pages)
    text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    out = Extracted(text=text, pages=None, media_type=media_type)
    _apply_char_limit(out)
    if not text.strip():
        out.status = "empty"
        out.warnings.append("fonte sem texto")
    return out


def _extract_pdf(data: bytes, max_pdf_pages: int) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("PDF criptografado nao e suportado")
        n_pages = len(reader.pages)
    except PdfReadError as exc:
        raise ExtractionError(f"PDF invalido: {exc}") from exc
    if n_pages > max_pdf_pages:
        raise ExtractionError(f"PDF com {n_pages} paginas excede o limite de {max_pdf_pages}")
    parts: list[str] = []
    offsets: list[int] = []
    total = 0
    warnings: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - pypdf pode falhar por pagina
            txt = ""
            warnings.append(f"pagina {i + 1}: falha na extracao ({type(exc).__name__})")
        txt = txt.replace("\r\n", "\n").strip()
        offsets.append(total)
        chunk = f"\n\n[[PAGINA {i + 1}]]\n{txt}"
        parts.append(chunk)
        total += len(chunk)
    text = "".join(parts).strip()
    out = Extracted(text=text, pages=n_pages, media_type=PDF_TYPE, warnings=warnings, page_offsets=offsets)
    alpha = sum(ch.isalnum() for ch in text)
    if n_pages and alpha < 40 * n_pages:
        out.status = "needs_ocr"
        out.warnings.append(
            "PDF com pouca ou nenhuma camada textual: provavelmente digitalizado e exige OCR, que esta fora do MVP."
        )
    _apply_char_limit(out)
    return out


def _apply_char_limit(out: Extracted) -> None:
    if len(out.text) > MAX_CHARS_PER_SOURCE:
        out.text = out.text[:MAX_CHARS_PER_SOURCE]
        out.truncated = True
        out.warnings.append(f"texto truncado em {MAX_CHARS_PER_SOURCE} caracteres; trechos posteriores foram omitidos")
