"""The text inside a file the person attached: plain text files, PDF, Word, Excel and PowerPoint.

Light on purpose (the computers this runs on are modest): nothing is converted or kept except the extracted text, a file is read once when it is
attached, and a huge one is cut at MAX_CHARS. A scan without text is not read here (there is no OCR for it): the person is told."""

import io
import os
from pathlib import PurePath

MAX_UPLOAD = 20 * 1024 * 1024
MAX_CHARS = 1_500_000
MAX_SHEET_ROWS = 2000

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm", ".yaml", ".yml", ".ini", ".srt", ".py", ".js", ".ts", ".sql"}
OFFICE_SUFFIXES = {".pdf", ".docx", ".xlsx", ".pptx"}
SUPPORTED = TEXT_SUFFIXES | OFFICE_SUFFIXES


class UnreadableFile(Exception):
    """The file cannot be read; the message says why, in words the person can use."""


def clean_name(name: str) -> str:
    base = PurePath(str(name).replace("\\", "/")).name.strip()
    base = "".join(c for c in base if c.isprintable() and c not in '<>"|?*\x00')
    return base[:120] or "arquivo"


def supported(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in SUPPORTED


def _plain(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise UnreadableFile("Para ler PDF falta o pacote pypdf (uv sync --extra documents).") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[página {number}]\n{text}")
                total += len(text)
            if total > MAX_CHARS:
                break
    except Exception as e:
        raise UnreadableFile("Não consegui abrir esse PDF (pode estar protegido ou corrompido).") from e
    if not pages:
        raise UnreadableFile("Esse PDF parece ser uma imagem escaneada, sem texto para ler.")
    return "\n\n".join(pages)


def _docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as e:
        raise UnreadableFile("Para ler Word falta o pacote python-docx (uv sync --extra documents).") from e
    try:
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    except Exception as e:
        raise UnreadableFile("Não consegui abrir esse documento do Word.") from e
    return "\n".join(parts)


def _xlsx(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError as e:
        raise UnreadableFile("Para ler Excel falta o pacote openpyxl (uv sync --extra documents).") from e
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for sheet in book.worksheets:
            parts.append(f"[planilha {sheet.title}]")
            for count, row in enumerate(sheet.iter_rows(values_only=True)):
                if count >= MAX_SHEET_ROWS:
                    parts.append("[…linhas seguintes não lidas]")
                    break
                cells = ["" if c is None else str(c) for c in row]
                if any(cells):
                    parts.append(" | ".join(cells))
    except Exception as e:
        raise UnreadableFile("Não consegui abrir essa planilha.") from e
    return "\n".join(parts)


def _pptx(data: bytes) -> str:
    try:
        from pptx import Presentation
    except ImportError as e:
        raise UnreadableFile("Para ler PowerPoint falta o pacote python-pptx (uv sync --extra documents).") from e
    try:
        parts = []
        for number, slide in enumerate(Presentation(io.BytesIO(data)).slides, start=1):
            texts = [s.text_frame.text for s in slide.shapes if getattr(s, "has_text_frame", False) and s.text_frame.text.strip()]
            if texts:
                parts.append(f"[slide {number}]\n" + "\n".join(texts))
    except Exception as e:
        raise UnreadableFile("Não consegui abrir essa apresentação.") from e
    return "\n\n".join(parts)


def read_text(name: str, data: bytes) -> str:
    """The text of the file, cut at MAX_CHARS. Raises UnreadableFile with a sentence for the person."""
    suffix = os.path.splitext(name)[1].lower()
    if suffix not in SUPPORTED:
        raise UnreadableFile("Esse tipo de arquivo ainda não é lido. Use texto, PDF, Word, Excel ou PowerPoint.")
    if len(data) > MAX_UPLOAD:
        raise UnreadableFile("O arquivo é grande demais (o limite é 20 MB).")
    reader = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}.get(suffix)
    text = reader(data) if reader else _plain(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    if not text:
        raise UnreadableFile("O arquivo está vazio ou não tem texto.")
    return text[:MAX_CHARS]
