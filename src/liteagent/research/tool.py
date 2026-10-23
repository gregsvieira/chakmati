import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..llm import ChatClient
from ..loop.scorer import PartScorer
from .fetch import PageFetcher, chunk_text, extract_text
from .filter import filter_results, rank_passages
from .search import SearchBackend

COMPOSE_SYSTEM = (
    "Answer the question in the user's language using ONLY the numbered passages below. "
    "Cite the passages you use as [n]. If the passages do not contain the answer, say so "
    "instead of guessing."
)
CONCISE_SUFFIX = (
    " Be concise: answer in at most 3 short sentences unless the question explicitly asks for detail."
)
NOTHING_FOUND = "Não encontrei informações utilizáveis na web para esta pergunta."


@dataclass(frozen=True)
class ResearchAnswer:
    answer: str
    sources: list[str]

    def render(self) -> str:
        if not self.sources:
            return self.answer
        return self.answer + "\n\nFontes:\n" + "\n".join(f"- {u}" for u in self.sources)


class ResearchTool:
    def __init__(
        self,
        search: SearchBackend,
        fetcher: PageFetcher,
        llm: ChatClient,
        scorer: PartScorer,
        max_pages: int = 4,
        passages: int = 4,
        result_cutoff: float = 0.2,
        concise: bool = False,
        fetch_deadline: float | None = None,
    ):
        self._search = search
        self._fetcher = fetcher
        self._llm = llm
        self._scorer = scorer
        self._max_pages = max_pages
        self._passages = passages
        self._cutoff = result_cutoff
        self._system = COMPOSE_SYSTEM + CONCISE_SUFFIX if concise else COMPOSE_SYSTEM
        self._fetch_deadline = fetch_deadline

    async def _fetch_all(self, results) -> list[str | None]:
        """Download the pages in parallel. With a deadline, pages that have not arrived in time are
        cancelled and treated as failed, so one site that hangs cannot hold back the whole answer."""
        tasks = [asyncio.create_task(self._fetcher.fetch(r.url)) for r in results]
        if not tasks:
            return []
        if self._fetch_deadline is None:
            return list(await asyncio.gather(*tasks))
        done, pending = await asyncio.wait(tasks, timeout=self._fetch_deadline)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return [task.result() if task in done and task.exception() is None else None for task in tasks]

    async def _prepare(self, query: str) -> tuple[list[dict[str, str]] | None, list[str]]:
        """Search, filter, fetch and rank. Returns (chat messages, source urls), or (None, [])
        when no usable page was found."""
        results = await self._search.search(query, limit=10)
        results = await asyncio.to_thread(
            filter_results, query, results, self._scorer, self._cutoff
        )
        chosen = results[: self._max_pages]
        bodies = await self._fetch_all(chosen)

        pairs: list[tuple[str, str]] = []  # (passage, url)
        for result, body in zip(chosen, bodies, strict=True):
            if body is None:
                continue
            for passage in chunk_text(extract_text(body, result.url)):
                pairs.append((passage, result.url))
        if not pairs:
            return None, []

        best = await asyncio.to_thread(
            rank_passages, query, [p for p, _ in pairs], self._scorer, self._passages
        )
        url_of: dict[str, str] = {}
        for passage, url in pairs:
            url_of.setdefault(passage, url)
        numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(best, 1))
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": f"Question: {query}\n\nPassages:\n{numbered}"},
        ]
        sources: list[str] = []
        for passage in best:
            url = url_of[passage]
            if url not in sources:
                sources.append(url)
        return messages, sources

    async def answer(self, query: str) -> ResearchAnswer:
        messages, sources = await self._prepare(query)
        if messages is None:
            return ResearchAnswer(NOTHING_FOUND, [])
        reply = await self._llm.chat(messages)
        return ResearchAnswer(reply.strip(), sources)

    async def stream_answer(self, query: str) -> AsyncIterator[str]:
        """Same retrieval as `answer`, but the reply is yielded piece by piece as the model writes it;
        the sources list is appended at the end, so the joined text equals `answer(...).render()`
        (up to surrounding whitespace)."""
        messages, sources = await self._prepare(query)
        if messages is None:
            yield NOTHING_FOUND
            return
        async for delta in self._llm.stream_chat(messages):  # type: ignore[attr-defined]
            yield delta
        if sources:
            yield "\n\nFontes:\n" + "\n".join(f"- {u}" for u in sources)
