"""How many pages does the research tool need: 1, 2 or 4?

Step 1  search + download each question's top 4 pages ONCE, record how long each download took.
Step 2  for every ranker x pages configuration run the real ResearchTool on that same data
        (a page only counts if it finished within the 2 s deadline, as in production) and
        check whether the final answer contains the expected fact.
Step 3  fetch-stage waiting time per pages value, computed from the measured download times.

Run:  uv run python -m chakmati.features.research.pages_experiment   (needs SearXNG on :8080 and Ollama)
"""

import asyncio
import json
import re
import time
from collections.abc import Sequence
from pathlib import Path

import httpx

from chakmati.shared.config import Settings
from chakmati.shared.llm import OllamaClient
from chakmati.features.research.loop.scorer import KeepAllScorer
from chakmati.features.research.fetch import PageFetcher
from chakmati.features.research.rankers import EmbeddingScorer
from chakmati.features.research.search import SearchResult, build_user_agent
from chakmati.features.research.searxng import SearxngBackend
from chakmati.features.research.tool import ResearchTool

DEADLINE = 2.0
PAGES = (1, 2, 4)
REPS = 2
OUT = Path("docs/superpowers/results/2026-10-23-pages_experiment.json")

# (query, regex a correct answer must match)
QUESTIONS = [
    ("quem escreveu Dom Casmurro", r"Machado"),
    ("capital da Austrália", r"Canberra|Camberra"),
    ("o que é espalhamento de Rayleigh", r"part[ií]cul|particle"),
    ("quantos dias tem fevereiro em ano bissexto", r"29"),
    ("quem pintou a Mona Lisa", r"Leonardo|Vinci"),
    ("qual a capital do Canadá", r"Ottawa"),
    ("em que ano o homem pisou na lua", r"1969"),
    ("qual o maior planeta do sistema solar", r"J[úu]piter|Jupiter"),
    ("quem descobriu o Brasil", r"Cabral"),
    ("qual a fórmula química da água", r"H2O|H₂O"),
    ("versão estável atual do Python", r"3\.1[3-6]"),
    ("latest stable Node.js version", r"2[4-7]\.\d+"),
]


def fetch_wait(durations: Sequence[float], pages: int, deadline: float) -> float:
    """Time until the batch of the first `pages` downloads is over: the slowest one, capped by the deadline."""
    chosen = list(durations[:pages])
    return min(deadline, max(chosen)) if chosen else 0.0


def usable_pages(
    bodies: Sequence[str | None], durations: Sequence[float], pages: int, deadline: float
) -> list[str | None]:
    """The first `pages` bodies, with the ones that failed or finished after the deadline replaced by None."""
    return [
        body if body is not None and dur <= deadline else None
        for body, dur in list(zip(bodies, durations, strict=True))[:pages]
    ]


def first_k_successes(
    bodies: Sequence[str | None], durations: Sequence[float], k: int, deadline: float
) -> tuple[list[int], float]:
    """`target_pages` simulated on measured data. Returns (indices in rank order of the pages used,
    seconds waited). Waits until the k-th successful download; if fewer than k succeed within the
    deadline, uses what arrived and waits the deadline (or until every download ended, if sooner)."""
    ok = sorted(
        (dur, i) for i, (b, dur) in enumerate(zip(bodies, durations, strict=True)) if b is not None and dur <= deadline
    )
    if len(ok) >= k:
        chosen = ok[:k]
        return sorted(i for _, i in chosen), chosen[-1][0]
    ended = max(durations) if durations else 0.0
    return sorted(i for _, i in ok), min(deadline, ended)


class ReplaySearch:
    def __init__(self, results: dict[str, list[SearchResult]]):
        self._results = results

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._results[query][:limit]


class ReplayFetcher:
    """Serves the pre-downloaded bodies; pages that failed or were too slow come back as None."""

    def __init__(self, bodies: dict[str, str | None]):
        self._bodies = bodies

    async def fetch(self, url: str) -> str | None:
        return self._bodies.get(url)


async def collect(settings: Settings) -> dict[str, dict]:
    backend = SearxngBackend(settings.searxng_url)
    fetcher = PageFetcher(timeout=10.0, user_agent=build_user_agent(settings.contact))
    data: dict[str, dict] = {}
    for query, _ in QUESTIONS:
        results = (await backend.search(query, 10))[:4]

        async def timed(url: str) -> tuple[str | None, float]:
            start = time.perf_counter()
            body = await fetcher.fetch(url)
            return body, time.perf_counter() - start

        fetched = await asyncio.gather(*(timed(r.url) for r in results))
        data[query] = {
            "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
            "bodies": [b for b, _ in fetched],
            "durations": [d for _, d in fetched],
        }
        print(f"collected {query!r}: durations={[round(d, 2) for _, d in fetched]}", flush=True)
    await backend.aclose()
    await fetcher.aclose()
    return data


async def run_config(
    settings: Settings, data: dict, ranker_name: str, pages: int, target: bool = False
) -> tuple[int, float]:
    scorer = EmbeddingScorer(settings.ollama_url) if ranker_name == "embeddings" else KeepAllScorer()
    llm = OllamaClient(settings.ollama_url, settings.chat_model, num_predict=200)
    correct, compute = 0, 0.0
    for query, expected in QUESTIONS:
        entry = data[query]
        results = [SearchResult(**r) for r in entry["results"]]
        if target:  # consider all candidates, keep the `pages` fastest successes
            chosen, _ = first_k_successes(entry["bodies"], entry["durations"], pages, DEADLINE)
            urls = {results[i].url: entry["bodies"][i] for i in chosen}
            considered = len(results)
        else:
            bodies = usable_pages(entry["bodies"], entry["durations"], pages, DEADLINE)
            urls = {r.url: b for r, b in zip(results[:pages], bodies, strict=True)}
            considered = pages
        tool = ResearchTool(
            ReplaySearch({query: results}), ReplayFetcher(urls), llm, scorer,
            max_pages=considered, concise=True, result_cutoff=0.0,
        )
        start = time.perf_counter()
        answer = await tool.answer(query)
        compute += time.perf_counter() - start
        correct += bool(re.search(expected, answer.answer, re.IGNORECASE))
    await llm.aclose()
    return correct, compute / len(QUESTIONS)


async def main() -> None:
    settings = Settings.from_env()
    if OUT.exists():
        data = json.loads(OUT.read_text())
        print(f"using cached downloads from {OUT}")
    else:
        data = await collect(settings)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False))
    n = len(QUESTIONS)
    ok_pages = {p: sum(any(b is not None and d <= DEADLINE for b, d in zip(data[q]["bodies"][:p], data[q]["durations"][:p])) for q, _ in QUESTIONS) for p in PAGES}

    print(f"\n{n} questions. Pages that fail or take > {DEADLINE}s are ignored (as in production).")
    print("\nFetch stage (computed from the measured download times)")
    print(f"{'pages':>6s}  mean_wait  questions_with_at_least_one_usable_page")
    for p in PAGES:
        waits = [fetch_wait(data[q]["durations"], p, DEADLINE) for q, _ in QUESTIONS]
        print(f"{p:>6d}  {sum(waits) / n:7.2f}s  {ok_pages[p]}/{n}")
    tw = [first_k_successes(data[q]["bodies"], data[q]["durations"], 2, DEADLINE)[1] for q, _ in QUESTIONS]
    tu = sum(1 for q, _ in QUESTIONS if first_k_successes(data[q]["bodies"], data[q]["durations"], 2, DEADLINE)[0])
    print(f"{'2 of 4':>6s}  {sum(tw) / n:7.2f}s  {tu}/{n}   <- target: stop at the 2nd successful page among 4 candidates")

    print(f"\nAnswer correctness (real ResearchTool + qwen3.5, {REPS} repetitions each)")
    print(f"{'ranker':>11s} {'pages':>5s}  correct/{n}   (per repetition)   mean compute time (rank+LLM)")
    for ranker in ("keepall", "embeddings"):
        for label, p, target in [("1", 1, False), ("2", 2, False), ("4", 4, False), ("2of4", 2, True)]:
            scores, times = [], []
            for _ in range(REPS):
                c, t = await run_config(settings, data, ranker, p, target)
                scores.append(c)
                times.append(t)
            print(f"{ranker:>11s} {label:>5s}  {sum(scores) / REPS:8.1f}   {scores}   {sum(times) / REPS:6.2f}s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
