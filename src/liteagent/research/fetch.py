import re

import httpx
import trafilatura

from .search import USER_AGENT

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def extract_text(html: str, url: str = "") -> str:
    text = trafilatura.extract(html, url=url or None, include_comments=False, include_tables=False)
    return (text or "").strip()


def _pieces(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        for sentence in _SENTENCE_END.split(paragraph.strip()):
            sentence = sentence.strip()
            while len(sentence) > max_chars:
                pieces.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            if sentence:
                pieces.append(sentence)
    return pieces


def chunk_text(text: str, max_chars: int = 800) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in _pieces(text, max_chars):
        if current and len(current) + 1 + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


class PageFetcher:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        user_agent: str = USER_AGENT,
    ):
        self._max = max_bytes
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )

    async def fetch(self, url: str) -> str | None:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if not (content_type.startswith("text/html") or content_type.startswith("text/plain")):
            return None
        if len(response.content) > self._max:
            return None
        return response.text

    async def aclose(self) -> None:
        await self._http.aclose()
