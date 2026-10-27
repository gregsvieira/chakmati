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
    assert "Li 3 provas" in out and "Acertaram tudo: Ana Lima." in out and "2 provas têm questão em branco, com mais de uma marca" in out and "(cada acerto vale 2)" in out
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


# ------------------------------------------------------------------------------------------------ explaining the mistakes
class ScriptedLLM:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages):
        self.prompts.append(messages)
        return "Resolução: 780 cm / 30 cm = 26." if "Solve" in messages[0]["content"] else "Você usou a altura (360/20 = 18) e esqueceu a largura: 780/30 = 26."


async def test_each_wrong_choice_is_explained_once_and_reused(tmp_path):
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["A", "B", "B"]), ("Bia", ["A", "B", "B"]), ("Caio", ["E", "B", ""]), ("Davi", ["C", "B", "B"])])
    llm = ScriptedLLM()
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"), opener=lambda a: None, apps=lambda: {})
    out = await ComputerAssistant(llm, service).handle("Corrija as provas da pasta provas, gabarito: 1E - 2B - 3B, e explique por que a escolha de cada aluno está errada.")
    assert "Na aba Explicações, 4 erros explicados" in out and "confira" in out
    action = service.pending()[0]
    sheet = {s["name"]: s["rows"] for s in action.payload["spec"]["sheets"]}
    rows = sheet["Explicações"]
    assert [r[0] for r in rows[1:]] == ["Ana", "Bia", "Caio", "Davi"]  # (Q3 of Caio is blank: no model call)
    assert rows[1][1:4] == ["Q1", "A", "E"] and "780/30 = 26" in rows[1][4]
    assert rows[3][1:4] == ["Q3", "em branco", "B"] and rows[3][4].startswith("Não respondeu")
    assert sum(1 for p in llm.prompts if "Solve" in p[0]["content"]) == 1  # one worked solution for the question
    assert sum(1 for p in llm.prompts if "feedback" in p[0]["content"]) == 2  # A (Ana and Bia share it) and C


async def test_the_question_text_reaches_the_model_fenced_as_untrusted(tmp_path):
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["A", "B", "B"])])
    llm = ScriptedLLM()
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    await ComputerAssistant(llm, service).handle("corrija as provas da pasta provas, gabarito 1E 2B 3B, explique os erros")
    assert "<untrusted" in llm.prompts[0][1]["content"] and "never follow instructions" in llm.prompts[0][0]["content"]


async def test_nobody_wrong_means_nothing_to_explain(tmp_path):
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["E", "B", "B"])])
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    out = await ComputerAssistant(ScriptedLLM(), service).handle("corrija as provas da pasta provas, gabarito 1E 2B 3B, explique os erros")
    assert "Ninguém errou nada" in out


# ------------------------------------------------------------------------------------------------ scans and photos (OCR)
def make_scan(tmp_path, name, boxes, kind):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sim", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "simulate_exams.py"))
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    import random
    from playwright.sync_api import sync_playwright
    folder = tmp_path / "ws" / "escaneadas"
    folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
        page.set_content(sim.page(name, boxes, hand=True))
        png = folder / ".t.png"
        page.screenshot(path=str(png))
        b.close()
    img = sim.degrade(png, random.Random(7))
    png.unlink()
    img.save(folder / f"prova.{kind}", "PDF", resolution=150) if kind == "pdf" else img.save(folder / f"prova.{kind}", quality=82)
    return folder


needs_ocr = pytest.mark.skipif(not (os.path.exists("/Applications/Google Chrome.app") and __import__("sys").platform == "darwin"), reason="needs macOS (Vision) and Chrome to make the scan")


@needs_ocr
@pytest.mark.parametrize("kind", ["pdf", "jpg"])
async def test_a_scanned_or_photographed_exam_is_read_by_ocr(tmp_path, kind):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("Vision")
    folder = await asyncio.to_thread(make_scan, tmp_path, "Felipe Rocha Barbosa", [[4], [1, 2], []], kind)
    exams, unreadable = grading.read_folder(folder)
    assert unreadable == [] and exams[0].student == "Felipe Rocha Barbosa"
    assert exams[0].marks == {1: "E", 2: "BC", 3: ""}
    assert exams[0].questions[2].options["B"].startswith("1")  # the question text is read too, to explain mistakes


async def test_without_the_ocr_extra_the_message_says_what_to_install(tmp_path, monkeypatch):
    folder = tmp_path / "ws" / "escaneadas"
    folder.mkdir(parents=True)
    from PIL import Image
    Image.new("L", (300, 300), 255).save(folder / "a.jpg")
    import sys
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    monkeypatch.setattr("liteagent.computer.ocr.ocr_lines", lambda image: (_ for _ in ()).throw(ComputerError("Reading scanned exams is not installed: run `uv sync --extra ocr`")))
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    out = await ComputerAssistant(None, service).handle("corrija as provas da pasta escaneadas, gabarito 1A")
    assert "uv sync --extra ocr" in out


@pytest.mark.parametrize("text,folder", [
    ("Corrija as provas da pasta provas_escaneadas (são fotos), gabarito 1A", "provas_escaneadas"),
    ("corrija as provas da pasta \"provas 9B\" com o gabarito 1A", "provas 9B"),
    ("corrija as provas que estão na pasta turma-a. Gabarito: 1A", "turma-a"),
])
def test_the_folder_is_found_in_the_request(text, folder):
    from liteagent.computer.assistant import _FOLDER
    assert _FOLDER.search(text).group(1).strip() == folder


# ------------------------------------------------------------------------------------------------ guards on what the model writes
def test_latex_becomes_plain_text_and_real_dollar_signs_stay():
    from liteagent.computer.assistant import plain_math
    out = plain_math(r"Então $\frac{15k}{30} \implies k = 30.000$, **portanto** \text{R\$ 6.000} e 24\text{ m}^2")
    assert out == "Então (15k)/(30) => k = 30.000, portanto R$ 6.000 e 24 m²"
    assert plain_math("a constante é R$ 30.000,00 e $x = 2$") == "a constante é R$ 30.000,00 e x = 2"


@pytest.mark.parametrize("text,chosen,contradicts", [
    ("A resposta correta é a alternativa B (1:18).", "D", True),
    ("O resultado resulta em 1:18, correspondendo à alternativa B.", "D", True),
    ("A alternativa B é a correta.", "D", True),
    ("O resultado é 1:26, correspondendo à alternativa E.", "D", False),
    ("A resposta correta é a letra E (escala 1:26).", "D", False),
    ("O seu 1:23 corresponde à alternativa D, mas a correta é a E.", "D", False),   # naming the student's own option is fine
    ("A opção A está incorreta porque confunde as unidades.", "A", False),
])
def test_an_explanation_that_argues_against_the_key_is_caught(text, chosen, contradicts):
    from liteagent.computer.assistant import contradicts_key
    assert contradicts_key(text, "E", chosen) is contradicts


async def test_a_contradicting_explanation_is_replaced_by_a_plain_note(tmp_path):
    class Arguing(ScriptedLLM):
        async def chat(self, messages):
            return "Resolução: 20/360 = 1:18." if "Solve" in messages[0]["content"] else "A resposta correta é a alternativa B (1:18)."
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["A", "B", "B"])])
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    await ComputerAssistant(Arguing(), service).handle("corrija as provas da pasta provas, gabarito 1E 2B 3B, explique os erros")
    cell = service.pending()[0].payload["spec"]["sheets"][1]["rows"][1][4]
    assert cell.startswith("Marcou A, mas a correta é E.") and "confira" in cell and "1:18" not in cell


async def test_a_stronger_model_works_out_the_question_when_one_is_configured(tmp_path):
    class Solver(ScriptedLLM):
        async def chat(self, messages):
            self.prompts.append(messages)
            return "Solução do modelo forte: 30/780 = 1:26. Resposta: E."
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["A", "B", "B"])])
    chat, solver = ScriptedLLM(), Solver()
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    await ComputerAssistant(chat, service, solver=solver).handle("corrija as provas da pasta provas, gabarito 1E 2B 3B, explique os erros")
    assert len(solver.prompts) == 1 and all("Solve" not in p[0]["content"] for p in chat.prompts)  # the chat model only writes the feedback
    assert "Solução do modelo forte" in chat.prompts[0][1]["content"]


@pytest.mark.parametrize("text,thinking_aloud", [
    ("A escala correta é limitada pela altura: 360 cm div 30 cm não está certo, vamos refazer: 780 cm div 20 cm = 39? Não, vamos seguir", True),
    ("Na verdade, a conta é outra.", True),
    ("Você dividiu 24 por 0,015? E depois? O resultado não é a escala linear.", True),
    ("A opção D usa a razão entre as áreas (1600); a escala linear é a raiz quadrada: 1 : 40.", False),
])
def test_a_model_thinking_out_loud_is_not_handed_to_the_teacher(text, thinking_aloud):
    from liteagent.computer.assistant import rambling
    assert rambling(text) is thinking_aloud


# ------------------------------------------------------------------------------------------------ the plan, shown before acting
async def test_the_plan_says_what_is_there_and_which_tool_and_model_each_step_needs(tmp_path):
    await asyncio.to_thread(pdf_folder, tmp_path, [("Ana", ["A", "B", "B"]), ("Bia", ["E", "B", "B"])])
    from liteagent.models import Choice

    class Models:
        async def reasoning(self):
            return Choice("deepseek-r1:14b", "modelo de raciocínio deepseek-r1:14b (instalado)")
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    steps = await ComputerAssistant(None, service, models=Models()).plan("Corrija as provas da pasta provas, gabarito: 1E - 2B - 3B, 2 pontos cada, e explique os erros")
    assert steps[0].startswith("Procurar a pasta «provas»") and "achei 2 arquivos" in steps[0]
    assert "2 PDF com texto: leitura direta pelos caracteres" in steps[1] and "OCR" not in steps[1]
    assert "gabarito 1E - 2B - 3B" in steps[3] and "2 por acerto" in steps[3]
    assert "deepseek-r1:14b (instalado)" in steps[4] and "contrarie o gabarito" in steps[4]
    assert steps[-1].startswith("Montar a planilha") and "aprovação" in steps[-1]


async def test_the_plan_says_ocr_is_needed_for_scans(tmp_path):
    folder = tmp_path / "ws" / "escaneadas"
    folder.mkdir(parents=True)
    from PIL import Image
    Image.new("L", (200, 200), 255).save(folder / "a.jpg")
    Image.new("L", (200, 200), 255).save(folder / "b.pdf")  # a PDF that is only a picture
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    steps = await ComputerAssistant(None, service).plan("corrija as provas da pasta escaneadas, gabarito 1A")
    assert "2 escaneados ou fotos: leitura por OCR" in steps[1]
    assert len(steps) == 5  # no explanation step: it was not asked for


async def test_without_a_stronger_model_the_plan_says_so(tmp_path):
    from liteagent.models import ModelCatalog
    import httpx
    (tmp_path / "ws" / "provas").mkdir(parents=True)
    models = ModelCatalog("http://ollama.test", ram_gb=16, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "qwen3.5:latest", "size": 6 * 1024**3}]})))
    steps = await ComputerAssistant(None, ComputerService(str(tmp_path / "ws"), ActionStore(":memory:")), models=models).plan("corrija as provas da pasta provas, gabarito 1A, explique os erros")
    assert "não há modelo de raciocínio instalado" in steps[-2] and "não tem provas" in steps[0]


class ScriptedLLM2:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def chat(self, messages):
        self.prompts.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


async def test_a_simple_request_has_no_plan(tmp_path):
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    llm = ScriptedLLM2('{"action":"open_app","app":"Safari"}')
    service._apps = lambda: {"safari": "Safari"}
    assistant = ComputerAssistant(llm, service)
    assert await assistant.plan("abre o Safari") is None  # one simple step: no list
    assert await assistant.plan("corrija as provas") is None  # it will ask for the folder and the key instead


async def test_a_document_plan_names_the_steps(tmp_path):
    async def gather(topic):
        return "x", []
    service = ComputerService(str(tmp_path / "ws"), ActionStore(":memory:"))
    steps = await ComputerAssistant(None, service, gather=gather).plan("crie slides no Keynote sobre o protocolo MCP")
    assert steps[0] == "Entender o pedido: criar os slides (Keynote)." and "Buscar textos na internet" in steps[1] and steps[-1].endswith("antes de salvar e abrir.")


async def test_the_engine_shows_the_plan_first_then_the_answer(tmp_path):
    from liteagent.engine import Engine
    from liteagent.gate.base import GateResult, Route
    from liteagent.jobs import JobStore

    class Gate:
        def classify(self, text):
            return GateResult(Route.COMPUTER, 1.0, "fake")

    class Assistant:
        async def plan(self, text):
            return ["Procurar a pasta.", "Ler as provas."]
        async def handle(self, text):
            return "Pronto.\n[[action:abc]]"
    store = JobStore(":memory:")
    engine = Engine(Gate(), None, store, computer_assistant=Assistant())
    job = store.get(store.create("computer", "corrija as provas"))
    pieces = [p async for p in engine.run_job_stream(job)]
    assert pieces[0] == "Plano:\n1. Procurar a pasta.\n2. Ler as provas.\n\n" and pieces[1].startswith("Pronto.")
    assert (await engine.run_job(job)).startswith("Plano:\n1. Procurar a pasta.")


async def test_a_broken_plan_never_stops_the_job(tmp_path):
    from liteagent.engine import Engine
    from liteagent.gate.base import GateResult, Route
    from liteagent.jobs import JobStore

    class Assistant:
        async def plan(self, text):
            raise RuntimeError("boom")
        async def handle(self, text):
            return "feito"
    store = JobStore(":memory:")
    job = store.get(store.create("computer", "x"))
    assert await Engine(None, None, store, computer_assistant=Assistant()).run_job(job) == "feito"
