import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from ..llm import ChatClient
from ..loop.scorer import PartScorer
from ..persona import PERSONA
from ..guard import NOTE, UNTRUSTED_RULE, StreamScrubber, neutralize, strip_markers, suspicious
from ..timeguard import is_recency_question, order_by_date, recency_fallback_query, today_line
from .fetch import PageFetcher, chunk_text, extract_text
from .filter import filter_results, rank_passages
from .search import SearchBackend

COMPOSE_SYSTEM = PERSONA + " " + (
    "Answer the question in the user's language using ONLY the numbered passages below. "
    "Cite the passages you use as [n]. If the passages do not contain the exact answer, give the closest "
    "relevant information they do contain and say what is missing; say you found nothing only if they are "
    "unrelated to the question. Never invent."
)
RECENCY_SUFFIX = (
    " The user wants the most recent item. The passages are ordered from the most recent date to the oldest and "
    "show their date. Answer with the most recent item dated no later than today and give its date. If it may not "
    "be the very latest, say so, but still answer."
)
REWRITE_SYSTEM = (
    "Escreva UMA consulta curta de busca na web, em português, com até 8 palavras, no plural quando fizer sentido, "
    "sem ponto de interrogação, que ache o que há de mais recente para a pergunta. Inclua o mês e o ano de hoje. "
    "Responda só com a consulta."
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
        target_pages: int | None = None,
    ):
        self._search = search
        self._fetcher = fetcher
        self._llm = llm
        self._scorer = scorer
        self._max_pages = max_pages
        self._passages = passages
        self._cutoff = result_cutoff
        self._system = COMPOSE_SYSTEM + CONCISE_SUFFIX if concise else COMPOSE_SYSTEM
        self._flagged = False  # the passages of the last question addressed the assistant (the worker runs one job at a time)
        self._fetch_deadline = fetch_deadline
        self._target_pages = target_pages

    async def _fetch_all(self, results) -> list[str | None]:
        """Download the pages in parallel.
        * `fetch_deadline`: pages that have not arrived in time are cancelled and treated as failed,
          so one site that hangs cannot hold back the whole answer.
        * `target_pages`: stop waiting as soon as this many pages downloaded successfully (the rest
          are cancelled); if fewer succeed, whatever arrived is used.
        Without either, it waits for every download."""
        tasks = [asyncio.create_task(self._fetcher.fetch(r.url)) for r in results]
        if not tasks:
            return []
        if self._fetch_deadline is None and self._target_pages is None:
            return list(await asyncio.gather(*tasks))
        loop = asyncio.get_running_loop()
        limit = None if self._fetch_deadline is None else loop.time() + self._fetch_deadline
        pending = set(tasks)
        successes = 0
        while pending:
            timeout = None if limit is None else max(0.0, limit - loop.time())
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:  # deadline reached
                break
            successes += sum(1 for t in done if t.exception() is None and t.result() is not None)
            if self._target_pages is not None and successes >= self._target_pages:
                break
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return [
            task.result() if task.done() and not task.cancelled() and task.exception() is None else None
            for task in tasks
        ]

    async def _recency_query(self, query: str, now: datetime) -> str:
        """A search query with the month and year ("filmes lançados em outubro de 2026"); the rule-based one if the model's is unusable."""
        fallback = recency_fallback_query(query, now)
        try:
            reply = (await self._llm.chat([
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": f"{today_line(now)}\nPergunta: {query}"},
            ])).strip().strip('"')
        except Exception:
            return fallback
        usable = reply and "\n" not in reply and len(reply) <= 100 and not re.search(r"[\[\]{}<>]", reply) and str(now.year) in reply
        return reply if usable else fallback

    async def gather(self, query: str, max_chars: int = 4000) -> tuple[str, list[str]]:
        """The text of the best pages for `query`, for something other than an answer (a document the person asked to make):
        (text, source urls), or ("", []) when nothing usable was found. The text is third-party DATA: callers fence it."""
        results = await self._search.search(query, limit=10)
        results = await asyncio.to_thread(filter_results, query, results, self._scorer, self._cutoff)
        chosen = results[: self._max_pages]
        bodies = await self._fetch_all(chosen)
        parts, urls = [], []
        for result, body in zip(chosen, bodies, strict=True):
            if body is None:
                continue
            text = neutralize(extract_text(body, result.url))
            if text.strip():
                parts.append(text.strip())
                urls.append(result.url)
        return "\n\n".join(parts)[:max_chars], urls

    async def _prepare(self, query: str, today: str | None = None, now: datetime | None = None) -> tuple[list[dict[str, str]] | None, list[str]]:
        """Search, filter, fetch and rank. Returns (chat messages, source urls), or (None, [])
        when no usable page was found. For "the latest"-style questions (`now` given) it also searches with the month and
        year, and the passages are put in order of date, newest first."""
        recency = now is not None and is_recency_question(query)
        results = await self._search.search(query, limit=10)
        if recency:
            extra = await self._recency_query(query, now)
            if extra and extra != query:
                known = {r.url for r in results}
                results = [*(r for r in await self._search.search(extra, limit=10) if r.url not in known), *results]
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

        if recency:
            # a list of releases is often written oldest-first, so its newest item is at the BOTTOM: look at every passage
            # of the pages (they already passed the relevance filter) and let the dates decide, not the position
            best = [p for p, _ in pairs][:150]
        else:
            best = await asyncio.to_thread(
                rank_passages, query, [p for p, _ in pairs], self._scorer, self._passages
            )
        url_of: dict[str, str] = {}
        for passage, url in pairs:
            url_of.setdefault(passage, url)
        if recency:
            ordered = order_by_date(best, now)[: self._passages + 2]
            best = [p for p, _ in ordered]
            numbered = "\n".join(f"[{i}] {f'(data: {d:%d/%m/%Y}) ' if d else ''}{neutralize(p)}" for i, (p, d) in enumerate(ordered, 1))
        else:
            numbered = "\n".join(f"[{i}] {neutralize(p)}" for i, p in enumerate(best, 1))
        self._flagged = suspicious(list(best), "web")
        system = self._system + UNTRUSTED_RULE + (RECENCY_SUFFIX if recency else "")
        messages = [
            {"role": "system", "content": system + (f" {today} Today's date matters for words like 'latest' or 'recent'." if today else "")},
            {"role": "user", "content": f"Question: {query}\n\nPassages:\n<untrusted source=\"web\">\n{numbered}\n</untrusted>"},
        ]
        sources: list[str] = []
        for passage in best:
            url = url_of[passage]
            if url not in sources:
                sources.append(url)
        return messages, sources

    async def answer(self, query: str, today: str | None = None, now: datetime | None = None) -> ResearchAnswer:
        messages, sources = await self._prepare(query, today, now)
        if messages is None:
            return ResearchAnswer(NOTHING_FOUND, [])
        reply = await self._llm.chat(messages)
        return ResearchAnswer(strip_markers(reply).strip() + (NOTE if self._flagged else ""), sources)

    async def stream_answer(self, query: str, today: str | None = None, now: datetime | None = None) -> AsyncIterator[str]:
        """Same retrieval as `answer`, but the reply is yielded piece by piece as the model writes it;
        the sources list is appended at the end, so the joined text equals `answer(...).render()`
        (up to surrounding whitespace)."""
        messages, sources = await self._prepare(query, today, now)
        if messages is None:
            yield NOTHING_FOUND
            return
        scrub = StreamScrubber()
        async for delta in self._llm.stream_chat(messages):  # type: ignore[attr-defined]
            safe = scrub.feed(delta)
            if safe:
                yield safe
        if rest := scrub.flush():
            yield rest
        if self._flagged:
            yield NOTE
        if sources:
            yield "\n\nFontes:\n" + "\n".join(f"- {u}" for u in sources)
