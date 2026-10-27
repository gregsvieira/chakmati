"""A real, visible Chrome driven with Playwright (the `browser` extra).

Playwright talks to the Chrome that is already installed (`channel="chrome"`), so there is no driver to match to the
browser's version and nothing extra to download. The profile is a folder of its own, never the person's everyday one:
no saved logins or history are reachable, and a Chrome that is already open does not get in the way."""

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from chakmati.extras import missing_message

VIEWPORT = {"width": 1280, "height": 800}
MAX_TEXT = 4500
MAX_ELEMENTS = 60

# Marks what can be clicked or typed into with a number and returns a compact description of the page.
_SNAPSHOT_JS = """
(max) => {
  document.querySelectorAll('[data-ck]').forEach((e) => e.removeAttribute('data-ck'));
  const cands = [];
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=textbox],[role=radio],[role=checkbox],[role=option],[role=tab],[contenteditable=true],label,[onclick],[tabindex]:not([tabindex="-1"])';
  // things made of plain boxes that act as buttons (size pickers, "add" buttons): the pointer cursor says they are clickable, only for what is on the screen
  const extra = Array.from(document.querySelectorAll('div,span,li,p,img')).filter((e) => { const r = e.getBoundingClientRect(); return r.width >= 8 && r.height >= 8 && r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0 && getComputedStyle(e).cursor === 'pointer' && !e.parentElement.closest('a[href],button,[role=button],[role=link]') && !(e.parentElement && getComputedStyle(e.parentElement).cursor === 'pointer') && (e.innerText || '').length < 60; });
  for (const found of new Set([...document.querySelectorAll(sel), ...extra])) {
    // a custom checkbox hides the real input (a few pixels, or none): its label is what is on the screen and what gets clicked
    const tiny = found.matches('input[type=checkbox],input[type=radio]') && (found.getBoundingClientRect().width < 8 || found.getBoundingClientRect().height < 8);
    const el = tiny ? ((found.labels && found.labels[0]) || found.closest('label') || found.parentElement || found) : found;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.bottom < 0 || r.top > innerHeight * 3 || r.right < 0 || r.left > innerWidth) continue;
    // something else on top of it (a closed menu, a hidden panel, an overlay): a click would never land, so do not offer it
    if (r.top >= 0 && r.top < innerHeight) {
      const hit = document.elementFromPoint(Math.min(r.left + r.width / 2, innerWidth - 1), Math.min(r.top + r.height / 2, innerHeight - 1));
      if (!hit || !(el.contains(hit) || hit.contains(el))) continue;
    }
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;   // faded out or hidden by an ancestor
    // banners, pop-ups and floating panels (not the page itself): the model is told to leave them alone unless it has to close one
    let overlay = false;
    const structural = el.matches('input,textarea,select') || !!el.closest('form,header,nav,[role=search],[role=banner]');  // a search box or menu in a sticky bar is the page itself
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (!structural && (cs.position === 'fixed' || cs.position === 'sticky') && a.getBoundingClientRect().height < innerHeight * 0.6) { overlay = true; break; }
      if (!structural && a.matches('[role=dialog],[aria-modal=true],[class*=banner i],[class*=promo i],[class*=popup i],[class*=cookie i],[id*=banner i],[id*=promo i],[id*=cookie i]')) { overlay = true; break; }
    }
    // what is read first: the page body on the screen, then the menus and footers on the screen, then what is below (the model sees only `max` of them)
    const inView = r.top < innerHeight && r.bottom > 0;
    const chrome = !!el.closest('header,nav,footer,[role=banner],[role=navigation],[role=contentinfo]');
    const rank = (inView ? (overlay ? 2 : chrome ? 1 : 0) : 3 + (chrome ? 1 : 0));   // banners on the screen still come before what is below: they have to be closable
    const own = found.labels && found.labels[0] ? found.labels[0].innerText : '';
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || own || (found.type === 'checkbox' || found.type === 'radio' ? (el.innerText || (found.parentElement ? found.parentElement.innerText : '')) : '') || el.placeholder || el.getAttribute('title') || el.getAttribute('name') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    cands.push({ el, rank, order: cands.length, tag: found.tagName.toLowerCase(), type: found.getAttribute('type') || '', label, overlay, cls: String((el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className) || '').slice(0, 80) });
  }
  cands.sort((x, y) => x.rank - y.rank || x.order - y.order);
  const out = cands.slice(0, max).map((c, i) => { c.el.setAttribute('data-ck', String(i + 1)); return { id: i + 1, tag: c.tag, type: c.type, label: c.label, overlay: c.overlay, cls: c.cls }; });
  return { elements: out, text: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim() };
}
"""


@dataclass(frozen=True)
class Snapshot:
    url: str
    title: str
    text: str
    elements: list[dict]


class BrowserError(Exception):
    pass


def check_navigable(url: str) -> str:
    """Only http(s) pages on the public internet: never a local file, the engine itself, or the home network."""
    if "://" not in url and re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", url.strip(), re.IGNORECASE):  # javascript:, data:, mailto: ...
        raise BrowserError("só abro endereços http(s)")
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise BrowserError("só abro endereços http(s)")
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")) or host.startswith(("127.", "10.", "192.168.", "169.254.", "0.")) \
            or (host.startswith("172.") and host.split(".")[1:2] and host.split(".")[1].isdigit() and 16 <= int(host.split(".")[1]) <= 31) or host in {"::1", "[::1]"}:
        raise BrowserError("não abro endereços locais ou da rede da casa")
    return parsed.geturl()


class PlaywrightSession:
    def __init__(self, profile_dir: str, headless: bool = False):
        self._profile = os.path.expanduser(profile_dir)
        self._headless = headless
        self._pw = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserError(missing_message("browser", "The browser agent")) from exc
        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                self._profile, channel="chrome", headless=self._headless, viewport=VIEWPORT,
            )  # no stealth flags or user-agent changes: a site that asks for a human check gets a stop, not a workaround
        except Exception as exc:
            await self._pw.stop()
            raise BrowserError(f"não consegui abrir o Chrome (ele precisa estar instalado): {exc}") from exc
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    @property
    def visible(self) -> bool:
        return not self._headless

    async def reopen_visible(self) -> None:
        """Closes the browser and opens the same profile (cookies and all) in a window the person can see, at the same page: for a human check
        that only a person can pass. The Chakmati does not try to pass it."""
        url = self._page.url if self._page is not None else ""
        await self.close()
        self._headless = False
        await self.start()
        if url and url != "about:blank":
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._settle()

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._pw is not None:
            await self._pw.stop()
        self._context = self._pw = self._page = None

    async def goto(self, url: str) -> None:
        await self._page.goto(check_navigable(url), wait_until="domcontentloaded", timeout=30_000)
        await self._settle()

    async def back(self) -> None:
        await self._page.go_back(wait_until="domcontentloaded", timeout=15_000)
        await self._settle()

    async def _settle(self, navigating: bool = False) -> None:
        if navigating:  # a click or Enter starts a navigation a moment later: without this the address and picture are the old page's
            await self._page.wait_for_timeout(700)
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=8_000)
            except Exception:
                pass
        try:
            await self._page.wait_for_load_state("networkidle", timeout=4_000)
        except Exception:
            pass  # pages that never go quiet are fine: what is on screen now is what we use

    async def click(self, ident: int) -> None:
        await self._page.locator(f'[data-ck="{int(ident)}"]').first.click(timeout=4_000)
        await self._settle(navigating=True)

    async def type(self, ident: int, text: str, submit: bool, secret: bool = False) -> None:
        box = self._page.locator(f'[data-ck="{int(ident)}"]').first
        if (await box.get_attribute("type") or "").lower() == "password" and not secret:
            raise BrowserError("uma senha só é digitada se você me der: eu pergunto na conversa")
        await box.fill(text, timeout=8_000)
        if submit:
            await box.press("Enter")
            await self._settle(navigating=True)

    async def scroll(self, down: bool) -> None:
        await self._page.mouse.wheel(0, 700 if down else -700)
        await self._page.wait_for_timeout(300)

    def _follow(self) -> None:
        """A check solved by the person may open (or move to) another tab: what is read and shown is the newest one that is still open."""
        open_pages = [pg for pg in (self._context.pages if self._context else []) if not pg.is_closed()]
        if open_pages and self._page not in open_pages:
            self._page = open_pages[-1]
        elif len(open_pages) > 1 and self._page is not open_pages[-1] and self._page.url in ("", "about:blank"):
            self._page = open_pages[-1]

    async def snapshot(self) -> Snapshot:
        self._follow()
        # shops redirect and reload after the first load: a page that changes under our feet is waited for and read again
        for attempt in range(4):
            try:
                data = await self._page.evaluate(_SNAPSHOT_JS, MAX_ELEMENTS)
                return Snapshot(self._page.url, await self._page.title(), data["text"][:MAX_TEXT], data["elements"])
            except Exception as exc:
                if attempt == 3 or not any(m in str(exc) for m in ("context was destroyed", "navigat", "Target closed")):
                    raise
                await self._settle(navigating=True)

    async def screenshot(self) -> bytes:
        return await self._page.screenshot(type="jpeg", quality=60)
