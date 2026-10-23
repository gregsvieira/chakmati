import httpx

from liteagent.research.fetch import PageFetcher
from liteagent.research.search import SearchResult
from liteagent.research.tool import COMPOSE_SYSTEM, ResearchAnswer, ResearchTool

PAGE = """<html><body><article><p>{text}</p><p>Mais detalhes importantes sobre o assunto aparecem
neste segundo parágrafo, com informação suficiente para ser extraída.</p></article></body></html>"""


class FakeSearch:
    def __init__(self, results):
        self.results, self.queries = results, []

    async def search(self, query, limit=10):
        self.queries.append((query, limit))
        return self.results


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return "Resposta [1]."


class ByLength:
    """Longer text -> higher score (just needs to be deterministic)."""

    def score(self, question, parts):
        return [min(len(p) / 1000, 1.0) for p in parts]


def pages(mapping):
    def handler(request: httpx.Request) -> httpx.Response:
        body = mapping.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    return PageFetcher(transport=httpx.MockTransport(handler))


async def test_answer_uses_fetched_passages_and_lists_sources():
    results = [
        SearchResult("A", "https://a.test/1", "snippet a"),
        SearchResult("B", "https://b.test/2", "snippet b"),
    ]
    mapping = {
        "https://a.test/1": PAGE.format(text="O Python 3.13 é a versão estável mais recente da linguagem."),
        "https://b.test/2": PAGE.format(text="Outra fonte confirma que a versão atual é a 3.13."),
    }
    llm = FakeLLM()
    tool = ResearchTool(FakeSearch(results), pages(mapping), llm, ByLength(), result_cutoff=0.0)
    out = await tool.answer("versão atual do python")

    assert out.answer == "Resposta [1]."
    assert set(out.sources) == {"https://a.test/1", "https://b.test/2"}
    system, user = llm.calls[0]
    assert system["content"] == COMPOSE_SYSTEM
    assert "[1]" in user["content"] and "versão atual do python" in user["content"]
    assert "3.13" in user["content"]


async def test_no_search_results_skips_the_llm():
    llm = FakeLLM()
    out = await ResearchTool(FakeSearch([]), pages({}), llm, ByLength()).answer("q")
    assert out.sources == [] and "Não encontrei" in out.answer
    assert llm.calls == []


async def test_all_pages_fail_skips_the_llm():
    results = [SearchResult("A", "https://a.test/1", "s")]
    llm = FakeLLM()
    out = await ResearchTool(FakeSearch(results), pages({}), llm, ByLength(), result_cutoff=0.0).answer("q")
    assert "Não encontrei" in out.answer and llm.calls == []


async def test_only_max_pages_are_fetched():
    results = [SearchResult(f"T{i}", f"https://s.test/{i}", "x") for i in range(6)]
    mapping = {f"https://s.test/{i}": PAGE.format(text=f"conteúdo {i} " * 20) for i in range(6)}
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        return httpx.Response(200, text=mapping[str(request.url)], headers={"content-type": "text/html"})

    fetcher = PageFetcher(transport=httpx.MockTransport(handler))
    tool = ResearchTool(FakeSearch(results), fetcher, FakeLLM(), ByLength(), max_pages=2, result_cutoff=0.0)
    await tool.answer("q")
    assert len(fetched) == 2


def test_render_appends_sources():
    assert ResearchAnswer("ok", ["https://a", "https://b"]).render() == "ok\n\nFontes:\n- https://a\n- https://b"
    assert ResearchAnswer("ok", []).render() == "ok"


async def test_concise_flag_appends_the_brevity_instruction_only_when_enabled():
    from liteagent.research.tool import CONCISE_SUFFIX

    results = [SearchResult("A", "https://a.test/1", "s")]
    mapping = {"https://a.test/1": PAGE.format(text="Texto suficiente para ser extraído da página de teste.")}
    llm = FakeLLM()
    await ResearchTool(FakeSearch(results), pages(mapping), llm, ByLength(), result_cutoff=0.0, concise=True).answer("q")
    assert llm.calls[0][0]["content"] == COMPOSE_SYSTEM + CONCISE_SUFFIX
    llm2 = FakeLLM()
    await ResearchTool(FakeSearch(results), pages(mapping), llm2, ByLength(), result_cutoff=0.0).answer("q")
    assert llm2.calls[0][0]["content"] == COMPOSE_SYSTEM


class StreamLLM:
    def __init__(self, deltas):
        self.deltas, self.calls = deltas, []

    async def chat(self, messages):
        raise AssertionError("stream_answer must not call chat()")

    async def stream_chat(self, messages):
        self.calls.append(messages)
        for d in self.deltas:
            yield d


async def test_stream_answer_yields_deltas_then_sources():
    results = [SearchResult("A", "https://a.test/1", "s")]
    mapping = {"https://a.test/1": PAGE.format(text="O Python 3.13 é a versão estável mais recente da linguagem.")}
    llm = StreamLLM(["Python ", "3.13 [1]."])
    tool = ResearchTool(FakeSearch(results), pages(mapping), llm, ByLength(), result_cutoff=0.0)
    out = [d async for d in tool.stream_answer("versão do python")]
    assert out[:2] == ["Python ", "3.13 [1]."]
    assert "".join(out[2:]) == "\n\nFontes:\n- https://a.test/1"
    assert llm.calls[0][0]["content"] == COMPOSE_SYSTEM


async def test_stream_answer_without_usable_pages_yields_the_notice_and_skips_the_llm():
    llm = StreamLLM(["x"])
    out = [d async for d in ResearchTool(FakeSearch([]), pages({}), llm, ByLength()).stream_answer("q")]
    assert out == ["Não encontrei informações utilizáveis na web para esta pergunta."]
    assert llm.calls == []


import asyncio as _asyncio
import time as _time


class DelayedFetcher:
    """Serves bodies after a per-url delay, so one slow site can be simulated."""

    def __init__(self, table):
        self.table, self.cancelled = table, []

    async def fetch(self, url):
        delay, body = self.table[url]
        try:
            await _asyncio.sleep(delay)
        except _asyncio.CancelledError:
            self.cancelled.append(url)
            raise
        return body


def _slow_site_setup():
    results = [
        SearchResult("Fast", "https://fast.test/1", "s"),
        SearchResult("Slow", "https://slow.test/2", "s"),
    ]
    table = {
        "https://fast.test/1": (0.0, PAGE.format(text="Informação relevante da página rápida, bem longa o bastante.")),
        "https://slow.test/2": (5.0, PAGE.format(text="Informação da página lenta que nunca deveria ser esperada.")),
    }
    return results, table


async def test_fetch_deadline_drops_a_page_that_hangs_and_does_not_wait_for_it():
    results, table = _slow_site_setup()
    fetcher = DelayedFetcher(table)
    llm = FakeLLM()
    tool = ResearchTool(FakeSearch(results), fetcher, llm, ByLength(), result_cutoff=0.0, fetch_deadline=0.3)
    started = _time.perf_counter()
    out = await tool.answer("q")
    assert _time.perf_counter() - started < 2.0  # did not wait the 5 s
    assert out.sources == ["https://fast.test/1"]
    assert fetcher.cancelled == ["https://slow.test/2"]  # the hanging download was cancelled


async def test_without_a_deadline_all_pages_are_awaited():
    results, table = _slow_site_setup()
    table["https://slow.test/2"] = (0.2, table["https://slow.test/2"][1])
    tool = ResearchTool(FakeSearch(results), DelayedFetcher(table), FakeLLM(), ByLength(), result_cutoff=0.0)
    out = await tool.answer("q")
    assert set(out.sources) == {"https://fast.test/1", "https://slow.test/2"}


async def test_stream_answer_also_honours_the_fetch_deadline():
    results, table = _slow_site_setup()
    llm = StreamLLM(["ok"])
    tool = ResearchTool(FakeSearch(results), DelayedFetcher(table), llm, ByLength(), result_cutoff=0.0, fetch_deadline=0.3)
    started = _time.perf_counter()
    out = [d async for d in tool.stream_answer("q")]
    assert _time.perf_counter() - started < 2.0 and out[0] == "ok"
    assert "slow.test" not in "".join(out)


class TimedFetcher:
    """Each url -> (delay, body or None). Records which downloads were cancelled."""

    def __init__(self, table):
        self.table, self.cancelled = table, []

    async def fetch(self, url):
        delay, body = self.table[url]
        try:
            await _asyncio.sleep(delay)
        except _asyncio.CancelledError:
            self.cancelled.append(url)
            raise
        return body


def _four_sites():
    results = [SearchResult(f"T{i}", f"https://s.test/{i}", "x") for i in range(4)]
    good = lambda n: PAGE.format(text=f"Conteúdo útil número {n} da página, longo o bastante para extração.")  # noqa: E731
    return results, good


async def test_target_pages_stops_waiting_once_enough_pages_succeeded():
    results, good = _four_sites()
    table = {
        "https://s.test/0": (0.4, None),          # fails (after a while)
        "https://s.test/1": (0.05, good(1)),      # succeeds fast
        "https://s.test/2": (0.1, good(2)),       # succeeds fast  -> target of 2 reached here
        "https://s.test/3": (5.0, good(3)),       # slow: must be cancelled, not awaited
    }
    fetcher = TimedFetcher(table)
    tool = ResearchTool(FakeSearch(results), fetcher, FakeLLM(), ByLength(), result_cutoff=0.0, target_pages=2)
    started = _time.perf_counter()
    out = await tool.answer("q")
    assert _time.perf_counter() - started < 2.0
    assert set(out.sources) == {"https://s.test/1", "https://s.test/2"}
    assert "https://s.test/3" in fetcher.cancelled


async def test_target_pages_falls_back_to_whatever_arrived_if_the_target_is_not_reached():
    results, good = _four_sites()
    table = {f"https://s.test/{i}": (0.0, None) for i in range(4)}
    table["https://s.test/2"] = (0.0, good(2))
    tool = ResearchTool(FakeSearch(results), TimedFetcher(table), FakeLLM(), ByLength(), result_cutoff=0.0, target_pages=2)
    out = await tool.answer("q")
    assert out.sources == ["https://s.test/2"]
