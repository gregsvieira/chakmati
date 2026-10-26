"""Grading multiple-choice exams that are PDFs with an "X" in the chosen box, against an answer key.

Done in code, never by the model: the text of each PDF is parsed for the lines "[X] B) ..." and the student's name for "Aluno: ...";
the marks are compared with the key the PERSON gave in the request. A question with no X, or with more than one, counts as wrong and
is flagged for the teacher to look at. The PDFs' text is other people's text: it only goes through these regular expressions."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..extras import missing_message
from .safety import ComputerError

MAX_FILES, MAX_BYTES, MAX_QUESTIONS = 100, 8_000_000, 100
_QUESTION = re.compile(r"^\s*(\d{1,3})\s*[.)]\s+\S")
_OPTION = re.compile(r"^\s*\[\s*([Xx]?)\s*\]\s*([A-Ea-e])\)")
_NAME = re.compile(r"^\s*Aluno\(?a?\)?\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_KEY = re.compile(r"\b(\d{1,3})\s*[-:.)]?\s*([A-Ea-e])\b")


@dataclass(frozen=True)
class Exam:
    file: str
    student: str
    marks: dict[int, str]  # question -> the letters marked ("" = none, "BD" = two)


def parse_key(text: str) -> dict[int, str]:
    """"1E - 2B - 3B" -> {1: "E", 2: "B", 3: "B"}"""
    key = {int(n): letter.upper() for n, letter in _KEY.findall(text)}
    if not key or len(key) > MAX_QUESTIONS:
        raise ComputerError("não entendi o gabarito: escreva assim, “1E - 2B - 3B”")
    return key


def parse_text(file: str, text: str) -> Exam:
    marks: dict[int, str] = {}
    question = None
    for line in text.splitlines():
        if (q := _QUESTION.match(line)) and not _OPTION.match(line):
            question = int(q.group(1))
            marks.setdefault(question, "")
        elif (o := _OPTION.match(line)) and question is not None and o.group(1):
            marks[question] += o.group(2).upper()
    text = unicodedata.normalize("NFKC", text)  # the PDF's "ﬁ" ligature is not an "fi"
    name = _NAME.search(text)
    return Exam(file, (name.group(1).strip() if name else Path(file).stem)[:80], marks)


def read_folder(folder: Path) -> tuple[list[Exam], list[str]]:
    """(the exams read, the files that could not be read)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ComputerError(missing_message("documents", "Reading the exams (PDF)")) from exc
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("."))
    if not files:
        raise ComputerError(f"não há PDFs na pasta {folder.name}")
    if len(files) > MAX_FILES:
        raise ComputerError(f"são {len(files)} PDFs; corrijo até {MAX_FILES} por vez")
    exams, unreadable = [], []
    for path in files:
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("big")
            text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages[:6])
            exam = parse_text(path.name, text)
            if not exam.marks:
                raise ValueError("no questions")
            exams.append(exam)
        except Exception:
            unreadable.append(path.name)
    return exams, unreadable


def grade(exams: list[Exam], key: dict[int, str], points: float) -> tuple[dict, dict]:
    """(the spreadsheet spec for documents.check_spec, a summary for the person)."""
    questions = sorted(key)
    letters = "BCDEFGHIJKLMNOPQRSTUVWXYZ"
    last = letters[len(questions) - 1] if len(questions) <= 25 else "Z"
    header = ["Aluno", *(f"Q{q}" for q in questions), "Acertos", "Nota", "Observações"]
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
        rows.append([exam.student, *shown, f"={hits}", f"={acertos_col}{i}*{points:g}", "; ".join(notes)])
        got = sum(1 for q in questions if exam.marks.get(q, "") == key[q])
        if got == len(questions):
            top.append(exam.student)
    n = len(exams)
    if n:
        a, b = letters[len(questions)], letters[len(questions) + 1]
        rows.append(["Média da turma", *[""] * len(questions), f"=AVERAGE({a}3:{a}{n + 2})", f"=AVERAGE({b}3:{b}{n + 2})", ""])
    flagged = sum(1 for r in rows[2 : 2 + n] if r[-1])
    return {"sheets": [{"name": "Correção", "rows": rows}]}, {"alunos": n, "acertaram_tudo": top, "com_observacao": flagged}
