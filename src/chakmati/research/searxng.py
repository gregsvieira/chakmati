"""SearXNG search backend: a port of agenticSeek's `sources/tools/searxSearch.py`.

Same behaviour as the original:
  * POST {base}/search with the same form fields and the same headers
  * parse the HTML results page (`article.result` > `a.url_header`, `h3`, `p.content`)
  * if the HTML yields nothing, fall back to the JSON API (first 20 results)
  * up to 3 attempts, sleeping 1.0 * attempt seconds between them
  * TLS verification off and a 15 s timeout, as in the original (the instance is local)

Differences, all forced by the interface: it is async (httpx), it returns `SearchResult`s instead of
one formatted string, and when the instance cannot be reached after all attempts it raises
`SearxngUnavailable` (the original returned the error text). An empty result set returns `[]`
(the original returned "No search results, web search failed.").
"""

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

import httpx
from lxml import html as lxml_html

from chakmati.research.search import SearchResult

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
MAX_ATTEMPTS = 3
JSON_FALLBACK_LIMIT = 20


class SearxngUnavailable(RuntimeError):
    """The SearXNG instance could not be reached (or kept failing) after every attempt."""


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def parse_searxng_html(html: str) -> list[SearchResult]:
    """Extract results from the SearxNG HTML results page."""
    if not html.strip():
        return []
    tree = lxml_html.fromstring(html)
    results: list[SearchResult] = []
    for article in tree.xpath(f"//article[{_has_class('result')}]"):
        url_header = article.xpath(f".//a[{_has_class('url_header')}]")
        if not url_header or not url_header[0].get("href"):
            continue
        h3 = article.xpath(".//h3")
        content = article.xpath(f".//p[{_has_class('content')}]")
        title = h3[0].text_content().strip() if h3 else "No Title"
        snippet = content[0].text_content().strip() if content else "No Description"
        results.append(SearchResult(title, url_header[0].get("href"), snippet))
    return results


class SearxngBackend:
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout: float = REQUEST_TIMEOUT,
        max_attempts: int = MAX_ATTEMPTS,
    ):
        self._base = base_url.rstrip("/")
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout, verify=False)

    async def _search_json_api(self, query: str) -> list[SearchResult]:
        """Fallback: query the SearxNG JSON API, which is stable across UI template changes.
        Requires "json" in search.formats of the SearxNG settings; returns [] when unavailable."""
        try:
            response = await self._http.get(
                f"{self._base}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "language": "auto",
                    "safesearch": "0",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            response.raise_for_status()
            results: list[SearchResult] = []
            for r in response.json().get("results", [])[:JSON_FALLBACK_LIMIT]:
                results.append(
                    SearchResult(
                        r.get("title") or "No Title",
                        r.get("url", ""),
                        r.get("content") or "No Description",
                    )
                )
            return results
        except (httpx.HTTPError, ValueError):
            return []

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": USER_AGENT,
        }
        data = urlencode(
            {
                "q": query,
                "categories": "general",
                "language": "auto",
                "time_range": "",
                "safesearch": "0",
                "theme": "simple",
            }
        ).encode("utf-8")

        last_error: str | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._http.post(f"{self._base}/search", headers=headers, content=data)
                response.raise_for_status()
                results = parse_searxng_html(response.text)
                if not results:
                    # HTML template change or an empty result set: try the JSON API.
                    results = await self._search_json_api(query)
                if results:
                    return results[:limit]
                last_error = None  # reachable, but nothing found
            except httpx.HTTPError as e:
                last_error = (
                    "Error during search: SearxNG unavailable. Is the SearXNG container "
                    f"running? ({e})"
                )
            if attempt < self._max_attempts - 1:
                await self._sleep(1.0 * (attempt + 1))  # brief backoff, then retry
        if last_error is not None:
            raise SearxngUnavailable(last_error)
        return []

    async def aclose(self) -> None:
        await self._http.aclose()
