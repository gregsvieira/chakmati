import asyncio
from dataclasses import dataclass

from chakmati.shared.llm import ChatClient
from chakmati.features.research.loop.parts import compose_messages, draft_messages, parse_parts
from chakmati.features.research.loop.prune import PruneConfig, prune
from chakmati.features.research.loop.scorer import PartScorer


@dataclass(frozen=True)
class LoopResult:
    answer: str
    kept: list[str]
    dropped: list[str]
    rounds: int


class ThinkLoop:
    def __init__(
        self,
        llm: ChatClient,
        scorer: PartScorer,
        prune_config: PruneConfig = PruneConfig(),
        max_rounds: int = 1,
        parts_per_round: int = 5,
    ):
        self._llm = llm
        self._scorer = scorer
        self._cfg = prune_config
        self._max_rounds = max_rounds
        self._k = parts_per_round

    async def run(self, question: str) -> LoopResult:
        kept: list[str] = []
        dropped: list[str] = []
        rounds = 0
        for _ in range(self._max_rounds):
            raw = await self._llm.chat(draft_messages(question, kept, self._k))
            drafts = [d for d in parse_parts(raw) if d not in kept]
            if not drafts:
                break
            rounds += 1
            scores = await asyncio.to_thread(self._scorer.score, question, drafts)
            survivors = prune(drafts, scores, self._cfg)
            dropped.extend(d for d in drafts if d not in survivors)
            kept.extend(survivors)
        answer = await self._llm.chat(compose_messages(question, kept))
        return LoopResult(answer, kept, dropped, rounds)
