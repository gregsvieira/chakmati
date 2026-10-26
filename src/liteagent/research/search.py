from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from lxml import html as lxml_html

USER_AGENT = "chakmati/0.1 (+local research assistant; low volume)"


def build_user_agent(contact: str | None) -> str:
    """Some sites (Wikipedia) reject user agents that do not say who runs the bot. When the user
    configures a contact (LITEAGENT_CONTACT: a URL or an e-mail) it is appended; otherwise the
    plain agent is used. Nothing is invented or taken from the machine."""
    if not contact:
        return USER_AGENT
    return f"chakmati/0.1 (local research assistant; low volume; contact: {contact})"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    @property
    def text(self) -> str:
        return f"{self.title}. {self.snippet}"


class SearchBackend(Protocol):
    async def search(self, query: str, limit: int = 10) -> list[SearchResult]: ...


def _clean_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com"):
        if parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return target or None
        return None  # ads (y.js) and other internal links
    return href if parsed.scheme in {"http", "https"} else None


def parse_ddg_html(html: str) -> list[SearchResult]:
    if not html.strip():
        return []
    tree = lxml_html.fromstring(html)
    results: list[SearchResult] = []
    for block in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " result ")]'):
        link = block.xpath('.//a[contains(@class, "result__a")]')
        if not link:
            continue
        url = _clean_url(link[0].get("href", ""))
        if url is None:
            continue
        snippet_nodes = block.xpath('.//a[contains(@class, "result__snippet")]')
        snippet = snippet_nodes[0].text_content().strip() if snippet_nodes else ""
        results.append(SearchResult(link[0].text_content().strip(), url, " ".join(snippet.split())))
    return results


class DuckDuckGoHtmlBackend:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        user_agent: str = USER_AGENT,
    ):
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        response = await self._http.get("https://html.duckduckgo.com/html/", params={"q": query})
        response.raise_for_status()
        return parse_ddg_html(response.text)[:limit]

    async def aclose(self) -> None:
        await self._http.aclose()
