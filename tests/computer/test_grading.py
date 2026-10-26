import asyncio
import os

import pytest

from liteagent.approvals import ActionStore
from liteagent.computer import grading
from liteagent.computer.assistant import ComputerAssistant
from liteagent.computer.safety import ComputerError
from liteagent.computer.service import ComputerService
from liteagent.gate.base import Route
from liteagent.gate.heuristic import HeuristicGate

TEXT = """PROVA DE MATEMÁTICA
1. (ENEM 2024) Um pintor pretende fazer uma reprodução:
[ ]  A) 1 : 12.
[X] E) 1 : 26.
2. (ENEM 2024) Na planta baixa de uma casa:
[X] B) 1 : 40.
[X] C) 1 : 60.
3. (Enem 2019) Para contratar três máquinas:
[ ]  A) R$ 3.100,00
[ ]  B) R$ 6.000,00
Escola: Escola X
Aluno: Soﬁa Reis
12 / 11 / 2026"""


def test_the_key_is_read_from_the_teachers_words():
    assert grading.parse_key("1E - 2B - 3B") == {1: "E", 2: "B", 3: "B"}
    assert grading.parse_key("1-e, 2:b e 3)B") == {1: "E", 2: "B", 3: "B"}
    with pytest.raises(ComputerError):
        grading.parse_key("sem gabarito")


def test_marks_and_name_are_read_from_the_text():
    exam = grading.parse_text("p.pdf", TEXT)
    assert exam.student == "Sofia Reis" and exam.marks == {1: "E", 2: "BC", 3: ""}


def test_double_and_blank_marks_are_wrong_and_flagged():
    spec, summary = grading.grade([grading.parse_text("p.pdf", TEXT)], {1: "E", 2: "B", 3: "B"}, 1)
    rows = spec["sheets"][0]["rows"]
    assert rows[2][:4] == ["Sofia Reis", "E", "BC", "-"] and "Q2 com mais de uma marca (BC)" in rows[2][-1] and "Q3 em branco" in rows[2][-1]
    assert rows[2][4] == "=IF(B3=B$2,1,0)+IF(C3=C$2,1,0)+IF(D3=D$2,1,0)" and rows[3][4] == "=AVERAGE(E3:E3)"
    assert summary == {"alunos": 1, "acertaram_tudo": [], "com_observacao": 1}


def test_the_spreadsheet_formulas_pass_the_allow_list():
    from liteagent.computer import documents
    spec, _ = grading.grade([grading.parse_text("a.pdf", TEXT)] * 3, {1: "E", 2: "B", 3: "B"}, 0.5)
    documents.check_spec("xlsx", spec)  # raises if a formula is not allowed


# ------------------------------------------------------------------------------------------------ the whole flow, with real PDFs
def pdf_folder(tmp_path, copies):
    pytest.importorskip("pypdf")
    from playwright.sync_api import sync_playwright
    if not os.path.exists("/Applications/Google Chrome.app"):
        pytest.skip("needs Google Chrome to make the PDFs")
    folder = tmp_path / "ws" / "provas"
    folder.mkdir(parents=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page()
        for i, (name, boxes) in enumerate(copies, 1):
            body = "".join(f"<p>{n}. Pergunta {n}?</p>" + "".join(f"<p>[{'X' if L in marked else '&nbsp;'}] {L}) opção</p>" for L in "ABCDE") for n, marked in enumerate(boxes, 1))
            page.set_content(f"<html><body><h1>PROVA</h1>{body}<p>Aluno: {name}</p></body></html>")
            page.pdf(path=str(folder / f"p{i}.pdf"))
        b.close()
    return folder


async def test_a_teacher_pile_of_pdfs_becomes_a_graded_spreadsheet(tmp_path):
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana Lima", ["E", "B", "B"]), ("Bruno Dias", ["A", "B", ""]), ("Carla Nunes", ["E", "BD", "B"])])
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"), opener=lambda a: None, apps=lambda: {})
    out = await ComputerAssistant(None, service).handle("Corrija as provas da pasta provas. O gabarito é: 1E - 2B - 3B. Cada acerto vale 2 pontos. Monte uma planilha no Numbers.")
    assert "Li 3 provas" in out and "Acertaram tudo: Ana Lima." in out and "2 provas têm questão em branco ou com mais de uma marca" in out and "(cada acerto vale 2)" in out
    action = service.pending()[0]
    assert action.payload["path"].endswith("correcao-provas.xlsx")
    import openpyxl
    service.approve(action.id)
    ws = openpyxl.load_workbook(action.payload["path"]).worksheets[0]
    assert [c.value for c in ws[3]][:5] == ["Ana Lima", "E", "B", "B", "=IF(B3=B$2,1,0)+IF(C3=C$2,1,0)+IF(D3=D$2,1,0)"]
    assert ws["F3"].value == "=E3*2"


async def test_it_asks_for_what_is_missing(tmp_path):
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    assistant = ComputerAssistant(None, service)
    assert "Qual é o gabarito" in await assistant.handle("corrija as provas da pasta provas")
    assert "Em que pasta" in await assistant.handle("corrija as provas, gabarito 1E 2B")


async def test_a_folder_outside_the_workspace_is_refused(tmp_path):
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    out = await ComputerAssistant(None, service).handle("corrija as provas da pasta /etc, gabarito 1A")
    assert out.startswith("Não consegui")


@pytest.mark.parametrize("text", ["Corrija as 20 provas de matemática da pasta provas", "corrige essas provas pra mim", "faça a correção das provas"])
def test_grading_requests_go_to_the_computer(text):
    assert HeuristicGate().classify(text).route is Route.COMPUTER
