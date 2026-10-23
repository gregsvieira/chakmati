import httpx
import pytest

from liteagent.research.search import (
    USER_AGENT,
    DuckDuckGoHtmlBackend,
    SearchResult,
    parse_ddg_html,
)

HTML = """
<div id="links" class="results">
  <div class="result results_links web-result">
    <div class="links_main result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="https://www.python.org/downloads/">Download Python | Python.org</a>
      </h2>
      <a class="result__snippet" href="https://www.python.org/downloads/">Looking for <b>Python</b> with a different OS?</a>
    </div>
  </div>
  <div class="result results_links web-result">
    <div class="links_main result__body">
      <h2 class="result__title">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Fb%3D1&amp;rut=abc">Example &amp; Co</a>
      </h2>
      <a class="result__snippet" href="x">Second snippet</a>
    </div>
  </div>
  <div class="result result--ad">
    <h2 class="result__title"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></h2>
    <a class="result__snippet">buy now</a>
  </div>
  <div class="result"><h2 class="result__title"><a class="result__a">no href</a></h2></div>
</div>
"""


def test_parse_extracts_title_url_snippet_and_unwraps_redirects():
    results = parse_ddg_html(HTML)
    assert results == [
        SearchResult(
            "Download Python | Python.org",
            "https://www.python.org/downloads/",
            "Looking for Python with a different OS?",
        ),
        SearchResult("Example & Co", "https://example.com/a?b=1", "Second snippet"),
    ]


def test_parse_empty_and_garbage():
    assert parse_ddg_html("") == []
    assert parse_ddg_html("<html><body>nothing</body></html>") == []


def test_search_result_text():
    assert SearchResult("T", "u", "S").text == "T. S"


async def test_backend_requests_ddg_with_user_agent_and_limits_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=HTML)

    backend = DuckDuckGoHtmlBackend(transport=httpx.MockTransport(handler))
    results = await backend.search("python version", limit=1)
    assert len(results) == 1
    assert seen["url"].startswith("https://html.duckduckgo.com/html/?q=python+version")
    assert seen["ua"] == USER_AGENT


async def test_backend_http_error_raises():
    backend = DuckDuckGoHtmlBackend(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(httpx.HTTPStatusError):
        await backend.search("q")


from liteagent.research.search import build_user_agent


def test_build_user_agent_adds_the_contact_only_when_given():
    assert build_user_agent("") == USER_AGENT
    assert build_user_agent(None) == USER_AGENT
    ua = build_user_agent("https://example.org/me")
    assert ua.startswith("lite-agent/0.1") and "contact: https://example.org/me" in ua
