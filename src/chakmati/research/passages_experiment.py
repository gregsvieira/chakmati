"""Which passage ranker puts the answer-bearing passages first?

Corpus: the first 4 pages of the cached DuckDuckGo results for each case, extracted and chunked
(`docs/superpowers/results/2026-10-23-passages_corpus.json`). "Gold" passages are defined by a
regex written BEFORE looking at any ranker output (see CASES). The end-to-end check gives the top 4
passages of each ranker to the LLM with the same prompt as ResearchTool and checks the answer.

Run:  uv run python -m chakmati.research.passages_experiment
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from chakmati.config import Settings
from chakmati.loop.scorer import KeepAllScorer
from chakmati.research.rankers import Bm25Scorer, EmbeddingScorer
from chakmati.research.tool import COMPOSE_SYSTEM

CORPUS_FILE = Path("docs/superpowers/results/2026-10-23-passages_corpus.json")

# Per case (all regexes fixed from the page texts, none tuned to a ranker):
#   official : passages that carry the OFFICIAL current-version data (tables / release lists)
#   explicit : passages that EXPLICITLY say which version is the latest/current (may be outdated)
#   latest   : a final answer naming the truly latest stable version
#   any      : a final answer that names some concrete version (possibly outdated)
# NOTE: `explicit` and the answer categories were added after a first run showed the single
# strict gold missed passages that say "3.14 is the latest" (a third-party page that is already
# outdated vs the official 3.15.1); the first run is kept in the spec.
CASES: dict[str, dict[str, str]] = {
    "pesquise a versão estável atual do Python": {
        "official": r"3\.15 (?:bugfix|feature)|Python 3\.15\.\d+ - ",
        "explicit": r"(?:mais recente|latest)[^.\n]{0,80}3\.1\d|3\.1\d[^.\n]{0,80}(?:mais recente|latest)",
        "latest": r"3\.15",
        "any": r"3\.1[3-6]",
    },
    "latest stable Node.js version": {
        "official": r"Version 2[4-7]\.\d+\.\d+ \((?:Current|LTS)\)|v2[4-7]\.\d+\.\d+",
        "explicit": r"(?:latest|current|LTS)[^.\n]{0,60}v?2\d\.\d+|v?2\d\.\d+[^.\n]{0,60}(?:latest|current|LTS)",
        "latest": r"\b(?:26|24)\.\d+",
        "any": r"\b2\d\.\d+",
    },
}
CORPUS_KEYS = {
    "pesquise a versão estável atual do Python": "versão estável atual do Python",
    "latest stable Node.js version": "latest stable Node.js version",
}


def _order(scores: Sequence[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))  # ties keep input order


def rank_of_first(scores: Sequence[float], gold: Sequence[bool]) -> int | None:
    for position, idx in enumerate(_order(scores), 1):
        if gold[idx]:
            return position
    return None


def gold_in_top(scores: Sequence[float], gold: Sequence[bool], k: int) -> int:
    return sum(1 for idx in _order(scores)[:k] if gold[idx])


def _answer(settings: Settings, query: str, passages: list[str]) -> str:
    numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(passages, 1))
    response = httpx.post(
        f"{settings.ollama_url}/api/chat",
        json={
            "model": settings.chat_model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": COMPOSE_SYSTEM},
                {"role": "user", "content": f"Question: {query}\n\nPassages:\n{numbered}"},
            ],
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def rankers(settings: Settings) -> dict[str, object]:
    from laya import Router

    router = Router(max_loaded=3)

    class LayaPassage:
        def __init__(self, checkpoint: str, kind: str):
            self.checkpoint, self.kind = checkpoint, kind

        def score(self, question: str, parts: Sequence[str]) -> list[float]:
            if self.kind == "noul":
                spec = {"q": {"type": "noul", "instructions": "Does this passage answer the question?"}}
                key = lambda a: float(a["noul"])  # noqa: E731
            else:
                spec = {
                    "q": {
                        "type": "score",
                        "instructions": "How well does this passage answer the question?",
                        "criteria": ["not at all", "partly", "directly"],
                    }
                }
                key = lambda a: float(a["score"]) / 2  # noqa: E731
            return [
                key(
                    router.predict(
                        {"body": f"Question: {question}\nPassage: {p}"}, spec, model=self.checkpoint
                    )["answers"]["q"]
                )
                for p in parts
            ]

    return {
        "page order (keep-all)": KeepAllScorer(),
        "laya multilingual/noul": LayaPassage("multilingual", "noul"),
        "laya english/score": LayaPassage("english", "score"),
        "bm25": Bm25Scorer(),
        "embeddings (nomic)": EmbeddingScorer(settings.ollama_url),
    }


def main() -> None:
    settings = Settings.from_env()
    corpus = json.loads(CORPUS_FILE.read_text())
    methods = rankers(settings)
    results: list[dict[str, object]] = []
    for query, rx in CASES.items():
        rows = corpus[CORPUS_KEYS[query]]
        texts = [r["text"] for r in rows]
        gold_off = [bool(re.search(rx["official"], t)) for t in texts]
        gold_exp = [bool(re.search(rx["explicit"], t, re.I)) for t in texts]
        print(f"\n### {query}\n{len(texts)} passages; {sum(gold_off)} official-data, {sum(gold_exp)} explicit-claim")
        print(
            f"{'ranker':24s} first_rank(off/exp)  top4(off/exp)  ms/passage  final answer"
        )
        for name, ranker in methods.items():
            score: Callable[[str, Sequence[str]], list[float]] = ranker.score  # type: ignore[attr-defined]
            start = time.perf_counter()
            scores = score(query, texts)
            ms = 1000 * (time.perf_counter() - start) / len(texts)
            top4 = [texts[i] for i in _order(scores)[:4]]
            answer = _answer(settings, query, top4)
            if re.search(rx["latest"], answer):
                verdict = "LATEST (correct)"
            elif re.search(rx["any"], answer):
                verdict = "other version (outdated)"
            else:
                verdict = "no version given"
            print(
                f"{name:24s} {str(rank_of_first(scores, gold_off)):>8s}/{str(rank_of_first(scores, gold_exp)):<8s}"
                f"  {gold_in_top(scores, gold_off, 4):6d}/{gold_in_top(scores, gold_exp, 4):<5d}"
                f"  {ms:9.1f}  {verdict}",
                flush=True,
            )
            results.append({"query": query, "ranker": name, "verdict": verdict, "answer": answer})
    Path("docs/superpowers/results/2026-10-23-passages_answers.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1)
    )


if __name__ == "__main__":
    main()
