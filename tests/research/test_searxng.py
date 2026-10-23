from urllib.parse import parse_qs

import httpx
import pytest

from liteagent.research.search import SearchResult
from liteagent.research.searxng import USER_AGENT, SearxngBackend, SearxngUnavailable, parse_searxng_html

HTML = """
<div id="urls">
  <article class="result result-default category-general">
    <a href="https://www.python.org/downloads/" class="url_header" rel="noreferrer">
      <div class="url_wrapper"><span class="url_o1">python.org</span></div></a>
    <h3><a href="https://www.python.org/downloads/">Download Python</a></h3>
    <p class="content">The official home of <b>Python</b>.</p>
  </article>
  <article class="result result-default">
    <a href="https://example.com/x" class="url_header"></a>
  </article>
  <article class="result result-default">
    <h3><a href="https://nolink.test">No url header here</a></h3>
  </article>
</div>
"""


class Recorder:
    """MockTransport handler that records requests and serves scripted responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def backend(rec, sleeps=None, **kw):
    async def fake_sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return SearxngBackend(
        "http://searx.test", transport=httpx.MockTransport(rec), sleep=fake_sleep, **kw
    )


def test_parse_html_matches_agenticseek_defaults():
    assert parse_searxng_html(HTML) == [
        SearchResult("Download Python", "https://www.python.org/downloads/", "The official home of Python."),
        SearchResult("No Title", "https://example.com/x", "No Description"),
    ]


def test_parse_html_empty_and_garbage():
    assert parse_searxng_html("") == []
    assert parse_searxng_html("<html><body>nothing</body></html>") == []


async def test_request_shape_is_the_same_as_agenticseek():
    rec = Recorder(httpx.Response(200, text=HTML))
    results = await backend(rec).search("capital da Austrália")
    assert len(results) == 2
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == "http://searx.test/search"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert req.headers["user-agent"] == USER_AGENT
    assert req.headers["accept-language"] == "en-US,en;q=0.9"
    assert req.headers["cache-control"] == "no-cache" and req.headers["pragma"] == "no-cache"
    form = parse_qs(req.content.decode(), keep_blank_values=True)
    assert form == {
        "q": ["capital da Austrália"],
        "categories": ["general"],
        "language": ["auto"],
        "time_range": [""],
        "safesearch": ["0"],
        "theme": ["simple"],
    }


async def test_falls_back_to_json_api_when_html_has_no_results():
    json_body = {
        "results": [
            {"title": "T1", "content": "C1", "url": "https://a.test"},
            {"url": "https://b.test"},  # missing title/content -> defaults
        ]
        + [{"title": f"x{i}", "content": "c", "url": f"https://x.test/{i}"} for i in range(30)]
    }
    rec = Recorder(httpx.Response(200, text="<html></html>"), httpx.Response(200, json=json_body))
    results = await backend(rec).search("q", limit=50)
    assert [r.url for r in results][:2] == ["https://a.test", "https://b.test"]
    assert results[1] == SearchResult("No Title", "https://b.test", "No Description")
    assert len(results) == 20  # agenticSeek keeps the first 20 JSON results
    get = rec.requests[1]
    assert get.method == "GET" and get.url.path == "/search"
    params = dict(get.url.params)
    assert params == {
        "q": "q", "format": "json", "categories": "general", "language": "auto", "safesearch": "0",
    }
    assert get.headers["accept"] == "application/json"


async def test_limit_is_applied():
    rec = Recorder(httpx.Response(200, text=HTML))
    assert len(await backend(rec).search("q", limit=1)) == 1


async def test_retries_with_linear_backoff_then_succeeds():
    rec = Recorder(httpx.ConnectError("down"), httpx.Response(200, text=HTML))
    sleeps: list[float] = []
    results = await backend(rec, sleeps).search("q")
    assert len(results) == 2 and sleeps == [1.0]


async def test_raises_unavailable_after_three_failed_attempts():
    rec = Recorder(httpx.ConnectError("a"), httpx.ConnectError("b"), httpx.ConnectError("c"))
    sleeps: list[float] = []
    with pytest.raises(SearxngUnavailable, match="SearxNG unavailable"):
        await backend(rec, sleeps).search("q")
    assert sleeps == [1.0, 2.0] and len(rec.requests) == 3


async def test_http_error_status_counts_as_a_failed_attempt():
    rec = Recorder(httpx.Response(500), httpx.Response(200, text=HTML))
    sleeps: list[float] = []
    assert len(await backend(rec, sleeps).search("q")) == 2 and sleeps == [1.0]


async def test_empty_after_all_attempts_returns_empty_list():
    empty = httpx.Response(200, text="<html></html>")
    rec = Recorder(*([empty, httpx.Response(200, json={"results": []})] * 3))
    sleeps: list[float] = []
    assert await backend(rec, sleeps).search("q") == []
    assert sleeps == [1.0, 2.0] and len(rec.requests) == 6  # 3 attempts x (POST + JSON fallback)


async def test_blank_query_is_rejected():
    rec = Recorder()
    assert await backend(rec).search("   ") == []
    assert rec.requests == []
