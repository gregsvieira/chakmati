"""Compare ways of scoring "is this candidate part good?" on the labelled set.

Run:  uv run python -m chakmati.loop.compare
Needs: Ollama running with the chat model, and `uv sync --extra laya`.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

from .evalset import ALL_ITEMS, LabelledPart, pairwise_accuracy

THRESHOLDS = (0.5, 0.89)
KINDS = ("good", "irrelevant", "wrong")


def summarize(
    scores_by_method: dict[str, list[float]],
    items: Sequence[LabelledPart],
    thresholds: Sequence[float] = THRESHOLDS,
) -> dict[str, dict[str, Any]]:
    totals = {k: sum(1 for i in items if i.kind == k) for k in KINDS}
    out: dict[str, dict[str, Any]] = {}
    for method, scores in scores_by_method.items():
        pair = pairwise_accuracy(items, scores)
        by_kind = {k: [s for i, s in zip(items, scores, strict=True) if i.kind == k] for k in KINDS}
        out[method] = {
            "good_vs_irrelevant": pair["irrelevant"],
            "good_vs_wrong": pair["wrong"],
            "mean": {k: round(mean(v), 3) for k, v in by_kind.items()},
            "passing": {t: {k: sum(1 for s in by_kind[k] if s >= t) for k in KINDS} for t in thresholds},
            "totals": totals,
        }
    return out


# ---------------------------------------------------------------- Laya scorers

def _state(item: LabelledPart) -> dict[str, str]:
    return {"body": f"Question: {item.question}\nCandidate step: {item.part}"}


NOUL = {
    "q": {
        "type": "noul",
        "instructions": "Is this candidate step correct and useful for answering the question?",
    }
}
SCORE = {
    "q": {
        "type": "score",
        "instructions": "How correct and useful is this candidate step for answering the question?",
        "criteria": ["wrong or useless", "partly useful", "correct and useful"],
    }
}
CHOICE = {
    "q": {
        "type": "choice",
        "instructions": "Judge this candidate step for the question.",
        "criteria": {
            "useful": "correct and helps answer the question",
            "irrelevant": "unrelated to the question",
            "incorrect": "related to the question but factually wrong",
        },
    }
}


def laya_scorers(router: Any, checkpoint: str) -> dict[str, Callable[[LabelledPart], float]]:
    def noul(item: LabelledPart) -> float:
        return float(router.predict(_state(item), NOUL, model=checkpoint)["answers"]["q"]["noul"])

    def score(item: LabelledPart) -> float:
        a = router.predict(_state(item), SCORE, model=checkpoint)["answers"]["q"]
        return float(a["score"]) / (len(SCORE["q"]["criteria"]) - 1)

    def choice(item: LabelledPart) -> float:
        a = router.predict(_state(item), CHOICE, model=checkpoint)["answers"]["q"]
        return float(a["probabilities"]["useful"])

    return {
        f"laya/{checkpoint}/noul": noul,
        f"laya/{checkpoint}/score": score,
        f"laya/{checkpoint}/choice": choice,
    }


# ---------------------------------------------------------------- LLM scorers

def _ollama(base: str, model: str, system: str, user: str) -> str:
    r = httpx.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 8},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip().lower()


def llm_scorers(base: str, model: str) -> dict[str, Callable[[LabelledPart], float]]:
    def text(item: LabelledPart) -> str:
        return f"Question: {item.question}\nCandidate step: {item.part}"

    def yesno(item: LabelledPart) -> float:
        out = _ollama(
            base, model,
            "Decide if the candidate step is factually correct AND useful for answering the "
            "question. Reply with exactly one word: yes or no.",
            text(item),
        )
        return 1.0 if out.startswith(("yes", "sim")) else 0.0

    def rate(item: LabelledPart) -> float:
        out = _ollama(
            base, model,
            "Rate how factually correct and useful the candidate step is for answering the "
            "question, from 0 (wrong or useless) to 10 (correct and very useful). "
            "Reply with only the number.",
            text(item),
        )
        m = re.search(r"\d+(?:\.\d+)?", out)
        return min(float(m.group()), 10.0) / 10.0 if m else 0.0

    return {"llm/yes-no": yesno, "llm/rate-0-10": rate}


# ---------------------------------------------------------------- runner

def main() -> None:
    from laya import Router

    from ..config import Settings

    s = Settings.from_env()
    router = Router(max_loaded=3)
    scorers: dict[str, Callable[[LabelledPart], float]] = {}
    for checkpoint in ("multilingual", "english", "typed-decisions"):
        scorers.update(laya_scorers(router, checkpoint))
    scorers.update(llm_scorers(s.ollama_url, s.chat_model))

    scores: dict[str, list[float]] = {}
    timing: dict[str, float] = {}
    for name, fn in scorers.items():
        fn(ALL_ITEMS[0])  # warm-up (model load) excluded from timing
        start = time.perf_counter()
        scores[name] = [fn(item) for item in ALL_ITEMS]
        timing[name] = 1000 * (time.perf_counter() - start) / len(ALL_ITEMS)
        print(f"scored {name}", flush=True)

    Path("compare_scores.json").write_text(
        json.dumps(
            {"items": [i.__dict__ for i in ALL_ITEMS], "scores": scores}, ensure_ascii=False, indent=1
        )
    )
    report = summarize(scores, ALL_ITEMS)
    n = report[next(iter(report))]["totals"]
    print(f"\n{len(ALL_ITEMS)} parts: {n['good']} good, {n['irrelevant']} irrelevant, {n['wrong']} wrong")
    print("\nRanking quality (1.00 = good parts always outscore bad ones; 0.50 = coin flip)")
    print(f"{'method':32s} good>irrel  good>wrong  avg score g/i/w        ms/part")
    for name, r in report.items():
        m = r["mean"]
        print(
            f"{name:32s} {r['good_vs_irrelevant']:9.2f}  {r['good_vs_wrong']:10.2f}  "
            f"{m['good']:.2f}/{m['irrelevant']:.2f}/{m['wrong']:.2f}      {timing[name]:7.0f}"
        )
    for t in THRESHOLDS:
        print(f"\nFixed cutoff: a part passes if score >= {t}")
        print(f"{'method':32s} good pass   irrelevant pass   wrong pass")
        for name, r in report.items():
            p, tot = r["passing"][t], r["totals"]
            print(
                f"{name:32s} {p['good']:3d}/{tot['good']:<3d}     "
                f"{p['irrelevant']:3d}/{tot['irrelevant']:<3d}          {p['wrong']:3d}/{tot['wrong']:<3d}"
            )


if __name__ == "__main__":
    main()
