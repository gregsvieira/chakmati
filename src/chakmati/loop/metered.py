from chakmati.llm import ChatClient


class MeteredLLM:
    def __init__(self, inner: ChatClient):
        self._inner = inner
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def chat(self, messages: list[dict[str, str]]) -> str:
        out = await self._inner.chat(messages)
        self.calls += 1
        usage = getattr(self._inner, "last_usage", {})
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        return out
