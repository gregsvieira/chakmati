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


async def test_last_usage_is_recorded():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"content": "x"},
                "prompt_eval_count": 12,
                "eval_count": 34,
            },
        )

    client = make_client(handler)
    assert client.last_usage == {}
    await client.chat([{"role": "user", "content": "hi"}])
    await client.aclose()
    assert client.last_usage == {"prompt_tokens": 12, "completion_tokens": 34}


async def test_optional_keep_alive_and_num_predict_are_sent_only_when_set():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "x"}})

    plain = OllamaClient("http://ollama.test", "m", transport=httpx.MockTransport(handler))
    await plain.chat([{"role": "user", "content": "hi"}])
    tuned = OllamaClient(
        "http://ollama.test", "m", transport=httpx.MockTransport(handler), keep_alive="30m", num_predict=120
    )
    await tuned.chat([{"role": "user", "content": "hi"}])
    assert "keep_alive" not in bodies[0] and "options" not in bodies[0]
    assert bodies[1]["keep_alive"] == "30m" and bodies[1]["options"] == {"num_predict": 120}


async def test_preload_posts_an_empty_generate_and_never_raises():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"done": True})

    ok = OllamaClient("http://ollama.test", "m", transport=httpx.MockTransport(handler), keep_alive="10m")
    assert await ok.preload() is True
    assert seen["url"] == "http://ollama.test/api/generate"
    assert seen["body"] == {"model": "m", "prompt": "", "keep_alive": "10m", "stream": False}
    bad = OllamaClient("http://ollama.test", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert await bad.preload() is False
