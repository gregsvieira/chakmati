"""Connecting to Home Assistant without copying anything: find it on the network, send the person to ITS login page, take the answer.

The person's part is one click on "Aprovar" in their own Home Assistant. No token is shown, copied or typed. It is the same sign-in that Home
Assistant's own phone app uses (https://developers.home-assistant.io/docs/auth_api): the Chakmati asks for access, Home Assistant sends the browser
back to the engine with a one-time code, and the code is exchanged for tokens that are kept in a file only the person's user can read.

Only addresses of the person's own network are accepted (a name ending in .local, a private IP, a name with no dot): the engine never sends a
sign-in to a stranger's server."""

import asyncio
import ipaddress
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx

from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.models import HomeError

CANDIDATES = ("http://homeassistant.local:8123", "http://homeassistant:8123")  # the names a Home Assistant answers to by default
STATE_TTL_SECONDS = 600.0
HOME_ASSISTANT = "Home Assistant"


def lan_url(raw: str) -> str:
    """"192.168.0.10", "homeassistant.local:8123" or a full address -> "http://host:port"; HomeError for anything that is not on the person's own network."""
    text = (raw or "").strip()
    if not text:
        raise HomeError("escreva o endereço do Home Assistant, por exemplo 192.168.0.10")
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        raise HomeError("esse endereço não parece válido") from None
    if parts.scheme not in ("http", "https") or not host:
        raise HomeError("esse endereço não parece válido")
    try:
        ip = ipaddress.ip_address(host)
        local = ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        local = host == "localhost" or host.endswith(".local") or "." not in host
    if not local:
        raise HomeError("só aceito um Home Assistant da sua rede (um endereço como 192.168.0.10 ou homeassistant.local), não da internet")
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port or 8123}"


async def probe(url: str, http: httpx.AsyncClient) -> dict | None:
    """{"url", "name"} when a Home Assistant answers at `url`, otherwise None. Reads only public pages: nothing is sent to it."""
    for path in ("/manifest.json", "/api/discovery_info"):
        try:
            response = await http.get(url + path, timeout=2.5)
            data = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            continue
        if isinstance(data, dict) and (HOME_ASSISTANT in str(data.get("name", "")) or "location_name" in data):
            return {"url": url, "name": str(data.get("location_name") or data.get("name") or HOME_ASSISTANT)}
    return None


async def discover(http: httpx.AsyncClient, candidates=CANDIDATES) -> list[dict]:
    found = [f for f in await asyncio.gather(*(probe(u, http) for u in candidates)) if f]
    seen, out = set(), []
    for item in found:
        if item["name"] not in seen:  # two names that lead to the same house are one house
            seen.add(item["name"])
            out.append(item)
    return out


class HomeConnector:
    """One sign-in at a time: `start` gives the page to open, `finish` receives what Home Assistant sends back."""

    def __init__(self, auth: HomeAuth, http: httpx.AsyncClient, now=time.time):
        self._auth, self._http, self._now = auth, http, now
        self._pending: dict | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None and self._now() < self._pending["expires"]

    def start(self, url: str, engine_base: str) -> str:
        """The address of the Home Assistant page where the person approves. `engine_base` is where the browser comes back to (the engine itself)."""
        home = lan_url(url)
        base = engine_base if engine_base.endswith("/") else engine_base + "/"
        host = urlsplit(base).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise HomeError("a conexão só pode ser iniciada pelo próprio aplicativo")
        state = secrets.token_urlsafe(24)
        self._pending = {"state": state, "url": home, "client_id": base, "redirect": base + "home/callback", "expires": self._now() + STATE_TTL_SECONDS}
        return f"{home}/auth/authorize?" + urlencode({"client_id": base, "redirect_uri": base + "home/callback", "state": state})

    async def finish(self, state: str, code: str) -> str:
        """Exchanges the one-time code for the tokens and keeps them. Returns the Home Assistant address. The state must be the one that was given out."""
        pending, self._pending = self._pending, None
        if pending is None or self._now() >= pending["expires"] or not secrets.compare_digest(str(state), pending["state"]):
            raise HomeError("este pedido de conexão já foi usado ou expirou: comece de novo em Ajustes")
        try:
            response = await self._http.post(f"{pending['url']}/auth/token", data={"grant_type": "authorization_code", "code": code, "client_id": pending["client_id"]})
        except httpx.HTTPError as exc:
            raise HomeError(f"não consegui falar com o Home Assistant em {pending['url']}: {exc}") from exc
        data = response.json() if response.status_code == 200 else {}
        if not data.get("access_token") or not data.get("refresh_token"):
            raise HomeError("o Home Assistant não aceitou a conexão")
        self._auth.save(pending["url"], str(data["access_token"]), str(data["refresh_token"]), data.get("expires_in", 1800), pending["client_id"])
        return pending["url"]
