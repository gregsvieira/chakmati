"""Does Laya help as a search-result filter, compared with the engine's own ranking?

Step 1  uv run python -m chakmati.research.experiment collect   # queries the web once, caches results
Step 2  (a person labels results: docs/superpowers/results/2026-10-23-search_labels.json)
Step 3  uv run python -m chakmati.research.experiment run       # scores and compares
"""

import asyncio
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from chakmati.config import Settings
from chakmati.research.evalset import LabelledResult, ranking_metrics, with_injected_negatives
from chakmati.research.search import DuckDuckGoHtmlBackend

RESULTS_DIR = Path("docs/superpowers/results")
RESULTS_FILE = RESULTS_DIR / "2026-10-23-search_results.json"
LABELS_FILE = RESULTS_DIR / "2026-10-23-search_labels.json"

QUERIES = [
    "versão estável atual do Python",
    "latest stable Node.js version",
    "capital da Austrália",
    "como ferver ovos duros",
    "quem escreveu Dom Casmurro",
    "o que é espalhamento de Rayleigh",
    "preço atual do bitcoin em reais",
    "how to restart a router",
]


async def collect() -> None:
    if RESULTS_FILE.exists():
        print(f"{RESULTS_FILE} already exists; delete it to collect again")
        return
    backend = DuckDuckGoHtmlBackend()
    out: dict[str, list[dict[str, str]]] = {}
    for q in QUERIES:
        results = await backend.search(q, 10)
        out[q] = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results]
        print(f"{q!r}: {len(results)} results", flush=True)
        await asyncio.sleep(2)  # polite pacing
    await backend.aclose()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1))


def load_items() -> list[LabelledResult]:
    data = json.loads(RESULTS_FILE.read_text())
    labels = json.loads(LABELS_FILE.read_text())  # {query: [urls that are NOT relevant]}
    items: list[LabelledResult] = []
    for query, results in data.items():
        bad = set(labels.get(query, []))
        for rank, r in enumerate(results, 1):
            items.append(
                LabelledResult(query, rank, r["title"], r["url"], r["snippet"],
                               0 if r["url"] in bad else 1, "natural")
            )
    return items


def scorers(settings: Settings) -> dict[str, Callable[[LabelledResult], float]]:
    from laya import Router

    from chakmati.research.judge import llm_relevance_scorer

    router = Router(max_loaded=3)
    state = lambda i: {"body": f"Query: {i.query}\nSearch result: {i.text}"}  # noqa: E731
    noul = {"q": {"type": "noul", "instructions": "Is this search result relevant to the query?"}}
    score = {
        "q": {
            "type": "score",
            "instructions": "How well does this search result answer the query?",
            "criteria": ["irrelevant", "partly relevant", "directly relevant"],
        }
    }
    out: dict[str, Callable[[LabelledResult], float]] = {"engine rank (-rank)": lambda i: -float(i.rank)}
    for ck in ("english", "multilingual"):
        out[f"laya/{ck}/noul"] = lambda i, ck=ck: float(
            router.predict(state(i), noul, model=ck)["answers"]["q"]["noul"])
        out[f"laya/{ck}/score"] = lambda i, ck=ck: float(
            router.predict(state(i), score, model=ck)["answers"]["q"]["score"]) / 2
    out["llm/yes-no"] = llm_relevance_scorer(settings.ollama_url, settings.chat_model)
    return out


def run() -> None:
    items = with_injected_negatives(load_items(), per_query=3)
    natural = [i for i in items if i.source == "natural"]
    print(f"{len(natural)} natural results ({sum(i.relevant for i in natural)} relevant), "
          f"{len(items) - len(natural)} injected irrelevant\n")
    print(f"{'method':24s} {'natural: pairwise  p@3':26s} {'natural+injected: pairwise  p@3':32s} ms/result")
    for name, fn in scorers(Settings.from_env()).items():
        fn(items[0])  # warm-up
        start = time.perf_counter()
        scores = [fn(i) for i in items]
        ms = 1000 * (time.perf_counter() - start) / len(items)
        nat_scores = [s for i, s in zip(items, scores, strict=True) if i.source == "natural"]
        a = ranking_metrics(natural, nat_scores)
        b = ranking_metrics(items, scores)
        # injected results carry another query's rank, so the rank baseline is meaningless there
        both = ("n/a", "n/a") if name.startswith("engine rank") else (f"{b['pairwise']:.2f}", f"{b['precision_at_3']:.2f}")
        print(f"{name:24s} {a['pairwise']:14.2f} {a['precision_at_3']:8.2f} "
              f"{both[0]:>18s} {both[1]:>8s} {ms:12.0f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    asyncio.run(collect()) if cmd == "collect" else run()
