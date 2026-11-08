"""Linking the Alexa to Home Assistant without the person opening Home Assistant: the Chakmati drives the setup of Home Assistant's own "Alexa Devices"
integration through its API (the same one its screens use).

That integration takes the Amazon e-mail, the password and the one-time code of the 2-step verification, and signs in by itself: no sign-in page, no window,
no browser. (The older community integration signed in through a page that Home Assistant relayed from Amazon, which Amazon refused.) The country of the
account is found by the integration itself from the account.

What happens to the credentials: they go from the modal to the engine and from there to Home Assistant over this computer's loopback, in one request,
and are never stored or logged by the Chakmati (the engine holds them only while that one request is made). Home Assistant itself keeps the e-mail and the
password (the integration needs them to sign in again when Amazon asks): in its own settings folder on this computer. The sign-in to Amazon is made by
Home Assistant, over https. The code is used once and not kept by anyone."""

import re
import time

import httpx

from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.models import HomeError

DOMAIN = "alexa_devices"
LOGIN_SECONDS = 3 * 60   # the sign-in takes seconds; past this something is stuck
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE = re.compile(r"^\d{6}$")
FLOW = "/api/config/config_entries/flow"
ERRORS = {   # what the integration reports, said for the person
    "invalid_auth": "A Amazon recusou o e-mail, a senha ou o código. O código muda a cada 30 segundos: digite o que está aparecendo agora.",
    "cannot_connect": "Não consegui falar com a Amazon. Confira a internet e tente de novo.",
    "cannot_retrieve_data": "Entrei na Amazon, mas não consegui ler os seus dispositivos. Tente de novo em instantes.",
}
_IDLE = {"state": "idle", "message": ""}


def _reason(errors: dict | None) -> str:
    key = str((errors or {}).get("base") or "")
    return ERRORS.get(key, "A Alexa não aceitou os dados. Confira e tente de novo.")


class AlexaSetup:
    def __init__(self, auth: HomeAuth, http: httpx.AsyncClient, clock=time.monotonic):
        self._auth, self._http, self._clock = auth, http, clock
        self._flow_id: str | None = None
        self._started = 0.0
        self._status: dict = dict(_IDLE)

    # --- talking to Home Assistant ---------------------------------------------------------------------------------------------------
    async def _call(self, method: str, path: str, body: dict | None = None) -> dict | list:
        base = self._auth.base_url
        if not base:
            raise HomeError("o Home Assistant ainda não está conectado")
        for attempt in (False, True):
            token = await self._auth.bearer(self._http, force_renew=attempt)
            try:
                response = await self._http.request(method, base + path, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60.0)
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
    async def start(self, email: str, password: str, code: str) -> dict:
        """Starts the integration's setup with these credentials. Returns the status ("login": the sign-in is running; read it with `status`)."""
        email = email.strip()
        code = re.sub(r"\s", "", code or "")
        if not _EMAIL.match(email) or len(email) > 254:
            raise HomeError("esse e-mail não parece válido")
        if not password or len(password) > 256:
            raise HomeError("escreva a senha da sua conta Amazon")
        if not _CODE.match(code):
            raise HomeError("o código tem 6 números (o da verificação em duas etapas da Amazon)")
        await self.cancel()
        try:
            first = await self._call("POST", FLOW, {"handler": DOMAIN, "show_advanced_options": False})
        except HomeError as exc:
            if "não achei" in str(exc) or "400" in str(exc):
                raise HomeError("este Home Assistant não tem a integração Alexa Devices (precisa ser a versão 2025.6 ou mais nova)") from exc
            raise
        flow_id = str(first.get("flow_id") or "")
        if first.get("type") != "form" or first.get("step_id") != "user" or not flow_id:
            raise HomeError("a integração da Alexa respondeu de um jeito que eu não conheço")
        self._flow_id, self._started = flow_id, self._clock()
        try:
            second = await self._call("POST", f"{FLOW}/{flow_id}", {"username": email, "password": password, "code": code})
        except HomeError:
            await self.cancel()
            raise
        finally:
            del password, code   # the Chakmati keeps nothing of them
        return self._read(second)

    def _read(self, step: dict) -> dict:
        """Turns what Home Assistant answered into the status."""
        kind = step.get("type")
        if kind == "progress":
            self._status = {"state": "login", "message": "Entrando na sua conta Amazon…"}
        elif kind == "create_entry":
            self._flow_id = None
            self._status = {"state": "done", "message": "A Alexa foi conectada."}
        elif kind == "abort" and step.get("reason") == "already_configured":
            self._flow_id = None
            self._status = {"state": "done", "message": "Essa conta Amazon já estava conectada."}
        elif kind == "form":   # back to the form: the sign-in was refused
            self._flow_id = None
            self._status = {"state": "error", "message": _reason(step.get("errors"))}
        else:
            self._flow_id = None
            self._status = {"state": "error", "message": "A Alexa não aceitou os dados. Confira e tente de novo."}
        return dict(self._status)

    async def status(self) -> dict:
        """Where the setup is. While the sign-in runs it reads the setup's own state (a read that never changes it: Home Assistant answers a setup in progress
        with its progress, and with the result when it is over)."""
        if self._status["state"] != "login" or self._flow_id is None:
            return dict(self._status)
        if self._clock() - self._started > LOGIN_SECONDS:
            await self.cancel()
            self._status = {"state": "error", "message": "O login na Amazon demorou demais. Tente de novo."}
            return dict(self._status)
        try:
            step = await self._call("GET", f"{FLOW}/{self._flow_id}")
        except HomeError as exc:
            if "não achei" in str(exc):   # the setup is gone: it either finished or was dropped
                self._flow_id = None
                self._status = {"state": "error", "message": "O login terminou sem conectar a Alexa. Tente de novo."}
                return dict(self._status)
            raise
        return self._read(step if isinstance(step, dict) else {})

    async def cancel(self) -> None:
        """Drops an unfinished setup (the person gave up)."""
        flow_id, self._flow_id = self._flow_id, None
        if self._status["state"] == "login":
            self._status = dict(_IDLE)
        if flow_id:
            try:
                await self._call("DELETE", f"{FLOW}/{flow_id}")
            except HomeError:
                pass   # it was already gone
