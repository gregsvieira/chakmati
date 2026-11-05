import json
import re
from collections.abc import AsyncIterator
from typing import Protocol

import httpx


class ChatClient(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> str: ...


async def chat_json(client: ChatClient, messages: list[dict[str, str]], schema: dict) -> str:
    """Ask for a JSON reply that follows `schema`. A client that can constrain the output (Ollama's `format`) is made to; any other
    client (a test double, another backend) just gets the plain call, so callers keep parsing the reply defensively either way."""
    if getattr(client, "supports_schema", False):
        return await client.chat(messages, schema=schema)  # type: ignore[call-arg]
    return await client.chat(messages)


def is_small_model(name: str) -> bool:
    """A chat model of about 4B parameters or less (qwen3.5:0.8b, granite4:3b, lfm3...): it gets the shorter prompt with examples and a
    request in several parts read one part at a time. A name with no size in it (qwen3.5:latest) is treated as big."""
    if re.search(r"lfm\d|micro", name.lower()):
        return True
    m = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)b\b", name.lower())
    return bool(m) and float(m.group(1)) <= 4


class StreamingChatClient(ChatClient, Protocol):
    def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class OllamaClient:
    supports_schema = True

    def __init__(
        self,
        base_url: str,
        model: str,
        think: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 300.0,
        keep_alive: str | None = None,
        num_predict: int | None = None,
    ):
        self._model = model
        self._think = think
        self._keep_alive = keep_alive
        self._num_predict = num_predict
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout
        )
        self.last_usage: dict[str, int] = {}

    def _payload(self, messages: list[dict[str, str]], stream: bool, schema: dict | None = None) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "think": self._think,
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        options: dict = {"num_predict": self._num_predict} if self._num_predict else {}
        if schema is not None:
            payload["format"] = schema  # the reply can only be a JSON object of this shape (grammar-constrained decoding)
            options["temperature"] = 0  # reading a request is not creative: the same request gets the same steps
        if options:
            payload["options"] = options
        return payload

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield the reply piece by piece as Ollama produces it (thinking tokens are skipped)."""
        async with self._http.stream("POST", "/api/chat", json=self._payload(messages, True)) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise RuntimeError(data["error"])
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content

    async def chat(self, messages: list[dict[str, str]], schema: dict | None = None) -> str:
        payload = self._payload(messages, False, schema)
        response = await self._http.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        self.last_usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return data["message"]["content"]

    async def preload(self) -> bool:
        """Load the model into memory ahead of the first request. Never raises."""
        payload: dict = {"model": self._model, "prompt": "", "stream": False}
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        try:
            response = await self._http.post("/api/generate", json=payload)
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    async def aclose(self) -> None:
        await self._http.aclose()
