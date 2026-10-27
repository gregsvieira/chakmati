"""Word, Excel and PowerPoint files (the `documents` extra), which Pages, Numbers and Keynote open and save.

The model only fills in a small spec (a title and paragraphs, rows of cells, slides with bullets); this module checks it and
writes the file. A spreadsheet cell is a number, text, or a formula from a short allow-list (sums, averages, ... over cells of
the same sheet): a formula can never reach another file, run a program or call a URL."""

import re
from dataclasses import dataclass
from pathlib import Path

from chakmati.extras import missing_message
from chakmati.computer.safety import ComputerError

KINDS = {"docx": "Pages", "xlsx": "Numbers", "pptx": "Keynote"}
MAX_PARAGRAPHS, MAX_ROWS, MAX_COLS, MAX_SLIDES, MAX_BULLETS, MAX_TEXT = 60, 200, 26, 30, 8, 4000

_FUNCTIONS = {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "ROUND", "IF", "ABS", "PRODUCT", "MEDIAN"}
_FORMULA = re.compile(r"^=[A-Z0-9+\-*/(). :,;<>=\"%$]{1,200}$")
_CELL_REF = re.compile(r"^\$?[A-Z]{1,2}\$?[0-9]{1,4}$")


@dataclass(frozen=True)
class Spec:
    kind: str
    data: dict


def _text(value: object, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ComputerError("o conteúdo do documento veio em formato inválido")
    return value.replace("\x00", "").strip()[:limit]


def check_formula(formula: str) -> str:
    """The formula if it only uses the allowed functions over cells and numbers, or ComputerError."""
    f = formula.strip().upper()
    if not _FORMULA.match(f) or "!" in f or "[" in f:
        raise ComputerError(f"fórmula não permitida: {formula[:40]}")
    for name in re.findall(r"\$?[A-Z][A-Z0-9]*(?:\$[0-9]+)?", f):
        if name in _FUNCTIONS or _CELL_REF.match(name) or name in {"TRUE", "FALSE"}:
            continue
        raise ComputerError(f"função ou nome não permitido na fórmula: {name}")
    if f.count("(") != f.count(")"):
        raise ComputerError("fórmula com parênteses desbalanceados")
    return f


def check_spec(kind: str, raw: object) -> Spec:
    """A clean copy of what the model produced, limited in size, or ComputerError."""
    if kind not in KINDS or not isinstance(raw, dict):
        raise ComputerError("tipo de documento inválido")
    if kind == "docx":
        paras = raw.get("paragraphs")
        if not isinstance(paras, list) or not paras:
            raise ComputerError("o documento ficou sem texto")
        return Spec(kind, {"title": _text(raw.get("title", ""), 200), "paragraphs": [_text(p) for p in paras[:MAX_PARAGRAPHS] if isinstance(p, str) and p.strip()],
                           "sources": [_text(u, 300) for u in (raw.get("sources") or [])[:5] if isinstance(u, str)]})
    if kind == "xlsx":
        sheets = raw.get("sheets")
        if not isinstance(sheets, list) or not sheets:
            raise ComputerError("a planilha ficou sem dados")
        out = []
        for sheet in sheets[:5]:
            rows = sheet.get("rows") if isinstance(sheet, dict) else None
            if not isinstance(rows, list) or not rows:
                continue
            clean = []
            for row in rows[:MAX_ROWS]:
                if not isinstance(row, list):
                    continue
                cells: list = []
                for cell in row[:MAX_COLS]:
                    if isinstance(cell, bool) or cell is None:
                        cells.append("" if cell is None else str(cell))
                    elif isinstance(cell, (int, float)):
                        cells.append(cell)
                    elif isinstance(cell, str) and cell.startswith("="):
                        cells.append(check_formula(cell))
                    else:
                        cells.append(_text(str(cell), 700))
                clean.append(cells)
            out.append({"name": re.sub(r"[\[\]:*?/\\]", "", _text(sheet.get("name", "Planilha"), 31)) or "Planilha", "rows": clean})
        if not out:
            raise ComputerError("a planilha ficou sem dados")
        return Spec(kind, {"sheets": out})
    slides = raw.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ComputerError("a apresentação ficou sem slides")
    clean_slides = []
    for slide in slides[:MAX_SLIDES]:
        if not isinstance(slide, dict):
            continue
        bullets = [_text(b, 300) for b in (slide.get("bullets") or [])[:MAX_BULLETS] if isinstance(b, str) and b.strip()]
        clean_slides.append({"title": _text(slide.get("title", ""), 120), "bullets": bullets})
    if not clean_slides:
        raise ComputerError("a apresentação ficou sem slides")
    return Spec(kind, {"title": _text(raw.get("title", ""), 200), "slides": clean_slides})


def preview(spec: Spec) -> str:
    d = spec.data
    if spec.kind == "docx":
        return f"{d['title']}\n" + "\n".join(p[:140] + ("…" if len(p) > 140 else "") for p in d["paragraphs"][:3])
    if spec.kind == "xlsx":
        sheet = d["sheets"][0]
        lines = [" | ".join(str(c) for c in row) for row in sheet["rows"][:6]]
        return f"Planilha “{sheet['name']}” ({len(sheet['rows'])} linhas)\n" + "\n".join(lines)
    return f"{d['title']} — {len(d['slides'])} slides\n" + "\n".join(f"{i}. {s['title']}" for i, s in enumerate(d["slides"][:8], 1))


def _import(kind: str):
    try:
        if kind == "docx":
            import docx
            return docx
        if kind == "xlsx":
            import openpyxl
            return openpyxl
        import pptx
        return pptx
    except ImportError as exc:
        raise ComputerError(missing_message("documents", "Creating Word, Excel and PowerPoint files")) from exc


def write(spec: Spec, target: Path) -> None:
    """Writes the file at `target` (which must not exist yet). The caller has already checked the path."""
    lib = _import(spec.kind)
    d = spec.data
    tmp = target.with_name(f".{target.name}.chakmati-tmp")
    if spec.kind == "docx":
        doc = lib.Document()
        if d["title"]:
            doc.add_heading(d["title"], level=0)
        for p in d["paragraphs"]:
            doc.add_paragraph(p)
        if d["sources"]:
            doc.add_paragraph("Fonte: " + ", ".join(d["sources"]))
        doc.save(tmp)
    elif spec.kind == "xlsx":
        wb = lib.Workbook()
        wb.remove(wb.active)
        for sheet in d["sheets"]:
            ws = wb.create_sheet(sheet["name"])
            for row in sheet["rows"]:
                ws.append(row)
            for cell in ws[1]:
                cell.font = lib.styles.Font(bold=True)
            for column in ws.columns:
                ws.column_dimensions[column[0].column_letter].width = min(40, max(10, *(len(str(c.value or "")) + 2 for c in column)))
        wb.save(tmp)
    else:
        prs = lib.Presentation()
        title_layout, bullet_layout = prs.slide_layouts[0], prs.slide_layouts[1]
        cover = prs.slides.add_slide(title_layout)
        cover.shapes.title.text = d["title"] or d["slides"][0]["title"]
        for placeholder in list(cover.placeholders):
            if placeholder.placeholder_format.idx == 1:  # the empty subtitle would show as "click to add" in Keynote
                placeholder._element.getparent().remove(placeholder._element)
        for s in d["slides"]:
            slide = prs.slides.add_slide(bullet_layout)
            slide.shapes.title.text = s["title"]
            frame = slide.placeholders[1].text_frame
            for i, bullet in enumerate(s["bullets"]):
                (frame.paragraphs[0] if i == 0 else frame.add_paragraph()).text = bullet
        prs.save(tmp)
    tmp.replace(target)


_WANTS_TOTAL = re.compile(r"\b(?:soma\w*|total|totais)\b", re.IGNORECASE)
_WANTS_AVERAGE = re.compile(r"\b(?:m[ée]dia\w*)\b", re.IGNORECASE)


def _col(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    out = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def add_formulas(spec: Spec, request: str) -> Spec:
    """When the request asks for totals or averages and the model left them out, they are written here: the formulas are the part a model gets wrong
    (the wrong range, the wrong row) and code gets right. Rows are the records, numbers are the columns it adds up. Nothing is touched when the sheet already has formulas."""
    wants_total, wants_average = bool(_WANTS_TOTAL.search(request)), bool(_WANTS_AVERAGE.search(request))
    if spec.kind != "xlsx" or not (wants_total or wants_average):
        return spec
    sheets = []
    for sheet in spec.data["sheets"]:
        rows = [list(r) for r in sheet["rows"]]
        has_formula = any(isinstance(c, str) and c.startswith("=") for r in rows for c in r)
        numeric = [j for j in range(1, max((len(r) for r in rows), default=0)) if sum(isinstance(r[j], (int, float)) for r in rows[1:] if j < len(r)) >= max(1, len(rows[1:]) // 2)]
        if has_formula or len(rows) < 2 or not numeric:
            sheets.append(sheet)
            continue
        first, last = _col(numeric[0]), _col(numeric[-1])
        header, body = rows[0], rows[1:]
        width = len(header)
        add = [(["Total"], "SUM"), (["Média"], "AVERAGE")]
        columns = [(name[0], fn) for name, fn in add if (fn == "SUM" and wants_total) or (fn == "AVERAGE" and wants_average)]
        for name, _ in columns:
            header.append(name)
        for i, r in enumerate(body, start=2):
            r.extend([""] * (width - len(r)))
            for _, fn in columns:
                r.append(f"={fn}({first}{i}:{last}{i})")
        if wants_total:  # a totals row under the records, one sum per number column
            n = len(body) + 1
            totals = ["Total"] + [""] * (len(header) - 1)
            for j in [*numeric, width]:  # (the new Total column too)
                totals[j] = f"=SUM({_col(j)}2:{_col(j)}{n})"
        sheets.append({"name": sheet["name"], "rows": [header, *body, *( [totals] if wants_total else [])]})
    return check_spec("xlsx", {"sheets": sheets})
