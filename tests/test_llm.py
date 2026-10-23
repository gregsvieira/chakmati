import json

import httpx
import pytest

from liteagent.llm import OllamaClient


def make_client(handler, think=False):
    return OllamaClient(
        "http://ollama.test",
        "qwen3.5:latest",
        think=think,
        transport=httpx.MockTransport(handler),
    )


async def test_chat_sends_think_false_and_returns_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Olá!"}})

    client = make_client(handler)
    out = await client.chat([{"role": "user", "content": "olá"}])
    await client.aclose()

    assert out == "Olá!"
    assert seen["url"] == "http://ollama.test/api/chat"
    assert seen["body"] == {
        "model": "qwen3.5:latest",
        "messages": [{"role": "user", "content": "olá"}],
        "stream": False,
        "think": False,
    }


async def test_think_can_be_enabled():
    seen = {}

    def handler(request):
        seen["think"] = json.loads(request.content)["think"]
        return httpx.Response(200, json={"message": {"content": "x"}})

    client = make_client(handler, think=True)
    await client.chat([{"role": "user", "content": "hi"}])
    await client.aclose()
    assert seen["think"] is True


async def test_http_error_raises():
    client = make_client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat([{"role": "user", "content": "hi"}])
    await client.aclose()
