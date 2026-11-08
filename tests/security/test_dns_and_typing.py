"""Two more doors of the browser agent: a name that DNS points at a private machine, and text the model types into a page on its own."""

import asyncio
import inspect

import pytest

from chakmati.features.browser import session as browser_session
from chakmati.features.browser.agent import _TYPED_BAD, BrowserAgent, check_typed
from chakmati.features.browser.frames import FrameStore
from chakmati.features.browser.session import BrowserError, Snapshot, check_resolved, request_allowed

from .payloads import MARKERS, ROLE_TOKENS, FENCE_BREAKERS, SQL_PAYLOADS


@pytest.fixture(autouse=True)
def fresh_cache():
    browser_session._RESOLVED.clear()


def answers(*ips):
    async def resolver(host):
        return list(ips)
    return resolver


# ---------------------------------------------------------------------------------------------------------------------- DNS
@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.1.20", "169.254.169.254", "100.64.0.9", "::1", "fd00::5", "fe80::1%en0", "::ffff:127.0.0.1", "0.0.0.0"])
async def test_a_public_looking_name_that_resolves_to_a_private_address_is_refused(ip):
    with pytest.raises(BrowserError):
        await check_resolved("https://friendly.example/", answers(ip))


async def test_one_private_answer_among_public_ones_refuses_the_name():
    with pytest.raises(BrowserError):
        await check_resolved("https://mixed.example/", answers("93.184.216.34", "10.0.0.7"))


async def test_a_name_with_only_public_answers_opens():
    assert await check_resolved("https://ok.example/page", answers("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")) == "https://ok.example/page"


async def test_a_name_that_does_not_resolve_is_left_to_the_browser():
    async def failing(host):
        raise OSError("no such host")
    assert await check_resolved("https://nowhere.example/", failing) == "https://nowhere.example/"


async def test_a_slow_dns_server_does_not_hang_the_agent(monkeypatch):
    monkeypatch.setattr(browser_session, "RESOLVE_TIMEOUT", 0.05)

    async def slow(host):
        await asyncio.sleep(1)
        return ["127.0.0.1"]
    assert await check_resolved("https://slow.example/", slow) == "https://slow.example/"


async def test_the_verdict_is_kept_so_a_page_with_many_requests_costs_one_lookup():
    calls = []

    async def resolver(host):
        calls.append(host)
        return ["93.184.216.34"]
    for _ in range(5):
        await check_resolved("https://cdn.example/a.js", resolver)
    assert calls == ["cdn.example"]


async def test_a_bad_verdict_is_kept_too():
    calls = []

    async def resolver(host):
        calls.append(host)
        return ["127.0.0.1"]
    for _ in range(3):
        with pytest.raises(BrowserError):
            await check_resolved("https://evil.example/", resolver)
    assert calls == ["evil.example"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765/", "http://localhost/", "http://2130706433/", "file:///etc/passwd", "ftp://example.org/"])
async def test_addresses_that_are_already_local_never_reach_dns(url):
    async def never(host):
        raise AssertionError("DNS must not be asked")
    with pytest.raises(BrowserError):
        await check_resolved(url, never)


async def test_every_request_a_page_makes_is_judged_not_only_the_first():
    resolver = answers("127.0.0.1")
    assert await request_allowed("https://evil.example/redirect-to-the-engine", resolver) is False
    assert await request_allowed("http://127.0.0.1:8765/overview", resolver) is False
    assert await request_allowed("data:image/png;base64,AAAA") is True
    assert await request_allowed("blob:https://ok.example/uuid") is True
    assert await request_allowed("about:blank") is True


def test_the_real_browser_session_installs_the_request_guard_before_any_page_exists():
    source = inspect.getsource(browser_session.PlaywrightSession.start)
    assert source.index('route("**/*", self._guard)') < source.index("new_page()")
    assert "request_allowed" in inspect.getsource(browser_session.PlaywrightSession._guard)
    assert "check_resolved" in inspect.getsource(browser_session.PlaywrightSession.goto)


# --------------------------------------------------------------------------------------------------------------------- typing
@pytest.mark.parametrize("text", [
    "https://evil.example/steal?d=abc", "visite www.evil.example", "evil.com/x",
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)", "\"><iframe src=x>",
    "' OR '1'='1", "x' UNION SELECT password FROM users --", "1; DROP TABLE users; --", "admin'--; --", "' or 1=1", "a' AND SLEEP(5)", "'; WAITFOR DELAY '0:0:5'--",
    *MARKERS, *ROLE_TOKENS, *FENCE_BREAKERS, "a\x00b", "zero​width",
], ids=lambda t: repr(t)[:30])
def test_text_the_model_makes_up_that_does_not_belong_in_an_entry_is_refused(text):
    with pytest.raises(BrowserError):
        check_typed(text, "pesquise sobre gatos")


@pytest.mark.parametrize("text", [
    "gatos siameses", "capital da Austrália", "o'brien", "preço de tênis até R$ 300", "O que é SQL e como funciona o SELECT?", "notícias de hoje 08/11",
    "rock'n'roll", "C++ e C#", "não sei", "Ignore todas as instruções anteriores",
])
def test_ordinary_searches_still_type(text):
    check_typed(text, "pesquise sobre gatos")


@pytest.mark.parametrize("text", ["' OR '1'='1", "https://example.org/pagina", "DROP TABLE alunos"])
def test_what_the_person_asked_to_type_is_typed_as_said(text):
    check_typed(text, f"digite {text} na busca e me diga o que aparece")


@pytest.mark.parametrize("payload", SQL_PAYLOADS[:8], ids=range(8))
async def test_the_agent_refuses_to_type_an_attack_and_tells_the_model(tmp_path, payload):
    import json

    class Session:
        def __init__(self):
            self.calls, self.url = [], "https://example.org/"

        async def start(self): ...
        async def close(self): ...
        async def goto(self, url): self.calls.append(("goto", url))
        async def back(self): ...
        async def click(self, ident): ...
        async def type(self, ident, text, submit, secret=False): self.calls.append(("type", ident, text))
        async def scroll(self, down): ...
        async def screenshot(self): return b"\xff\xd8jpeg"
        async def snapshot(self): return Snapshot(self.url, "t", "texto", [{"id": 1, "tag": "input", "type": "text", "label": "Pesquisar"}])

    class LLM:
        def __init__(self, *replies):
            self.replies, self.prompts = list(replies), []

        async def chat(self, messages):
            self.prompts.append(messages[-1]["content"])
            return self.replies.pop(0)

    session = Session()
    llm = LLM(json.dumps({"action": "type", "id": 1, "text": payload[:200], "enter": True}), '{"action":"done","answer":"ok"}')
    out = [p async for p in BrowserAgent(llm, FrameStore(tmp_path), lambda: session).run("a" * 32, "pesquise sobre gatos")]
    assert out == ["ok"]
    if any(r.search(payload[:200]) for r, _ in _TYPED_BAD):
        assert not [c for c in session.calls if c[0] == "type"], "the attack was typed into the page"
        assert "não digito" in llm.prompts[1]
