"""The browser agent asks the person for what only they know (user name, password), and never makes it up."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from chakmati.api import create_app
from chakmati.browser.agent import BrowserAgent, describe, is_personal_field, start_url
from chakmati.browser.frames import FrameStore
from chakmati.browser.inputs import InputBroker
from chakmati.browser.session import BrowserError, Snapshot
from chakmati.engine import Engine
from chakmati.gate.base import GateResult, Route
from chakmati.gate.heuristic import HeuristicGate
from chakmati.jobs import JobStore, Worker

JOB = "b" * 32
LOGIN = [{"id": 1, "tag": "input", "type": "text", "label": "Número de celular, nome de usuário ou email"},
         {"id": 2, "tag": "input", "type": "password", "label": "Senha"},
         {"id": 3, "tag": "button", "type": "", "label": "Entrar"},
         {"id": 4, "tag": "input", "type": "search", "label": "Pesquisar"}]


class LoginSession:
    def __init__(self):
        self.typed = []
        self.url = "https://www.instagram.com/"

    async def start(self): pass
    async def close(self): pass
    async def goto(self, url): self.url = url
    async def back(self): pass
    async def click(self, ident): pass
    async def scroll(self, down): pass
    async def screenshot(self): return b"\xff\xd8x"
    async def snapshot(self): return Snapshot(self.url, "Entrar", "Entre na sua conta", LOGIN)

    async def type(self, ident, text, submit, secret=False):
        if ident == 2 and not secret:
            raise BrowserError("uma senha só é digitada se você me der")
        self.typed.append((ident, text, submit, secret))


class LLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


def agent(llm, tmp_path, session, ask):
    return BrowserAgent(llm, FrameStore(tmp_path), lambda: session, ask=ask)


async def run(a, task="acesse meu instagram"):
    return [p async for p in a.run(JOB, task)]


ASK_USER = '{"action":"ask","key":"usuario","question":"Qual é o seu usuário do Instagram?"}'
ASK_PASS = '{"action":"ask","key":"senha","question":"E a sua senha?","secret":true}'


async def test_the_agent_asks_instead_of_inventing_and_types_what_the_person_answered(tmp_path):
    asked, session = [], LoginSession()

    async def ask(job_id, key, question, secret):
        asked.append((key, question, secret))
        return {"usuario": "gregory.v", "senha": "s3gredo!"}[key]
    llm = LLM(ASK_USER, '{"action":"type","id":1,"from":"usuario"}', ASK_PASS, '{"action":"type","id":2,"from":"senha","enter":true}', '{"action":"done","answer":"entrei"}')
    assert await run(agent(llm, tmp_path, session, ask)) == ["entrei"]
    assert asked == [("usuario", "Qual é o seu usuário do Instagram?", False), ("senha", "E a sua senha?", True)]
    assert session.typed == [(1, "gregory.v", False, False), (2, "s3gredo!", True, True)]


async def test_what_the_person_answered_never_reaches_the_model_or_the_captions(tmp_path):
    session = LoginSession()

    async def ask(job_id, key, question, secret):
        return {"usuario": "gregory.v", "senha": "s3gredo!"}[key]
    llm = LLM(ASK_USER, '{"action":"type","id":1,"from":"usuario"}', ASK_PASS, '{"action":"type","id":2,"from":"senha","enter":true}', '{"action":"done","answer":"ok"}')
    frames = FrameStore(tmp_path)
    await run(BrowserAgent(llm, frames, lambda: session, ask=ask))
    everything = json.dumps(llm.prompts) + json.dumps(frames.list(JOB))
    assert "s3gredo!" not in everything and "gregory.v" not in everything
    assert "Digitando a senha" in everything and "Esperando a sua resposta" in everything


async def test_a_made_up_user_name_is_refused_and_the_model_is_told_to_ask(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"type","id":1,"text":"meuusuario"}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None))
    assert session.typed == []
    assert "pede um dado pessoal" in llm.prompts[1] and "ask" in llm.prompts[1]


async def test_a_password_is_never_typed_from_text_even_when_it_is_in_the_task(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"type","id":2,"text":"abc123"}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None), "entre no instagram com a senha abc123")
    assert session.typed == []  # the session refuses a password that did not come from the person's answer


async def test_a_value_the_person_wrote_in_the_request_may_be_typed(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"type","id":1,"text":"gregory.v"}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None), "entre no instagram com o usuário gregory.v")
    assert session.typed == [(1, "gregory.v", False, False)]


async def test_a_search_box_may_be_typed_into_freely(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"type","id":4,"text":"gatos","enter":true}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None))
    assert session.typed == [(4, "gatos", True, False)]


async def test_typing_from_an_answer_that_was_never_asked_is_refused(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"type","id":1,"from":"usuario"}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None))
    assert session.typed == [] and "ainda não perguntei" in llm.prompts[1]


async def test_no_answer_in_time_stops_politely(tmp_path):
    async def ask(*a):
        return None
    out = await run(agent(LLM(ASK_USER), tmp_path, LoginSession(), ask))
    assert out == ["Não recebi a sua resposta a tempo, então parei. Peça de novo quando quiser continuar."]


async def test_nobody_to_ask_is_said(tmp_path):
    out = await run(agent(LLM(ASK_USER), tmp_path, LoginSession(), None))
    assert "consigo perguntar" in out[0]


async def test_the_same_question_is_not_asked_twice(tmp_path):
    calls = []

    async def ask(job_id, key, question, secret):
        calls.append(key)
        return "x"
    await run(agent(LLM(ASK_USER, ASK_USER, '{"action":"done","answer":"ok"}'), tmp_path, LoginSession(), ask))
    assert calls == ["usuario"]


def test_which_fields_are_personal():
    assert is_personal_field({"type": "password", "label": ""})
    assert is_personal_field({"type": "text", "label": "Número de celular, nome de usuário ou email"})
    assert is_personal_field({"type": "text", "label": "Código de segurança"})
    assert not is_personal_field({"type": "text", "label": "Pesquisar"})
    assert not is_personal_field({"type": "search", "label": "Search the site"})
    assert not is_personal_field({"type": "text", "label": "Mensagem"})


def test_the_caption_names_what_is_typed_but_never_shows_it():
    assert describe({"action": "type", "from": "senha"}, frozenset({"senha"})) == "Digitando a senha"
    assert describe({"action": "type", "from": "usuario"}) == "Digitando o dado “usuario”"
    assert describe({"action": "ask"}) == "Esperando a sua resposta"


@pytest.mark.parametrize("task,url", [("Acesse meu instagram e envie uma mensagem", "https://www.instagram.com/"), ("entre no github", "https://github.com/"), ("pesquise sobre o instagram", "https://duckduckgo.com/")])
def test_a_site_the_person_names_is_opened_directly(task, url):
    assert start_url(task) == url


def test_a_named_site_goes_to_the_browser_not_whatsapp():
    gate = HeuristicGate()
    assert gate.classify('Acesse meu instagram e envie uma mensagem para Paulo: "Oi"').route is Route.BROWSER
    assert gate.classify("manda no whatsapp pro João").route is Route.WHATSAPP


# ------------------------------------------------------------------------------------------------ the broker and the API
async def test_the_broker_hands_the_answer_to_the_one_waiting():
    broker = InputBroker(timeout=2)
    waiting = asyncio.create_task(broker.ask(JOB, "usuario", "Qual?", False))
    await asyncio.sleep(0.01)
    request = broker.pending(JOB)
    assert request.prompt == "Qual?" and not broker.answer(JOB, "0" * 32, "x")   # a wrong request id is refused
    assert broker.answer(JOB, request.id, "gregory") and await waiting == "gregory"
    assert broker.pending(JOB) is None and not broker.answer(JOB, request.id, "again")


async def test_the_broker_gives_up_after_the_timeout():
    assert await InputBroker(timeout=0.05).ask(JOB, "k", "?", True) is None


class OneGate:
    def classify(self, text):
        return GateResult(Route.BROWSER, 1.0, "fake")


def test_the_question_reaches_the_client_and_the_answer_comes_back_over_the_api(tmp_path):
    store, frames, broker = JobStore(":memory:"), FrameStore(tmp_path), InputBroker(timeout=10)
    session = LoginSession()
    llm = LLM(ASK_PASS, '{"action":"type","id":2,"from":"senha","enter":true}', '{"action":"done","answer":"entrei"}')
    engine = Engine(OneGate(), llm, store, browser_agent=BrowserAgent(llm, frames, lambda: session, ask=broker.ask))
    worker = Worker(store, engine.run_job, stream_handler=engine.run_job_stream)
    client = TestClient(create_app(engine, store, worker, frames=frames, inputs=broker))
    events = []
    with client:
        with client.stream("POST", "/message/stream", json={"text": "acesse meu instagram"}) as r:
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                events.append(event)
                if event["type"] == "input":
                    assert event["secret"] is True and event["prompt"] == "E a sua senha?" and event["key"] == "senha"
                    no_header = client.post(f"/jobs/{event['job_id']}/input", json={"request_id": event["request_id"], "value": "s3gredo!"})
                    assert no_header.status_code == 403            # only the app's own window may answer
                    wrong = client.post(f"/jobs/{event['job_id']}/input", headers={"X-LiteAgent-UI": "1"}, json={"request_id": "0" * 32, "value": "x"})
                    assert wrong.status_code == 404
                    ok = client.post(f"/jobs/{event['job_id']}/input", headers={"X-LiteAgent-UI": "1"}, json={"request_id": event["request_id"], "value": "s3gredo!"})
                    assert ok.status_code == 200
    kinds = [e["type"] for e in events]
    assert "input" in kinds and "input_done" in kinds and events[-1]["type"] == "done" and events[-1]["result"].endswith("entrei")
    assert session.typed == [(2, "s3gredo!", True, True)]
    assert "s3gredo!" not in json.dumps(events)                    # the answer is not echoed back in the stream


@pytest.mark.parametrize("text,route", [
    ("Entre em https://the-internet.herokuapp.com/login com o meu usuário e a minha senha", Route.BROWSER),
    ("abra https://pt.wikipedia.org/wiki/Canberra e me diga o ano", Route.BROWSER),
    ("abra https://example.org", Route.COMPUTER),                      # only opening a page: the person's own browser
    ("baixe https://example.com/a.csv como dados.csv", Route.COMPUTER),
])
def test_an_address_with_something_to_do_goes_to_the_browser_agent(text, route):
    assert HeuristicGate().classify(text).route is route


# Every request of the 24-request bench must reach the computer through the real gate (the bench itself skips the gate)
BENCH_COMPUTER = [
    "crie um arquivo lista2.txt com leite e pão", "crie a pasta projetos", "crie a pasta projetos e dentro dela um arquivo notas.txt com olá", "copie a lista.txt para lista_copia.txt",
    "crie notas.txt com oi e copie para notas2.txt", "mande o rascunho para a lixeira", "mande a lista para a lixeira", "edite a lista trocando leite por café", "abre o Spotify",
    "abre o Photoshop", "apague o arquivo naoexiste.txt", "mova a lista.txt para a pasta arquivos", "crie a pasta arquivos e mova a lista.txt para lá", "mostre o conteúdo da lista.txt",
    "liste os arquivos", "crie um arquivo .bashrc", "baixe https://example.com/a.csv como dados.csv", "renomeie o relatorio.txt para relatorio_final.txt", "apague tudo",
    "faça uma cópia do rascunho", "copie ideias/Rascunho.md para ideias/copia.md", "crie as pastas a, b e c", "edite o arquivo",
]


@pytest.mark.parametrize("text", BENCH_COMPUTER)
def test_the_requests_of_the_bench_reach_the_computer_through_the_gate(text):
    assert HeuristicGate().classify(text).route is Route.COMPUTER, text


async def test_clicking_login_before_the_password_is_filled_is_refused(tmp_path):
    session = LoginSession()
    llm = LLM('{"action":"click","id":3}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, session, None))
    assert "falta preencher a senha" in llm.prompts[1]


async def test_clicking_login_after_the_password_is_fine(tmp_path):
    clicks = []

    class S(LoginSession):
        async def click(self, ident): clicks.append(ident)

    async def ask(job_id, key, question, secret): return "x"
    llm = LLM(ASK_PASS, '{"action":"type","id":2,"from":"senha"}', '{"action":"click","id":3}', '{"action":"done","answer":"ok"}')
    await run(agent(llm, tmp_path, S(), ask))
    assert clicks == [3]


async def test_success_is_never_reported_when_the_page_says_the_login_failed(tmp_path):
    class Failed(LoginSession):
        async def snapshot(self): return Snapshot(self.url, "Login", "Your password is invalid! Username Password Login", LOGIN)

    async def ask(job_id, key, question, secret): return "x"
    llm = LLM(ASK_PASS, '{"action":"type","id":2,"from":"senha","enter":true}', '{"action":"done","answer":"O login foi realizado com sucesso"}')
    out = await run(agent(llm, tmp_path, Failed(), ask))
    assert out[0].startswith("Não consegui entrar") and "invalid" in out[0] and "sucesso" not in out[0]


async def test_a_task_without_a_login_is_not_second_guessed(tmp_path):
    class Page(LoginSession):
        async def snapshot(self): return Snapshot(self.url, "Erro 404", "Página não encontrada, tente novamente", [])
    out = await run(agent(LLM('{"action":"done","answer":"a página não existe"}'), tmp_path, Page(), None), "abra https://example.org/x e me diga")
    assert out == ["a página não existe"]


async def test_finishing_before_sending_the_form_is_sent_back_once(tmp_path):
    clicks = []

    class S(LoginSession):
        async def click(self, ident): clicks.append(ident)

    async def ask(job_id, key, question, secret): return "x"
    llm = LLM(ASK_PASS, '{"action":"type","id":2,"from":"senha"}', '{"action":"done","answer":"entrei"}', '{"action":"click","id":3}', '{"action":"done","answer":"enviei"}')
    out = await run(agent(llm, tmp_path, S(), ask))
    assert out == ["enviei"] and clicks == [3] and "did not send the form" in llm.prompts[3]


@pytest.mark.parametrize("text,failed", [
    ("Your password is invalid! Username Password Login", True),
    ("Senha incorreta. Tente novamente.", True),
    ("O usuário informado não foi encontrado", True),
    ("Login Page. This is where you can log into the secure area. If the information is wrong you should see error messages.", False),
    ("Welcome to the Secure Area. Logout", False),
])
def test_what_counts_as_the_page_saying_the_login_failed(text, failed):
    from chakmati.browser.agent import _FAILED
    assert bool(_FAILED.search(text)) is failed


# ------------------------------------------------------------------------------------------------ the login action
class FormSession(LoginSession):
    def __init__(self):
        super().__init__()
        self.clicks = []

    async def click(self, ident): self.clicks.append(ident)


async def test_the_login_action_asks_fills_both_fields_and_sends_the_form(tmp_path):
    asked, session = [], FormSession()

    async def ask(job_id, key, question, secret):
        asked.append((key, secret))
        return {"usuario": "gregory.v", "senha": "s3gredo!"}[key]
    llm = LLM('{"action":"login"}', '{"action":"done","answer":"entrei"}')
    frames = FrameStore(tmp_path)
    out = await run(BrowserAgent(llm, frames, lambda: session, ask=ask))
    assert out == ["entrei"] and asked == [("usuario", False), ("senha", True)]
    assert session.typed == [(1, "gregory.v", False, False), (2, "s3gredo!", False, True)] and session.clicks == [3]
    notes = [f["note"] for f in frames.list(JOB)]
    assert "Preenchendo o usuário" in notes and "Preenchendo a senha" in notes and "Entrando" in notes
    assert "s3gredo!" not in json.dumps(llm.prompts) + json.dumps(notes) and "gregory.v" not in json.dumps(llm.prompts)


async def test_the_login_action_on_a_page_without_a_password_field_is_refused(tmp_path):
    class Plain(FormSession):
        async def snapshot(self): return Snapshot(self.url, "Início", "Olá", [LOGIN[3]])
    llm = LLM('{"action":"login"}', '{"action":"done","answer":"x"}')
    await run(agent(llm, tmp_path, Plain(), None))
    assert "no password field" in llm.prompts[1]


async def test_a_login_with_nobody_to_ask_says_so(tmp_path):
    out = await run(agent(LLM('{"action":"login"}'), tmp_path, FormSession(), None))
    assert "consigo perguntar" in out[0]


async def test_the_login_action_reuses_what_the_model_already_asked(tmp_path):
    asked, session = [], FormSession()

    async def ask(job_id, key, question, secret):
        asked.append(key)
        return {"username": "gregory.v", "senha": "s3gredo!"}[key]
    llm = LLM('{"action":"ask","key":"username","question":"Qual é o seu usuário?"}', '{"action":"login"}', '{"action":"done","answer":"entrei"}')
    await run(agent(llm, tmp_path, session, ask))
    assert asked == ["username", "senha"]                       # the user name was not asked a second time
    assert session.typed[0] == (1, "gregory.v", False, False)


def test_the_plan_of_a_browser_task_warns_that_it_can_make_mistakes():
    plan = BrowserAgent(LLM(), None, None).plan("pesquise o protocolo MCP")
    assert plan[-1].startswith("Atenção: posso cometer erros ao navegar") and "enviar, comprar ou apagar" in plan[-1]


def test_stopping_a_job_over_the_api(tmp_path):
    import time
    store, frames, broker = JobStore(":memory:"), FrameStore(tmp_path), InputBroker(timeout=30)
    llm = LLM(ASK_PASS)
    engine = Engine(OneGate(), llm, store, browser_agent=BrowserAgent(llm, frames, lambda: LoginSession(), ask=broker.ask))
    worker = Worker(store, engine.run_job, stream_handler=engine.run_job_stream)
    client = TestClient(create_app(engine, store, worker, frames=frames, inputs=broker))
    events = []
    with client:
        with client.stream("POST", "/message/stream", json={"text": "acesse meu instagram"}) as r:
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                events.append(event)
                if event["type"] == "input":   # the agent is waiting for a password: the person presses Parar instead
                    assert client.post(f"/jobs/{event['job_id']}/cancel").status_code == 403            # only the app's own window
                    stop = client.post(f"/jobs/{event['job_id']}/cancel", headers={"X-LiteAgent-UI": "1"})
                    assert stop.status_code == 200 and stop.json() == {"ok": True}
    assert events[-1] == {"type": "cancelled", "text": "Interrompido por você."}
    assert client.post("/jobs/" + "0" * 32 + "/cancel", headers={"X-LiteAgent-UI": "1"}).status_code == 404


async def test_a_confirmation_has_no_text_to_type():
    broker = InputBroker(timeout=2)
    waiting = asyncio.create_task(broker.ask(JOB, "verificacao", "Resolva a verificação", False, True))
    await asyncio.sleep(0.01)
    assert broker.pending(JOB).confirm is True
    assert broker.answer(JOB, broker.pending(JOB).id, "ok") and await waiting == "ok"
