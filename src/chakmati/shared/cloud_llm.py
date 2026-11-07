"""A paid AI (an API key of Anthropic or OpenAI) as the chat model, with the local model behind it.

The Chakmati prefers the paid one: every call goes there first. When it answers that the limit is over (HTTP 429, or "credit balance too low"),
the local model (Ollama) takes over for the time the provider asked to wait (`Retry-After`, or a default), and the paid one is tried again after
that. Any other failure of the paid one (no network, a 5xx) is answered by the local model for that call only. A key the provider refuses
(401/403) is not retried for an hour, so a wrong key does not slow every answer.

An API key is not the chat subscription (Claude Pro, ChatGPT Plus...): those do not give access to an API, and the key is billed apart, by use.

The key arrives in the environment of the engine (CHAKMATI_CLOUD_API_KEY) and is only ever sent to the provider's own address."""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable

import httpx

log = logging.getLogger("chakmati.llm")

PROVIDERS = {
    "anthropic": {"url": "https://api.anthropic.com/v1/messages", "models": "https://api.anthropic.com/v1/models"},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "models": "https://api.openai.com/v1/models"},
}
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096
DEFAULT_COOLDOWN = 900.0  # seconds: how long the local model takes over when the provider did not say when the limit ends
KEY_REFUSED_COOLDOWN = 3600.0
MAX_COOLDOWN = 6 * 3600.0
_QUOTA_WORDS = ("credit balance", "insufficient_quota", "quota", "billing", "rate limit", "rate_limit", "overloaded")


class CloudError(Exception):
    """The paid AI could not answer this call (the local model answers it)."""


class LimitReached(CloudError):
    def __init__(self, retry_after: float, reason: str = "limit"):
        super().__init__(f"{reason}: wait {retry_after:.0f}s")
        self.retry_after = retry_after
        self.reason = reason


class KeyRefused(CloudError):
    pass


def _headers(provider: str, key: str) -> dict[str, str]:
    if provider == "anthropic":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    return {"authorization": f"Bearer {key}", "content-type": "application/json"}


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(max(float(response.headers.get("retry-after", "")), 1.0), MAX_COOLDOWN)
    except ValueError:
        return DEFAULT_COOLDOWN


def _raise_for(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    body = response.text[:400].lower()
    if response.status_code in (401, 403):
        raise KeyRefused(f"the provider refused the key (HTTP {response.status_code})")
    if response.status_code in (429, 402, 529) or (response.status_code == 400 and any(w in body for w in _QUOTA_WORDS)):
        raise LimitReached(_retry_after(response), f"HTTP {response.status_code}")
    raise CloudError(f"HTTP {response.status_code}")


def _with_schema(messages: list[dict[str, str]], schema: dict | None) -> list[dict[str, str]]:
    """The providers have no Ollama-style `format`: the shape is asked for in words, and callers parse the reply defensively anyway."""
    if schema is None:
        return messages
    ask = "Reply ONLY with a single JSON object that follows this JSON schema, with no text before or after it:\n" + json.dumps(schema, ensure_ascii=False)
    return [{"role": "system", "content": ask}, *messages]


class CloudClient:
    supports_schema = True

    def __init__(self, provider: str, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 120.0, max_tokens: int | None = None):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        self._provider, self._key, self._model, self._max_tokens = provider, api_key, model, max_tokens
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)
        self.last_usage: dict[str, int] = {}

    def _payload(self, messages: list[dict[str, str]], stream: bool) -> dict:
        if self._provider == "anthropic":
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            payload: dict = {"model": self._model, "max_tokens": self._max_tokens or ANTHROPIC_MAX_TOKENS, "messages": [m for m in messages if m["role"] != "system"], "stream": stream}
            if system:
                payload["system"] = system
            return payload
        payload = {"model": self._model, "messages": messages, "stream": stream}
        if self._max_tokens:
            payload["max_completion_tokens"] = self._max_tokens
        return payload

    async def chat(self, messages: list[dict[str, str]], schema: dict | None = None) -> str:
        try:
            response = await self._http.post(PROVIDERS[self._provider]["url"], headers=_headers(self._provider, self._key), json=self._payload(_with_schema(messages, schema), False))
        except httpx.HTTPError as e:
            raise CloudError(f"network: {type(e).__name__}") from e
        _raise_for(response)
        data = response.json()
        if self._provider == "anthropic":
            usage = data.get("usage", {})
            self.last_usage = {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0)}
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        self.last_usage = {"prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
        return data["choices"][0]["message"]["content"] or ""

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        try:
            async with self._http.stream("POST", PROVIDERS[self._provider]["url"], headers=_headers(self._provider, self._key), json=self._payload(messages, True)) as response:
                if response.status_code >= 400:
                    await response.aread()
                _raise_for(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if self._provider == "anthropic":
                        text = event.get("delta", {}).get("text", "") if event.get("type") == "content_block_delta" else ""
                    else:
                        choices = event.get("choices") or [{}]
                        text = choices[0].get("delta", {}).get("content") or ""
                    if text:
                        yield text
        except httpx.HTTPError as e:
            raise CloudError(f"network: {type(e).__name__}") from e

    async def aclose(self) -> None:
        await self._http.aclose()


class FallbackClient:
    """`primary` (the paid AI) first, `fallback` (the local model) when the primary is over its limit or cannot answer. `fallback` may be None
    (the person chose to run only on the paid AI): then a limit is an error the person is told about."""

    supports_schema = True

    def __init__(self, primary: CloudClient, fallback, clock: Callable[[], float] = time.monotonic):
        self._primary, self._fallback, self._clock = primary, fallback, clock
        self._blocked_until = 0.0
        self.reason = ""  # why the paid AI is not being used right now ("" = it is)
        self.last_usage: dict[str, int] = {}

    @property
    def active(self) -> str:
        return "cloud" if self._clock() >= self._blocked_until else "local"

    def _block(self, seconds: float, reason: str) -> None:
        self._blocked_until = self._clock() + seconds
        self.reason = reason
        log.warning("paid AI paused for %.0fs (%s); %s", seconds, reason, "the local model answers" if self._fallback else "no local model: answers fail")

    def _no_fallback(self) -> RuntimeError:
        return RuntimeError("O limite da sua assinatura de IA acabou e não há um modelo local instalado. Tente de novo mais tarde.")

    async def chat(self, messages: list[dict[str, str]], schema: dict | None = None) -> str:
        if self.active == "cloud":
            try:
                out = await self._primary.chat(messages, schema=schema)
                self.reason = ""
                self.last_usage = self._primary.last_usage
                return out
            except LimitReached as e:
                self._block(e.retry_after, e.reason)
            except KeyRefused as e:
                self._block(KEY_REFUSED_COOLDOWN, str(e))
            except CloudError as e:
                log.warning("paid AI failed for this call (%s)", e)
        if self._fallback is None:
            raise self._no_fallback()
        out = await self._fallback.chat(messages, schema=schema)
        self.last_usage = getattr(self._fallback, "last_usage", {})
        return out

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        started = False
        if self.active == "cloud":
            try:
                async for piece in self._primary.stream_chat(messages):
                    started = True
                    yield piece
                self.reason = ""
                return
            except LimitReached as e:
                if started:
                    raise
                self._block(e.retry_after, e.reason)
            except KeyRefused as e:
                if started:
                    raise
                self._block(KEY_REFUSED_COOLDOWN, str(e))
            except CloudError as e:
                if started:
                    raise
                log.warning("paid AI failed for this call (%s)", e)
        if self._fallback is None:
            raise self._no_fallback()
        async for piece in self._fallback.stream_chat(messages):
            yield piece

    async def preload(self) -> bool:
        return await self._fallback.preload() if self._fallback is not None else True

    async def aclose(self) -> None:
        await self._primary.aclose()
        if self._fallback is not None:
            await self._fallback.aclose()
