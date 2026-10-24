from liteagent.config import Settings
from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore
from liteagent.main import build_app
from liteagent.research.tool import ResearchAnswer


class FakeGate:
    def __init__(self, route):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return "plain llm answer"


class FakeResearcher:
    def __init__(self):
        self.queries = []

    async def answer(self, query, today=None, now=None):
        self.queries.append(query)
        return ResearchAnswer("web answer", ["https://a.test"])


async def test_research_job_uses_researcher_and_renders_sources():
    store, llm, researcher = JobStore(":memory:"), FakeLLM(), FakeResearcher()
    engine = Engine(FakeGate(Route.RESEARCH), llm, store, researcher=researcher)
    reply = await engine.handle("pesquise X")
    assert await engine.run_job(store.get(reply.job_id)) == "web answer\n\nFontes:\n- https://a.test"
    assert researcher.queries == ["pesquise X"]
    assert llm.calls == []


async def test_task_job_ignores_researcher():
    store, llm, researcher = JobStore(":memory:"), FakeLLM(), FakeResearcher()
    engine = Engine(FakeGate(Route.TASK), llm, store, researcher=researcher)
    reply = await engine.handle("crie um script")
    assert await engine.run_job(store.get(reply.job_id)) == "plain llm answer"
    assert researcher.queries == []


def test_build_app_wires_researcher_only_when_enabled(monkeypatch):
    captured = {}
    real_init = Engine.__init__

    def spy(self, *args, **kwargs):
        captured["researcher"] = kwargs.get("researcher")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg"))
    assert captured["researcher"] is not None
    build_app(Settings(db_path=":memory:"))
    assert captured["researcher"] is None


def test_build_app_research_scorer_selection(monkeypatch):
    from liteagent.loop.scorer import KeepAllScorer
    from liteagent.loop.twostage import LayaRelevanceScorer
    from liteagent.research import tool as tool_module

    captured = []
    real_init = tool_module.ResearchTool.__init__

    def spy(self, search, fetcher, llm, scorer, **kwargs):
        captured.append(scorer)
        real_init(self, search, fetcher, llm, scorer, **kwargs)

    monkeypatch.setattr(tool_module.ResearchTool, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg"))
    build_app(Settings(db_path=":memory:", research_backend="ddg", research_scorer="laya"))
    assert isinstance(captured[0], KeepAllScorer)
    assert isinstance(captured[1], LayaRelevanceScorer)


def test_build_app_selects_search_backend(monkeypatch):
    from liteagent.research import tool as tool_module
    from liteagent.research.search import DuckDuckGoHtmlBackend
    from liteagent.research.searxng import SearxngBackend

    captured = []
    real_init = tool_module.ResearchTool.__init__

    def spy(self, search, *args, **kwargs):
        captured.append(search)
        real_init(self, search, *args, **kwargs)

    monkeypatch.setattr(tool_module.ResearchTool, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg"))
    build_app(Settings(db_path=":memory:", research_backend="searxng", searxng_url="http://searx.test:8080"))
    assert isinstance(captured[0], DuckDuckGoHtmlBackend)
    assert isinstance(captured[1], SearxngBackend)
    assert captured[1]._base == "http://searx.test:8080"


def test_build_app_applies_speed_settings_to_the_research_client(monkeypatch):
    from liteagent.research import tool as tool_module

    captured = {}
    real_init = tool_module.ResearchTool.__init__

    def spy(self, search, fetcher, llm, scorer, **kwargs):
        captured["llm"], captured["kwargs"] = llm, kwargs
        real_init(self, search, fetcher, llm, scorer, **kwargs)

    monkeypatch.setattr(tool_module.ResearchTool, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg", research_max_tokens=150,
                       keep_alive="20m", research_concise=True))
    assert captured["llm"]._num_predict == 150 and captured["llm"]._keep_alive == "20m"
    assert captured["kwargs"]["concise"] is True


def test_build_app_passes_the_fetch_deadline_and_zero_means_none(monkeypatch):
    from liteagent.research import tool as tool_module

    seen = []
    real_init = tool_module.ResearchTool.__init__

    def spy(self, search, fetcher, llm, scorer, **kwargs):
        seen.append(kwargs.get("fetch_deadline"))
        real_init(self, search, fetcher, llm, scorer, **kwargs)

    monkeypatch.setattr(tool_module.ResearchTool, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg", fetch_deadline=2.5))
    build_app(Settings(db_path=":memory:", research_backend="ddg", fetch_deadline=0.0))
    assert seen == [2.5, None]


def test_build_app_passes_max_pages(monkeypatch):
    from liteagent.research import tool as tool_module

    seen = []
    real_init = tool_module.ResearchTool.__init__

    def spy(self, search, fetcher, llm, scorer, **kwargs):
        seen.append(kwargs.get("max_pages"))
        real_init(self, search, fetcher, llm, scorer, **kwargs)

    monkeypatch.setattr(tool_module.ResearchTool, "__init__", spy)
    build_app(Settings(db_path=":memory:", research_backend="ddg", research_max_pages=2))
    assert seen == [2]
