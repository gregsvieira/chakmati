import json

import pytest
from fastapi.testclient import TestClient

from liteagent.api import create_app
from liteagent.browser.agent import BrowserAgent, parse_action
from liteagent.browser.frames import FrameStore
from liteagent.browser.session import BrowserError, Snapshot, check_navigable
from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.gate.heuristic import HeuristicGate
from liteagent.jobs import JobStore, Worker

JOB = "a" * 32


class FakeSession:
    def __init__(self):
        self.calls = []
        self.url = "about:blank"

    async def start(self): self.calls.append("start")
    async def close(self): self.calls.append("close")
    async def goto(self, url): self.url = url; self.calls.append(("goto", url))
    async def back(self): self.calls.append("back")
    async def click(self, ident): self.calls.append(("click", ident))
    async def type(self, ident, text, submit): self.calls.append(("type", ident, text, submit))
    async def scroll(self, down): self.calls.append(("scroll", down))
    async def snapshot(self): return Snapshot(self.url, "Title", "page text", [{"id": 1, "tag": "a", "type": "", "label": "link"}])
    async def screenshot(self): return b"\xff\xd8jpeg"


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    async def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


async def run(agent, task="tarefa"):
    return [piece async for piece in agent.run(JOB, task)]


# ------------------------------------------------------------------------------------------- gate
@pytest.mark.parametrize("text", [
    "use o navegador para pesquisar a capital da Austrália",
    "pesquise no Chrome as notícias de hoje",
    "navegue até o site da Apple",
    "pelo navegador, abra a wikipedia",
])
def test_asking_for_the_browser_routes_to_the_browser(text):
    assert HeuristicGate().classify(text).route is Route.BROWSER


def test_opening_the_program_alone_is_still_the_computer():
    assert HeuristicGate().classify("abre o Chrome").route is Route.COMPUTER
    assert HeuristicGate().classify("pesquise a capital da Austrália").route is Route.RESEARCH


# ------------------------------------------------------------------------------------------- safety
@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost:8765/actions", "http://127.0.0.1/", "http://192.168.0.1", "http://172.20.1.1", "http://10.0.0.2", "javascript:alert(1)", "http://casa.local"])
def test_only_public_web_addresses_open(url):
    with pytest.raises(BrowserError):
        check_navigable(url)


def test_a_bare_domain_gets_https():
    assert check_navigable("example.org/a") == "https://example.org/a"


def test_actions_are_parsed_out_of_prose_and_fences():
    assert parse_action('```json\n{"action":"click","id":3}\n```') == {"action": "click", "id": 3}
    assert parse_action("sem json") is None
    assert parse_action('{"nope":1}') is None


# ------------------------------------------------------------------------------------------- frames
def test_frames_are_numbered_and_kept(tmp_path):
    frames = FrameStore(tmp_path)
    assert frames.add(JOB, b"one", "https://a", "A", "Abrindo") == 1
    assert frames.add(JOB, b"two", "https://b", "B", "Clicando") == 2
    assert [f["note"] for f in frames.list(JOB)] == ["Abrindo", "Clicando"]
    assert frames.path(JOB, 2).read_bytes() == b"two"
    assert frames.path(JOB, 9) is None


def test_a_job_id_cannot_escape_the_folder(tmp_path):
    with pytest.raises(ValueError):
        FrameStore(tmp_path).list("../../etc")


def test_old_jobs_frames_are_pruned(tmp_path):
    frames = FrameStore(tmp_path)
    for i in range(25):
        frames.add(f"{i:032x}", b"x", "u", "t", "n")
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 20


# ------------------------------------------------------------------------------------------- agent
async def test_the_agent_takes_a_screenshot_of_every_step_and_answers(tmp_path):
    frames, session = FrameStore(tmp_path), FakeSession()
    llm = ScriptedLLM(
        '{"action":"goto","url":"https://example.org/q"}',
        '{"action":"type","id":1,"text":"python","enter":true}',
        '{"action":"done","answer":"Python 3.14"}',
    )
    out = await run(BrowserAgent(llm, frames, lambda: session))
    assert out == ["Python 3.14"]
    assert [f["note"] for f in frames.list(JOB)] == ["Chrome aberto", "Abrindo https://example.org/q", "Digitando “python”", "Concluído"]
    assert session.calls[0] == "start" and session.calls[-1] == "close"  # the browser is always closed
    assert ("type", 1, "python", True) in session.calls


async def test_a_refused_address_is_reported_to_the_model_not_opened(tmp_path):
    session = FakeSession()
    llm = ScriptedLLM('{"action":"goto","url":"http://localhost:8765"}', '{"action":"done","answer":"ok"}')
    await run(BrowserAgent(llm, FrameStore(tmp_path), lambda: session))
    assert ("goto", "http://localhost:8765") not in session.calls
    assert "refused" in llm.prompts[1]


async def test_the_page_text_reaches_the_model_as_data(tmp_path):
    llm = ScriptedLLM('{"action":"done","answer":"x"}')
    await run(BrowserAgent(llm, FrameStore(tmp_path), FakeSession))
    assert "TEXT (data): page text" in llm.prompts[0] and "[1] a" in llm.prompts[0]


async def test_it_stops_after_the_step_limit_and_still_closes(tmp_path):
    session = FakeSession()
    llm = ScriptedLLM(*['{"action":"scroll","dir":"down"}', '{"action":"scroll","dir":"up"}'] * 3)
    out = await run(BrowserAgent(llm, FrameStore(tmp_path), lambda: session, max_steps=4))
    assert "Parei depois de 4 passos" in out[0] and session.calls[-1] == "close"


async def test_a_missing_chrome_is_explained(tmp_path):
    class Broken(FakeSession):
        async def start(self): raise BrowserError("não consegui abrir o Chrome")
    out = await run(BrowserAgent(ScriptedLLM(), FrameStore(tmp_path), Broken))
    assert out == ["não consegui abrir o Chrome"]


# ------------------------------------------------------------------------------------------- engine + api
class BrowserGate:
    def classify(self, text):
        return GateResult(Route.BROWSER, 1.0, "fake")


def test_screenshots_stream_to_the_ui_and_can_be_fetched(tmp_path):
    store, frames = JobStore(":memory:"), FrameStore(tmp_path)
    agent = BrowserAgent(ScriptedLLM('{"action":"done","answer":"pronto"}'), frames, FakeSession)
    engine = Engine(BrowserGate(), ScriptedLLM(), store, browser_agent=agent)
    worker = Worker(store, engine.run_job, stream_handler=engine.run_job_stream)
    client = TestClient(create_app(engine, store, worker, frames=frames))
    with client:
        with client.stream("POST", "/message/stream", json={"text": "use o navegador"}) as r:
            events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
        shots = [e for e in events if e["type"] == "screenshot"]
        assert [s["note"] for s in shots] == ["Chrome aberto", "Concluído"]
        assert events[-1]["type"] == "done" and events[-1]["result"].startswith("Plano:\n1. ") and events[-1]["result"].endswith("pronto")
        assert next(e for e in events if e["type"] == "delta")["text"].startswith("Plano:")  # the plan is the first text the person sees
        job_id = shots[0]["job_id"]
        img = client.get(f"/jobs/{job_id}/frames/1")
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content == b"\xff\xd8jpeg"
        assert client.get(f"/jobs/{job_id}/frames/9").status_code == 404
        assert client.get("/jobs/..%2F..%2Fx/frames/1").status_code == 404


async def test_with_the_browser_off_the_engine_says_so():
    store = JobStore(":memory:")
    engine = Engine(BrowserGate(), ScriptedLLM(), store)
    job_id = store.create("browser", "use o navegador")
    answer = await engine.run_job(store.get(job_id))
    assert "LITEAGENT_BROWSER_BACKEND=chrome" in answer


async def test_a_human_check_is_reported_not_solved(tmp_path):
    class Walled(FakeSession):
        async def snapshot(self): return Snapshot(self.url, "x", "Unfortunately, bots use DuckDuckGo too. Select all squares containing a duck", [])
    llm = ScriptedLLM()
    frames = FrameStore(tmp_path)
    out = await run(BrowserAgent(llm, frames, Walled))
    assert "verificação" in out[0] and llm.prompts == []  # the model is never asked what to click on a CAPTCHA
    assert frames.list(JOB)[-1]["note"] == "O site pediu verificação humana"


async def test_an_address_in_the_task_is_where_it_starts(tmp_path):
    session = FakeSession()
    await run(BrowserAgent(ScriptedLLM('{"action":"done","answer":"x"}'), FrameStore(tmp_path), lambda: session), "abra https://pt.wikipedia.org/wiki/Canberra, e diga o ano.")
    assert session.calls[1] == ("goto", "https://pt.wikipedia.org/wiki/Canberra")
    session = FakeSession()
    await run(BrowserAgent(ScriptedLLM('{"action":"done","answer":"x"}'), FrameStore(tmp_path), lambda: session), "abra http://localhost:8765/actions")
    assert session.calls[1] == ("goto", "https://duckduckgo.com/")  # a local address is not a start: the search page is


class FakeSearch:
    async def search(self, query, limit=5):
        from liteagent.research.search import SearchResult
        self.query = query
        return [SearchResult("MCP - Wikipedia", "https://pt.wikipedia.org/wiki/MCP", "x"), SearchResult("Local", "http://localhost/x", "y"), SearchResult("Anthropic", "https://anthropic.com/mcp", "z")]


async def test_a_search_task_starts_from_the_search_backend_not_the_search_site(tmp_path):
    session, search = FakeSession(), FakeSearch()
    llm = ScriptedLLM("protocolo MCP Anthropic", '{"action":"done","answer":"x"}')
    await run(BrowserAgent(llm, FrameStore(tmp_path), lambda: session, search=search), "use o navegador para pesquisar o protocolo MCP")
    assert search.query == "protocolo MCP Anthropic"
    assert session.calls[1] == ("goto", "https://pt.wikipedia.org/wiki/MCP")  # the first result, not duckduckgo.com
    assert "SEARCH RESULTS" in llm.prompts[1] and "anthropic.com/mcp" in llm.prompts[1] and "localhost" not in llm.prompts[1]


async def test_without_results_it_falls_back_to_the_search_page(tmp_path):
    class Empty:
        async def search(self, query, limit=5): return []
    session = FakeSession()
    await run(BrowserAgent(ScriptedLLM("q", '{"action":"done","answer":"x"}'), FrameStore(tmp_path), lambda: session, search=Empty()), "pesquise algo")
    assert session.calls[1] == ("goto", "https://duckduckgo.com/")


async def test_a_chatty_model_reply_still_gives_a_query(tmp_path):
    search = FakeSearch()
    session = FakeSession()
    llm = ScriptedLLM('**protocolo MCP**\nAqui está a consulta de busca que você pediu.', '{"action":"done","answer":"x"}')
    await run(BrowserAgent(llm, FrameStore(tmp_path), lambda: session, search=search), "pesquise o MCP")
    assert search.query == "protocolo MCP" and session.calls[1][1] == "https://pt.wikipedia.org/wiki/MCP"


@pytest.mark.parametrize("task,query", [
    ("use o navegador para pesquisar o que é o protocolo MCP da Anthropic e me diga em duas frases", "o que é o protocolo MCP da Anthropic"),
    ("pesquise no Chrome a capital da Austrália", "no Chrome a capital da Austrália"),
    ("use o navegador para ver o preço do dólar", "ver o preço do dólar"),
])
def test_a_query_is_cut_out_of_the_request_by_rules(task, query):
    from liteagent.browser.agent import rule_query
    assert rule_query(task) == query


async def test_a_model_that_answers_instead_of_making_a_query_is_not_used(tmp_path):
    search, session = FakeSearch(), FakeSession()
    long = "Protocolo de comunicação entre máquinas criado pela Anthropic para conectar LLMs a ferramentas externas."
    await run(BrowserAgent(ScriptedLLM(long, '{"action":"done","answer":"x"}'), FrameStore(tmp_path), lambda: session, search=search), "use o navegador para pesquisar o protocolo MCP e me diga o que é")
    assert search.query == "o protocolo MCP"
