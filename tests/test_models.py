import httpx
import pytest

from liteagent.models import ModelCatalog

GB = 1024**3


def transport(models):
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": n, "size": int(s * GB)} for n, s in models.items()]})
    return httpx.MockTransport(handler)


def catalog(models, ram=16.0, configured="", **kw):
    return ModelCatalog("http://ollama.test", configured=configured, ram_gb=ram, transport=transport(models), **kw)


async def test_the_best_installed_reasoning_model_is_found_without_being_told():
    c = catalog({"qwen3.5:latest": 6.1, "deepseek-r1:8b": 5.2, "deepseek-r1:14b": 8.4})
    choice = await c.reasoning()
    assert choice.model == "deepseek-r1:14b" and "instalado" in choice.why


async def test_a_weak_computer_does_not_get_a_model_it_cannot_run():
    c = catalog({"deepseek-r1:14b": 8.4}, ram=8.0)
    choice = await c.reasoning()
    assert choice.model is None and "pouca memória" in choice.why  # 8.4 GB x 1.4 + 1.5 > 8


async def test_a_smaller_installed_model_is_used_when_the_big_one_does_not_fit():
    c = catalog({"deepseek-r1:14b": 8.4, "deepseek-r1:8b": 4.9}, ram=12.0)
    assert (await c.reasoning()).model == "deepseek-r1:8b"  # 4.9 x 1.4 + 1.5 = 8.4 fits; 13.3 does not


async def test_without_a_reasoning_model_the_standard_one_is_used_and_the_person_is_told():
    choice = await catalog({"qwen3.5:latest": 6.1}).reasoning()
    assert choice.model is None and "não há modelo de raciocínio instalado" in choice.why and "instalador" in choice.why


async def test_a_model_named_by_the_person_is_trusted():
    assert (await catalog({}, configured="my-model:7b").reasoning()).model == "my-model:7b"


async def test_when_ollama_does_not_answer_nothing_breaks():
    def boom(request):
        raise httpx.ConnectError("down")
    c = ModelCatalog("http://ollama.test", ram_gb=16, transport=httpx.MockTransport(boom))
    assert await c.installed() == {} and (await c.reasoning()).model is None


async def test_the_list_is_cached_for_a_while():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"models": []})
    t = [0.0]
    c = ModelCatalog("http://ollama.test", ram_gb=16, transport=httpx.MockTransport(handler), ttl=30, now=lambda: t[0])
    await c.installed(); await c.installed()
    t[0] = 31
    await c.installed()
    assert len(calls) == 2
