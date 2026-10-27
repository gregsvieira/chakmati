from chakmati.loop.metered import MeteredLLM


class Inner:
    def __init__(self):
        self.last_usage = {}

    async def chat(self, messages):
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}
        return "ok"


class NoUsageInner:
    async def chat(self, messages):
        return "ok"


async def test_accumulates_calls_and_tokens():
    metered = MeteredLLM(Inner())
    assert await metered.chat([]) == "ok"
    await metered.chat([])
    assert metered.calls == 2
    assert metered.prompt_tokens == 20
    assert metered.completion_tokens == 10


async def test_inner_without_usage_still_counts_calls():
    metered = MeteredLLM(NoUsageInner())
    await metered.chat([])
    assert (metered.calls, metered.prompt_tokens, metered.completion_tokens) == (1, 0, 0)
