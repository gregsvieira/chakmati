"""The page snapshot and the wait after a click, run in a real headless Chrome on a local page (skipped without Chrome)."""

import shutil
import sys

import pytest

from chakmati.browser.session import PlaywrightSession

CHROME = sys.platform == "darwin" and shutil.which("open") and __import__("os").path.exists("/Applications/Google Chrome.app")
pytestmark = pytest.mark.skipif(not CHROME, reason="needs Google Chrome installed")

PAGE = """<html><body>
<header style="position:sticky;top:0"><form><textarea placeholder="Search"></textarea></form></header>
<div class="promo-module__root" style="position:fixed;bottom:10px;right:10px;width:240px;height:120px">
  <button>Dismiss promotion</button><br><a href="#x">Install our browser</a></div>
<div class="drawer-promotion-wrap"><form><input type="text" placeholder="real search box"></form></div>
<a href="#r1">Result one</a>
<a id="go" href="#" onclick="setTimeout(()=>{history.pushState({}, '', '/next'); document.title='after'}, 300); return false">Go</a>
</body></html>"""


@pytest.fixture
async def session(tmp_path):
    s = PlaywrightSession(str(tmp_path / "profile"), headless=True)
    await s.start()
    await s._page.route("https://example.test/**", lambda route: route.fulfill(body=PAGE, content_type="text/html"))
    await s.goto("https://example.test/start")
    yield s
    await s.close()


async def test_banners_are_marked_and_listed_last_but_search_boxes_never_are(session):
    elements = (await session.snapshot()).elements
    by_label = {e["label"]: e for e in elements}
    assert by_label["Dismiss promotion"]["overlay"] and by_label["Install our browser"]["overlay"]
    assert not by_label["Search"]["overlay"] and not by_label["real search box"]["overlay"]  # inside a form: the page itself, even in a "promotion" wrapper
    assert not by_label["Result one"]["overlay"]
    assert [e["overlay"] for e in elements] == sorted(e["overlay"] for e in elements)  # the page's own things first


async def test_after_a_click_the_snapshot_waits_for_the_page_to_change(session):
    link = next(e["id"] for e in (await session.snapshot()).elements if e["label"] == "Go")
    await session.click(link)
    snap = await session.snapshot()
    assert snap.title == "after" and snap.url.endswith("/next")


async def test_a_page_that_redirects_while_it_is_read_is_waited_for(tmp_path):
    s = PlaywrightSession(str(tmp_path / "profile2"), headless=True)
    await s.start()
    try:
        async def route(r):
            body = "<html><title>A</title><body><script>setTimeout(() => { location.href = 'https://example.test/b'; }, 5)</script>a</body></html>" if r.request.url.endswith("/a") else "<html><title>B</title><body><a href='#x'>link</a></body></html>"
            await r.fulfill(body=body, content_type="text/html")
        await s._page.route("https://example.test/**", route)
        await s._page.goto("https://example.test/a", wait_until="commit")
        snap = await s.snapshot()
        assert snap.url.startswith("https://example.test/")   # (the point: no "Execution context was destroyed"; which of the two pages it caught is a matter of timing)
    finally:
        await s.close()
