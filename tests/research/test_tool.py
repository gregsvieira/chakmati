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
