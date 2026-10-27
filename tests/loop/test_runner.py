from chakmati.loop.runner import ThinkLoop


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


class KeywordScorer:
    """0.9 for parts containing 'útil', else 0.1."""

    def score(self, question, parts):
        return [0.9 if "útil" in p else 0.1 for p in parts]


async def test_one_round_prunes_and_composes_from_survivors_only():
    llm = ScriptedLLM(['["fato útil 1", "ruído", "fato útil 2"]', "resposta final"])
    result = await ThinkLoop(llm, KeywordScorer()).run("Q?")

    assert result.answer == "resposta final"
    assert result.kept == ["fato útil 1", "fato útil 2"]
    assert result.dropped == ["ruído"]
    assert result.rounds == 1
    assert len(llm.calls) == 2
    compose_user = llm.calls[1][1]["content"]
    assert "fato útil 1" in compose_user and "ruído" not in compose_user


async def test_second_round_sees_only_kept_notes():
    llm = ScriptedLLM(['["a útil", "b"]', '["c útil", "d"]', "final"])
    result = await ThinkLoop(llm, KeywordScorer(), max_rounds=2).run("Q?")

    assert result.kept == ["a útil", "c útil"]
    assert result.dropped == ["b", "d"]
    assert result.rounds == 2
    second_draft_user = llm.calls[1][1]["content"]
    assert "a útil" in second_draft_user and "b" not in second_draft_user.split("Notes so far:")[1]
    assert len(llm.calls) == 3


async def test_repeated_drafts_are_not_added_twice():
    llm = ScriptedLLM(['["a útil"]', '["a útil"]', "final"])
    result = await ThinkLoop(llm, KeywordScorer(), max_rounds=2).run("Q?")
    assert result.kept == ["a útil"]
    assert result.rounds == 1


async def test_no_drafts_still_composes():
    llm = ScriptedLLM(["", "final"])
    result = await ThinkLoop(llm, KeywordScorer()).run("Q?")
    assert result.answer == "final"
    assert result.kept == [] and result.rounds == 0
    assert len(llm.calls) == 2


async def test_min_keep_floor_keeps_best_even_if_all_low():
    llm = ScriptedLLM(['["x", "y"]', "final"])
    result = await ThinkLoop(llm, KeywordScorer()).run("Q?")
    assert len(result.kept) == 1
    assert len(result.dropped) == 1
