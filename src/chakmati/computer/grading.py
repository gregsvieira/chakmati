"""Grading multiple-choice exams that are PDFs with an "X" in the chosen box, against an answer key.

Done in code, never by the model: the text of each PDF is parsed for the lines "[X] B) ..." and the student's name for "Aluno: ...";
the marks are compared with the key the PERSON gave in the request. A question with no X, or with more than one, counts as wrong and
is flagged for the teacher to look at. The PDFs' text is other people's text: it only goes through these regular expressions."""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from chakmati.extras import missing_message
from chakmati.computer.safety import ComputerError

MAX_FILES, MAX_BYTES, MAX_QUESTIONS = 100, 8_000_000, 100
_QUESTION = re.compile(r"^\s*(\d{1,3})\s*[.)]\s+\S")
_OPTION = re.compile(r"^\s*\[\s*([Xx]?)\s*\]\s*([A-Ea-e])\)")
_NAME = re.compile(r"^\s*Aluno\(?a?\)?\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_KEY = re.compile(r"\b(\d{1,3})\s*[-:.)]?\s*([A-Ea-e])\b")


@dataclass
class Question:
    stem: str = ""
    options: dict = field(default_factory=dict)  # letter -> the option's text


@dataclass(frozen=True)
class Exam:
    file: str
    student: str
    marks: dict[int, str]  # question -> the letters marked ("" = none, "BD" = two)
    notes: tuple = ()  # things the teacher should look at (a doubtful mark, a name that could not be read)
    questions: dict = field(default_factory=dict, compare=False)  # question -> Question (text and options), for explaining the mistakes


def parse_key(text: str) -> dict[int, str]:
    """"1E - 2B - 3B" -> {1: "E", 2: "B", 3: "B"}"""
    key = {int(n): letter.upper() for n, letter in _KEY.findall(text)}
    if not key or len(key) > MAX_QUESTIONS:
        raise ComputerError("não entendi o gabarito: escreva assim, “1E - 2B - 3B”")
    return key


def parse_text(file: str, text: str) -> Exam:
    marks: dict[int, str] = {}
    questions: dict[int, Question] = {}
    question = None
    for line in text.splitlines():
        if (q := _QUESTION.match(line)) and not _OPTION.match(line):
            question = int(q.group(1))
            marks.setdefault(question, "")
            questions[question] = Question(re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", line).strip())
        elif (o := _OPTION.match(line)) and question is not None:
            questions[question].options[o.group(2).upper()] = line[o.end():].strip()
            if o.group(1):
                marks[question] += o.group(2).upper()
        elif question is not None and not questions[question].options and line.strip() and not _NAME.match(line):
            questions[question].stem += " " + line.strip()  # the question's text wraps over several lines
    text = unicodedata.normalize("NFKC", text)  # the PDF's "ﬁ" ligature is not an "fi"
    name = _NAME.search(text)
    return Exam(file, (name.group(1).strip() if name else Path(file).stem)[:80], marks, (), questions)


def read_folder(folder: Path) -> tuple[list[Exam], list[str]]:
    """(the exams read, the files that could not be read)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ComputerError(missing_message("documents", "Reading the exams (PDF)")) from exc
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png"} and not p.name.startswith("."))
    if not files:
        raise ComputerError(f"não há provas (PDF, JPG ou PNG) na pasta {folder.name}")
    if len(files) > MAX_FILES:
        raise ComputerError(f"são {len(files)} arquivos; corrijo até {MAX_FILES} por vez")
    exams, unreadable, ocr_missing = [], [], None
    for path in files:
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("big")
            exam = None
            if path.suffix.lower() == ".pdf":  # a PDF with text is read as text; one that is only a picture (a scan) goes to the OCR
                text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages[:6])
                parsed = parse_text(path.name, text)
                exam = parsed if parsed.marks else None
            if exam is None:
                from chakmati.computer import ocr
                exam = ocr.read_scan(path)
            exams.append(exam)
        except ComputerError as exc:
            if "extra" in str(exc) or "uv sync" in str(exc):
                ocr_missing = exc  # not this file's fault: say what to install
            unreadable.append(path.name)
        except Exception:
            unreadable.append(path.name)
    if ocr_missing is not None and not exams:
        raise ocr_missing
    return exams, unreadable


def grade(exams: list[Exam], key: dict[int, str], points: float) -> tuple[dict, dict]:
    """(the spreadsheet spec for documents.check_spec, a summary for the person)."""
    questions = sorted(key)
    letters = "BCDEFGHIJKLMNOPQRSTUVWXYZ"
    last = letters[len(questions) - 1] if len(questions) <= 25 else "Z"
    header = ["Aluno", *(f"Q{q}" for q in questions), "Acertos", "Nota", "Observações"]  # (explanations, when asked for, go on a second sheet)
    rows: list[list] = [header, ["Gabarito", *(key[q] for q in questions), "", "", ""]]
    top = []
    for i, exam in enumerate(exams, start=3):
        shown, notes = [], []
        for q in questions:
            m = exam.marks.get(q, "")
            shown.append(m or "-")
            if not m:
                notes.append(f"Q{q} em branco")
            elif len(m) > 1:
                notes.append(f"Q{q} com mais de uma marca ({m})")
        hits = "+".join(f'IF({letters[j]}{i}={letters[j]}$2,1,0)' for j in range(len(questions)))
        acertos_col, nota_col = letters[len(questions)], letters[len(questions) + 1]
        rows.append([exam.student, *shown, f"={hits}", f"={acertos_col}{i}*{points:g}", "; ".join([*notes, *exam.notes])])
        got = sum(1 for q in questions if exam.marks.get(q, "") == key[q])
        if got == len(questions):
            top.append(exam.student)
    n = len(exams)
    if n:
        a, b = letters[len(questions)], letters[len(questions) + 1]
        rows.append(["Média da turma", *[""] * len(questions), f"=AVERAGE({a}3:{a}{n + 2})", f"=AVERAGE({b}3:{b}{n + 2})", ""])
    flagged = sum(1 for r in rows[2 : 2 + n] if r[-1])
    return {"sheets": [{"name": "Correção", "rows": rows}]}, {"alunos": n, "acertaram_tudo": top, "com_observacao": flagged}


def question_texts(exams: list[Exam]) -> dict[int, Question]:
    """The text of each question, from the first exam that has it (the copies are all the same exam)."""
    found: dict[int, Question] = {}
    for exam in exams:
        for number, q in exam.questions.items():
            if number not in found or (len(q.options) > len(found[number].options)):
                found[number] = q
    return found


def mistakes(exams: list[Exam], key: dict[int, str]) -> list[tuple[str, int, str, str]]:
    """(student, question, letters marked or "", the right letter) for every question not answered rightly."""
    return [(e.student, q, e.marks.get(q, ""), key[q]) for e in exams for q in sorted(key) if e.marks.get(q, "") != key[q]]


def inspect_folder(folder: Path) -> dict:
    """What is in a folder of exams, without grading anything: how many files and how each one will have to be read."""
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    found = {"files": 0, "text_pdf": 0, "scanned_pdf": 0, "images": 0}
    for path in sorted(folder.iterdir()):
        suffix = path.suffix.lower()
        if not path.is_file() or path.name.startswith(".") or suffix not in {".pdf", ".jpg", ".jpeg", ".png"}:
            continue
        found["files"] += 1
        if suffix != ".pdf":
            found["images"] += 1
            continue
        try:
            has_text = PdfReader is not None and bool(parse_text(path.name, (PdfReader(str(path)).pages[0].extract_text() or "")).marks)
        except Exception:
            has_text = False
        found["text_pdf" if has_text else "scanned_pdf"] += 1
    return found
