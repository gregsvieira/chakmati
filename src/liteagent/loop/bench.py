"""Live end-to-end comparison of answering strategies (needs Ollama; Laya optional).

Run:  uv run python -m liteagent.loop.bench

Modes
  plain         one chat call, think=False
  plain-concise same, with the compose prompt's "answer concisely" instruction (length control)
  native-think  one chat call, think=True (the model's own reasoning)
  loop-keepall  draft -> keep every part (no scoring) -> compose
  loop-llm      draft -> LLM verifies EVERY part -> compose
  loop-2stage   draft -> Laya relevance pre-filter -> LLM verifies survivors -> compose
"""

import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import OllamaClient
from .metered import MeteredLLM
from .prune import PruneConfig
from .runner import ThinkLoop
from .scorer import KeepAllScorer
from .twostage import LayaRelevanceScorer, LLMVerifier, TwoStageScorer

QUESTIONS = [
    "Explique por que o céu é azul.",
    "Quantos dias tem fevereiro em um ano bissexto e por quê?",
    "Qual a diferença entre TCP e UDP?",
    "Se eu tenho 3 maçãs, como 1 e depois compro 5, quantas tenho?",
    "Qual é a capital da Austrália e por que não é Sydney?",
    "Como faço para ferver ovos duros?",
]
MODES = ("plain", "plain-concise", "native-think", "loop-keepall", "loop-llm", "loop-2stage")
PRUNE = PruneConfig(threshold=0.5, max_keep=5, min_keep=1)


async def run_mode(
    mode: str, s: Settings, question: str, relevance: LayaRelevanceScorer
) -> dict[str, Any]:
    inner = OllamaClient(s.ollama_url, s.chat_model, think=(mode == "native-think"))
    llm = MeteredLLM(inner)
    verifier = LLMVerifier(s.ollama_url, s.chat_model)
    stats: dict[str, Any] = {}
    start = time.perf_counter()
    if mode in ("plain", "native-think"):
        answer = await llm.chat([{"role": "user", "content": question}])
    elif mode == "plain-concise":
        answer = await llm.chat(
            [
                {"role": "system", "content": "Answer the question concisely in the user's language."},
                {"role": "user", "content": question},
            ]
        )
    else:
        if mode == "loop-keepall":
            scorer: Any = KeepAllScorer()
        elif mode == "loop-llm":
            scorer = verifier
        else:
            scorer = TwoStageScorer(relevance, verifier, cutoff=0.2)
        result = await ThinkLoop(llm, scorer, PRUNE).run(question)
        answer = result.answer
        stats = {"kept": result.kept, "dropped": result.dropped}
        if isinstance(scorer, TwoStageScorer):
            stats["prefiltered_out"] = scorer.stats.prefiltered_out
            stats["verified"] = scorer.stats.verified
    elapsed = time.perf_counter() - start
    await inner.aclose()
    return {
        "mode": mode,
        "seconds": round(elapsed, 1),
        "chat_calls": llm.calls,
        "verify_calls": verifier.calls,
        "prompt_tokens": llm.prompt_tokens + verifier.prompt_tokens,
        "completion_tokens": llm.completion_tokens + verifier.completion_tokens,
        "answer": answer.strip(),
        **stats,
    }


async def main(modes: Sequence[str]) -> None:
    s = Settings.from_env()
    relevance = LayaRelevanceScorer()  # ONE instance: the checkpoint is loaded once, not per run
    # warm-up: load the chat model and Laya so the first measured run is not penalised
    await run_mode("loop-2stage", s, "Diga olá.", relevance)
    all_runs: list[dict[str, Any]] = []
    for question in QUESTIONS:
        print(f"\n# {question}")
        for mode in modes:
            r = await run_mode(mode, s, question, relevance)
            all_runs.append({"question": question, **r})
            extra = ""
            if "kept" in r:
                extra = f" kept={len(r['kept'])} dropped={len(r['dropped'])}"
                if "prefiltered_out" in r:
                    extra += f" laya_filtered={r['prefiltered_out']} llm_verified={r['verified']}"
            print(
                f"{mode:13s} {r['seconds']:6.1f}s chat={r['chat_calls']} verify={r['verify_calls']} "
                f"tok_in={r['prompt_tokens']} tok_out={r['completion_tokens']}{extra}",
                flush=True,
            )
    out = Path("bench_runs_" + "_".join(modes) + ".json")
    out.write_text(json.dumps(all_runs, ensure_ascii=False, indent=1))
    print(f"\nraw answers saved to {out}")

    print("\nMean over questions")
    print(f"{'mode':13s} seconds  chat+verify calls  tokens_out")
    for mode in modes:
        rows = [r for r in all_runs if r["mode"] == mode]
        n = len(rows)
        print(
            f"{mode:13s} {sum(r['seconds'] for r in rows) / n:7.1f}  "
            f"{sum(r['chat_calls'] + r['verify_calls'] for r in rows) / n:17.1f}  "
            f"{sum(r['completion_tokens'] for r in rows) / n:10.0f}"
        )

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or MODES))
