"""Linking the Alexa to Home Assistant without the person opening Home Assistant: the Chakmati drives the integration's own setup through Home Assistant's
API (the same one its screens use), so nobody has to find "Adicionar integração > Alexa Media Player".

What the integration does (alexa_media 5.x): it takes the Amazon region, e-mail and password, then asks for the sign-in on a page that Home Assistant
serves (a proxy of Amazon's own sign-in page, where Amazon asks for a captcha or a code if it wants one). The Chakmati gives Home Assistant the right
address for that page (`http://localhost:8123`: the default, `homeassistant.local`, does not exist for a browser, which is what leaves the page blank),
hands the page to the app's own small window, and waits for Home Assistant to finish.

What happens to the credentials: they go from the modal to the engine and from there to Home Assistant over this computer's loopback, in one request,
and are never stored or logged by the Chakmati (the engine holds them only while that one request is made). Home Assistant itself keeps them (the integration needs them to sign in again
when Amazon asks): in its own settings folder on this computer. The sign-in to Amazon is made by Home Assistant, over https."""

import asyncio
import re
import time

import httpx

from chakmati.features.home import docker as dock
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.models import HomeError

DOMAIN = "alexa_media"
REGIONS: dict[str, str] = {   # what the integration accepts, with the name the person recognises
    "amazon.com.br": "Brasil", "amazon.com": "Estados Unidos", "amazon.ca": "Canadá", "amazon.com.mx": "México", "amazon.co.uk": "Reino Unido",
    "amazon.de": "Alemanha", "amazon.es": "Espanha", "amazon.fr": "França", "amazon.it": "Itália", "amazon.in": "Índia", "amazon.co.jp": "Japão", "amazon.com.au": "Austrália",
}
LOGIN_SECONDS = 10 * 60
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def region_for_locale(locale: str) -> str:
    """The Amazon site for a locale like "pt-BR" (the country decides); amazon.com when the country is not one the integration knows."""
    country = (locale or "").replace("_", "-").split("-")[-1].upper()
    by_country = {"BR": "amazon.com.br", "US": "amazon.com", "CA": "amazon.ca", "MX": "amazon.com.mx", "GB": "amazon.co.uk", "DE": "amazon.de", "ES": "amazon.es",
                  "FR": "amazon.fr", "IT": "amazon.it", "IN": "amazon.in", "JP": "amazon.co.jp", "AU": "amazon.com.au"}
    return by_country.get(country, "amazon.com")


class AlexaSetup:
    def __init__(self, auth: HomeAuth, http: httpx.AsyncClient, hass_url: str = dock.URL, clock=time.monotonic):
        self._auth, self._http, self._hass_url, self._clock = auth, http, hass_url, clock
        self._flow_id: str | None = None
        self._started = 0.0
        self._status: dict = {"state": "idle", "message": "", "url": ""}

    # --- talking to Home Assistant ---------------------------------------------------------------------------------------------------
    async def _call(self, method: str, path: str, body: dict | None = None) -> dict | list:
        base = self._auth.base_url
        if not base:
            raise HomeError("o Home Assistant ainda não está conectado")
        for attempt in (False, True):
            token = await self._auth.bearer(self._http, force_renew=attempt)
            try:
                response = await self._http.request(method, base + path, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)
            except httpx.HTTPError as exc:
                raise HomeError(f"não consegui falar com o Home Assistant: {type(exc).__name__}") from exc
            if response.status_code != 401 or attempt or not self._auth.oauth:
                break
        if response.status_code == 401:
            raise HomeError("o Home Assistant recusou o acesso: conecte de novo")
        if response.status_code >= 400:   # never the body: it could echo what was sent
            raise HomeError("não achei isso no Home Assistant" if response.status_code == 404 else f"o Home Assistant respondeu {response.status_code}")
        return response.json() if response.content else {}

    # --- the steps -----------------------------------------------------------------------------------------------------------------
    async def start(self, region: str, email: str, password: str) -> dict:
        """Starts the integration's setup with these credentials. Returns the status: "login" with the address of the sign-in page to show, or "done"."""
        if region not in REGIONS:
            raise HomeError("escolha o país da sua conta Amazon")
        email = email.strip()
        if not _EMAIL.match(email) or len(email) > 254:
            raise HomeError("esse e-mail não parece válido")
        if not password or len(password) > 256:
            raise HomeError("escreva a senha da sua conta Amazon")
        await self.cancel()
        try:
            first = await self._call("POST", "/api/config/config_entries/flow", {"handler": DOMAIN, "show_advanced_options": False})
        except HomeError as exc:
            if "não achei" in str(exc) or "400" in str(exc):
                raise HomeError("a integração da Alexa não está carregada no Home Assistant: reinicie o Home Assistant e tente de novo") from exc
            raise
        flow_id = str(first.get("flow_id") or "")
        if first.get("type") != "form" or first.get("step_id") != "user" or not flow_id:
            raise HomeError("a integração da Alexa respondeu de um jeito que eu não conheço")
        self._flow_id, self._started = flow_id, self._clock()
        try:
            second = await self._call("POST", f"/api/config/config_entries/flow/{flow_id}", {"url": region, "email": email, "password": password, "hass_url": self._hass_url})
        except HomeError:
            await self.cancel()
            raise
        finally:
            del password   # the Chakmati keeps nothing of it
        kind, step = second.get("type"), second.get("step_id")
        if kind == "external" and second.get("url"):
            self._status = {"state": "login", "message": "Entre na sua conta Amazon na janela que abriu. Se a Amazon pedir um código, digite lá.", "url": str(second["url"])}
        elif kind == "create_entry":
            self._flow_id = None
            self._status = {"state": "done", "message": "A Alexa foi conectada.", "url": ""}
        else:
            await self.cancel()
            reason = {"proxy_warning": "o Home Assistant não conseguiu abrir a página de login por aqui", "totp_register": "a Amazon pediu uma chave de verificação que eu não sei tratar",
                      "user": "a Amazon recusou o e-mail ou a senha"}.get(str(step), "a integração da Alexa não aceitou os dados")
            raise HomeError(reason)
        return dict(self._status)

    async def status(self) -> dict:
        """Where the setup is. While the person signs in it ONLY reads the list of Home Assistant's configurations: asking Home Assistant about the setup itself
        (GET .../flow/<id>) makes it move on to the next step and throws the sign-in page away, so it is never asked. When the sign-in succeeds the integration
        tells Home Assistant by itself and the configuration appears."""
        if self._status["state"] != "login" or self._flow_id is None:
            return dict(self._status)
        entries = await self._call("GET", "/api/config/config_entries/entry?domain=" + DOMAIN)
        entry = next((e for e in entries if isinstance(e, dict) and e.get("domain") == DOMAIN), None) if isinstance(entries, list) else None
        if entry is not None:
            state = str(entry.get("state") or "")
            if state in ("setup_error", "setup_retry", "migration_error", "failed_unload"):
                self._flow_id = None
                self._status = {"state": "error", "message": "A Alexa foi aceita, mas não conseguiu iniciar. Confira a conta e tente de novo.", "url": ""}
            elif state == "loaded":
                self._flow_id = None
                self._status = {"state": "done", "message": "A Alexa foi conectada.", "url": ""}
        elif self._clock() - self._started > LOGIN_SECONDS:
            await self.cancel()
            self._status = {"state": "error", "message": "O login na Amazon demorou demais. Tente de novo.", "url": ""}
        return dict(self._status)

    async def cancel(self) -> None:
        """Drops an unfinished setup (the person closed the window or gave up)."""
        flow_id, self._flow_id = self._flow_id, None
        if self._status["state"] == "login":
            self._status = {"state": "idle", "message": "", "url": ""}
        if flow_id:
            try:
                await self._call("DELETE", f"/api/config/config_entries/flow/{flow_id}")
            except HomeError:
                pass   # it was already gone
