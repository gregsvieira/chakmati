"""Reading exams that are scans or phone photos (PDF with no text, or JPG/PNG), with an "X" written by hand in a box before each option.

Two jobs, both done in code (the model never sees the page):
  1. an OCR engine finds the lines of text and where they are: the student's name ("Aluno: ..."), the question numbers and the option lines
     ("[ ] B) 1 : 18."). On a Mac it is Apple's Vision (already part of macOS, nothing to download); elsewhere RapidOCR (the `ocr` extra).
  2. the mark is NOT read as text (handwriting is the least reliable thing to OCR): the little box in front of each option is measured, and an
     option counts as marked when its box has clearly more ink than the other boxes of the same exam (the printed brackets are the baseline).
A box that is only a bit darker than the others is not decided: it is flagged "marca duvidosa" for the teacher."""

import re
import statistics
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from chakmati.extras import missing_message
from chakmati.computer.grading import Exam, MAX_BYTES, Question
from chakmati.computer.safety import ComputerError

IMAGE_EXT = {".jpg", ".jpeg", ".png"}
MAX_PAGES = 3
_QUESTION = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*\S")
_OPTION = re.compile(r"^[^a-z]{0,6}?([A-E])\s*\)")  # "[ ] B)", and what the OCR makes of a handwritten box: "[XE)", "[IA)", "[X7A)", "LID)"
_NAME = re.compile(r"Aluno\(?a?\)?\s*:?\s*(.+)$", re.IGNORECASE)
MARK, DOUBT = 0.17, 0.12  # ink inside a box: an X is about 0.25, an empty box is under 0.1 (measured on scans and phone photos)


@dataclass(frozen=True)
class OcrLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float  # pixels, origin at the top left
    confidence: float
    letter_x: object = None  # callable(index of a character in text) -> pixel x of its left edge, when the engine can tell


def _pages(path: Path):
    """The pages of a PDF (rendered) or the image itself, as grey PIL images."""
    from PIL import Image
    if path.suffix.lower() in IMAGE_EXT:
        yield Image.open(path).convert("L")
        return
    try:
        import pypdfium2
    except ImportError as exc:
        raise ComputerError(missing_message("ocr", "Reading scanned exams")) from exc
    pdf = pypdfium2.PdfDocument(str(path))
    for i in range(min(len(pdf), MAX_PAGES)):
        yield pdf[i].render(scale=2.2).to_pil().convert("L")


def _vision_lines(image) -> list[OcrLine]:
    import Vision
    from Foundation import NSURL
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "page.png"
        image.save(png)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(png)), None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["pt-BR", "en-US"])
        ok, _ = handler.performRequests_error_([request], None)
        if not ok:
            raise ComputerError("não consegui ler a imagem da prova")
        width, height = image.size
        lines = []
        for obs in request.results() or []:
            candidate = obs.topCandidates_(1)[0]
            box = obs.boundingBox()  # normalised, origin at the bottom left

            def letter_x(index, candidate=candidate, width=width):
                found, _ = candidate.boundingBoxForRange_error_((index, 1), None)
                return found.boundingBox().origin.x * width if found is not None else None

            lines.append(OcrLine(str(candidate.string()), box.origin.x * width, (1 - box.origin.y - box.size.height) * height,
                                 (box.origin.x + box.size.width) * width, (1 - box.origin.y) * height, float(candidate.confidence()), letter_x))
        return lines


_rapid = None


def _rapid_lines(image) -> list[OcrLine]:
    global _rapid
    try:
        import numpy
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ComputerError(missing_message("ocr", "Reading scanned exams")) from exc
    _rapid = _rapid or RapidOCR()
    result, _ = _rapid(numpy.array(image.convert("RGB")))
    lines = []
    for points, text, score in result or []:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        x0, x1 = min(xs), max(xs)
        lines.append(OcrLine(text, x0, min(ys), x1, max(ys), float(score), lambda i, x0=x0, x1=x1, n=max(len(text), 1): x0 + (x1 - x0) * i / n))
    return sorted(lines, key=lambda line: line.y0)


def ocr_lines(image) -> list[OcrLine]:
    return _vision_lines(image) if sys.platform == "darwin" else _rapid_lines(image)


def _ink(image, x0: float, y0: float, x1: float, y1: float) -> float:
    """Share of dark pixels in a rectangle, judged against the page's own paper (so a dim photo is not "all ink")."""
    w, h = image.size
    box = image.crop((max(int(x0), 0), max(int(y0), 0), min(int(x1), w), min(int(y1), h)))
    if box.width < 3 or box.height < 3:
        return 0.0
    paper = statistics.median(image.resize((64, 64)).getdata())
    limit = paper * 0.6
    pixels = list(box.getdata())
    return sum(1 for p in pixels if p < limit) / len(pixels)


def read_scan(path: Path) -> Exam:
    if path.stat().st_size > MAX_BYTES:
        raise ComputerError("arquivo grande demais")
    marks: dict[int, str] = {}
    name, name_confidence = "", 0.0
    boxes: list[tuple[int, str, float]] = []  # (question, letter, ink)
    notes: list[str] = []
    question = None
    questions: dict[int, Question] = {}
    pending: list = []  # option lines, measured once their typical height is known
    for image in _pages(path):
        for line in sorted(ocr_lines(image), key=lambda l: l.y0):
            text = unicodedata.normalize("NFKC", line.text)
            if (m := _NAME.search(text)) and not name:
                name, name_confidence = m.group(1).strip(" _.:"), line.confidence
                continue
            option = _OPTION.match(text)
            if option and question is not None:
                questions[question].options[option.group(1)] = text[option.end():].strip()
                pending.append((question, option.group(1), image, line))
            elif q := _QUESTION.match(text):
                question = int(q.group(1))
                marks.setdefault(question, "")
                questions[question] = Question(re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", text).strip())
            elif question is not None and not questions[question].options:
                questions[question].stem += " " + text.strip()
    if pending:
        # a line's own box is jittery (a bracket taller than the letters, a tilted page): the same size and the middle of the line are used instead
        h = statistics.median(line.y1 - line.y0 for _, _, _, line in pending)
        for q, letter, image, line in pending:
            cy = (line.y0 + line.y1) / 2
            boxes.append((q, letter, _ink(image, line.x0 + 0.3 * h, cy - 0.28 * h, line.x0 + 0.9 * h, cy + 0.28 * h)))
    if not boxes:
        raise ComputerError("não achei questões nesta imagem")
    base = statistics.median(ink for _, _, ink in boxes)  # the paper and printed brackets of this very page: a dim photo has a higher floor
    for q, letter, ink in boxes:
        if ink >= max(MARK, base + 0.12):
            marks[q] = marks.get(q, "") + letter
    for q, letter, ink in boxes:
        if not marks.get(q) and ink >= max(DOUBT, base + 0.06):  # nothing clear in this question, but one box has some ink
            notes.append(f"Q{q}: marca duvidosa na alternativa {letter}, confira")
    student = name if name and name_confidence >= 0.5 else ""
    if not student:
        student = path.stem
        notes.append("nome não lido, usei o nome do arquivo")
    return Exam(path.name, student[:80], {q: "".join(sorted(set(m))) for q, m in marks.items()}, tuple(notes), questions)
