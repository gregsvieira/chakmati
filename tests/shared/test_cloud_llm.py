import json

import httpx
import pytest

from chakmati.shared.cloud_llm import CloudClient, CloudError, FallbackClient, KeyRefused, LimitReached
from chakmati.shared.config import Settings
from chakmati.main import _chat_client
from chakmati.shared.llm import OllamaClient

MSGS = [{"role": "system", "content": "Seja breve."}, {"role": "user", "content": "oi"}]


def transport(handler):
    return httpx.MockTransport(handler)


def anthropic_ok(request):
    return httpx.Response(200, json={"content": [{"type": "text", "text": "olá"}], "usage": {"input_tokens": 5, "output_tokens": 2}})


def openai_ok(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": "olá"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})


async def test_anthropic_request_shape_and_reply():
    seen = {}

    def handler(request):
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        return anthropic_ok(request)

    c = CloudClient("anthropic", "sk-ant-xxx", "m1", transport=transport(handler))
    assert await c.chat(MSGS) == "olá"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-xxx" and "authorization" not in seen["headers"]
    assert seen["body"]["system"] == "Seja breve." and seen["body"]["messages"] == [{"role": "user", "content": "oi"}]
    assert seen["body"]["max_tokens"] > 0
    assert c.last_usage == {"prompt_tokens": 5, "completion_tokens": 2}


async def test_openai_request_shape_and_reply():
    seen = {}

    def handler(request):
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        return openai_ok(request)

    c = CloudClient("openai", "sk-xxx", "m2", transport=transport(handler))
    assert await c.chat(MSGS) == "olá"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-xxx"
    assert seen["body"]["messages"] == MSGS


async def test_a_schema_is_asked_for_in_words():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return anthropic_ok(request)

    await CloudClient("anthropic", "k", "m", transport=transport(handler)).chat(MSGS, schema={"type": "object"})
    assert "JSON schema" in seen["body"]["system"] and '"type": "object"' in seen["body"]["system"]


def test_an_unknown_provider_is_refused():
    with pytest.raises(ValueError):
        CloudClient("nope", "k", "m")


@pytest.mark.parametrize("status,headers,body,exc", [
    (429, {"retry-after": "30"}, {}, LimitReached),
    (429, {}, {}, LimitReached),
    (402, {}, {}, LimitReached),
    (400, {}, {"error": {"message": "Your credit balance is too low"}}, LimitReached),
    (401, {}, {}, KeyRefused),
    (403, {}, {}, KeyRefused),
    (500, {}, {}, CloudError),
])
async def test_errors_are_classified(status, headers, body, exc):
    c = CloudClient("anthropic", "k", "m", transport=transport(lambda r: httpx.Response(status, headers=headers, json=body)))
    with pytest.raises(exc):
        await c.chat(MSGS)


async def test_retry_after_is_honoured():
    c = CloudClient("openai", "k", "m", transport=transport(lambda r: httpx.Response(429, headers={"retry-after": "42"})))
    with pytest.raises(LimitReached) as e:
        await c.chat(MSGS)
    assert e.value.retry_after == 42


async def test_a_network_failure_is_a_cloud_error():
    def boom(request):
        raise httpx.ConnectError("x")

    with pytest.raises(CloudError):
        await CloudClient("openai", "k", "m", transport=transport(boom)).chat(MSGS)


async def test_streaming_anthropic_and_openai():
    a = "\n".join(['data: {"type":"content_block_delta","delta":{"text":"ol"}}', "", 'data: {"type":"content_block_delta","delta":{"text":"á"}}', "", 'data: {"type":"message_stop"}', ""])
    o = "\n".join(['data: {"choices":[{"delta":{"content":"ol"}}]}', "", 'data: {"choices":[{"delta":{"content":"á"}}]}', "", "data: [DONE]", ""])
    for provider, body in (("anthropic", a), ("openai", o)):
        c = CloudClient(provider, "k", "m", transport=transport(lambda r, body=body: httpx.Response(200, text=body)))
        assert "".join([p async for p in c.stream_chat(MSGS)]) == "olá"


class Local:
    supports_schema = True

    def __init__(self):
        self.calls = 0
        self.last_usage = {"prompt_tokens": 1, "completion_tokens": 1}

    async def chat(self, messages, schema=None):
        self.calls += 1
        return "local"

    async def stream_chat(self, messages):
        self.calls += 1
        yield "lo"
        yield "cal"

    async def preload(self):
        return True

    async def aclose(self):
        pass


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def cloud(handler):
    return CloudClient("anthropic", "k", "m", transport=transport(handler))


async def test_the_paid_ai_is_used_first():
    local = Local()
    f = FallbackClient(cloud(anthropic_ok), local)
    assert await f.chat(MSGS) == "olá" and local.calls == 0 and f.active == "cloud"


async def test_after_the_limit_the_local_model_takes_over_and_the_paid_one_is_not_asked_again_until_it_ends():
    clock, local, hits = Clock(), Local(), []

    def handler(request):
        hits.append(1)
        return httpx.Response(429, headers={"retry-after": "60"}) if len(hits) == 1 else anthropic_ok(request)

    f = FallbackClient(cloud(handler), local, clock=clock)
    assert await f.chat(MSGS) == "local"              # the 429: answered by the local model, in the same call
    assert f.active == "local" and len(hits) == 1
    clock.t += 30
    assert await f.chat(MSGS) == "local" and len(hits) == 1   # still inside the wait: the paid one is not even asked
    clock.t += 31
    assert f.active == "cloud"
    assert await f.chat(MSGS) == "olá" and len(hits) == 2     # the wait is over: back to the paid one


async def test_a_refused_key_pauses_for_an_hour_and_a_plain_failure_only_for_that_call():
    clock, local = Clock(), Local()
    f = FallbackClient(cloud(lambda r: httpx.Response(401)), local, clock=clock)
    assert await f.chat(MSGS) == "local" and f.active == "local"
    clock.t += 3000
    assert f.active == "local"
    clock.t += 700
    assert f.active == "cloud"
    g = FallbackClient(cloud(lambda r: httpx.Response(500)), Local(), clock=Clock())
    assert await g.chat(MSGS) == "local" and g.active == "cloud"   # a 5xx does not pause it


async def test_without_a_local_model_the_limit_is_a_clear_error():
    f = FallbackClient(cloud(lambda r: httpx.Response(429)), None)
    with pytest.raises(RuntimeError, match="limite da sua assinatura"):
        await f.chat(MSGS)
    assert await f.preload() is True


async def test_streaming_falls_back_before_the_first_piece_but_not_in_the_middle():
    f = FallbackClient(cloud(lambda r: httpx.Response(429)), Local())
    assert "".join([p async for p in f.stream_chat(MSGS)]) == "local"
    cut = "\n".join(['data: {"type":"content_block_delta","delta":{"text":"ol"}}', ""])

    def handler(request):
        return httpx.Response(200, text=cut)

    g = FallbackClient(cloud(handler), Local())
    assert "".join([p async for p in g.stream_chat(MSGS)]) == "ol"


def test_the_engine_builds_the_paid_client_only_when_a_provider_key_and_model_are_set():
    local = OllamaClient("http://x", "qwen")
    assert _chat_client(Settings(), local) is local
    assert _chat_client(Settings(cloud_provider="openai", cloud_api_key="k"), local) is local   # no model: not enabled
    f = _chat_client(Settings(cloud_provider="openai", cloud_api_key="k", cloud_model="m"), local)
    assert isinstance(f, FallbackClient) and f._fallback is local
    assert _chat_client(Settings(cloud_provider="openai", cloud_api_key="k", cloud_model="m", local_model=False), local)._fallback is None


def test_settings_read_the_environment():
    s = Settings.from_env({"CHAKMATI_CLOUD_PROVIDER": "anthropic", "CHAKMATI_CLOUD_API_KEY": "k", "CHAKMATI_CLOUD_MODEL": "m", "CHAKMATI_LOCAL_MODEL": "0"})
    assert (s.cloud_provider, s.cloud_api_key, s.cloud_model, s.local_model) == ("anthropic", "k", "m", False)
    assert Settings.from_env({}).local_model is True
