import httpx

from chakmati.features.research.fetch import PageFetcher, chunk_text, extract_text
from chakmati.features.research.search import USER_AGENT

ARTICLE = """<html><head><title>Python 3.13</title></head><body>
<nav>Home | About | Login</nav>
<article><h1>Python 3.13 released</h1>
<p>Python 3.13 is the latest stable release of the Python programming language,
with a new interactive interpreter and experimental free-threading support.</p>
<p>The release also improves error messages and removes several deprecated modules,
so projects should review the migration notes before upgrading.</p></article>
<footer>Copyright</footer></body></html>"""


def test_extract_text_returns_main_content_without_boilerplate():
    text = extract_text(ARTICLE, "https://example.com/py313")
    assert "latest stable release" in text
    assert "Login" not in text


def test_extract_text_empty_when_nothing_to_extract():
    assert extract_text("<html><body></body></html>") == ""


def test_chunk_text_respects_max_chars_and_keeps_all_words():
    text = "Primeira frase curta. " * 30 + "\n\n" + "Segundo parágrafo aqui. " * 30
    chunks = chunk_text(text, max_chars=200)
    assert chunks and all(len(c) <= 200 for c in chunks)
    assert "".join(chunks).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")


def test_chunk_text_hard_splits_a_giant_sentence_and_drops_empties():
    assert chunk_text("") == []
    chunks = chunk_text("x" * 450, max_chars=200)
    assert [len(c) for c in chunks] == [200, 200, 50]


async def test_fetch_returns_body_and_sends_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html; charset=utf-8"})

    fetcher = PageFetcher(transport=httpx.MockTransport(handler))
    assert "Python 3.13" in await fetcher.fetch("https://example.com/a")
    assert seen["ua"] == USER_AGENT
    await fetcher.aclose()


async def test_fetch_returns_none_on_error_wrong_type_oversize_and_network_failure():
    def make(handler, **kw):
        return PageFetcher(transport=httpx.MockTransport(handler), **kw)

    assert await make(lambda r: httpx.Response(404)).fetch("https://x.test") is None
    pdf = lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    assert await make(pdf).fetch("https://x.test") is None
    big = lambda r: httpx.Response(200, text="a" * 5000, headers={"content-type": "text/html"})
    assert await make(big, max_bytes=1000).fetch("https://x.test") is None

    def boom(request):
        raise httpx.ConnectError("down")

    assert await make(boom).fetch("https://x.test") is None


async def test_fetcher_uses_a_custom_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="x", headers={"content-type": "text/plain"})

    fetcher = PageFetcher(transport=httpx.MockTransport(handler), user_agent="my-agent/1 (contact: a@b.c)")
    await fetcher.fetch("https://x.test")
    assert seen["ua"] == "my-agent/1 (contact: a@b.c)"
