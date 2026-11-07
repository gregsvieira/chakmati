"""HTTP routes of connecting to Home Assistant (used by Ajustes): find it, start the sign-in, receive the answer, say what is connected."""

import html

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.connect import HomeConnector, discover
from chakmati.features.home.install import HomeInstaller
from chakmati.features.home.models import HomeError
from chakmati.shared.http import ui_only

ALEXA_HELP = "https://github.com/alandtse/alexa_media_player"  # the integration that shows each Echo in Home Assistant


class ConnectIn(BaseModel):
    url: str = Field(min_length=1, max_length=200)


class InstallIn(BaseModel):
    confirm: bool = False   # the person said yes in the modal, which says what will be installed (the desktop sends this)


class AccountIn(BaseModel):
    name: str = Field(default="", max_length=60)
    password: str = Field(min_length=1, max_length=128)


def _page(title: str, text: str, ok: bool) -> HTMLResponse:
    colour = "#2f7d5b" if ok else "#b3261e"
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<body style='font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;text-align:center'>"
        f"<h1 style='color:{colour}'>{html.escape(title)}</h1><p style='font-size:1.1rem'>{html.escape(text)}</p>")


class HomeLink:
    """What is needed to connect: the credentials, the client that uses them and the sign-in flow."""

    def __init__(self, auth: HomeAuth, client: HomeAssistantClient, http: httpx.AsyncClient | None = None, hosts: list[str] | None = None, installer: HomeInstaller | None = None):
        self.auth = auth
        self.client = client
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self.connector = HomeConnector(auth, self._http)
        self.installer = installer
        self._hosts = hosts   # None = search the own network; a list (tests) = only these addresses

    async def status(self) -> dict:
        """Connected or not, and the music players it can see; never raises (a problem is a sentence for the person)."""
        info: dict = {"configured": self.auth.configured, "connected": False, "url": self.auth.base_url, "pending": self.connector.pending, "players": [], "alexa_help": ALEXA_HELP}
        if not self.auth.configured:
            return info
        try:
            entities = await self.client.entities()
        except HomeError as exc:
            info["error"] = str(exc)
            return info
        info["connected"] = True
        info["players"] = [{"name": e.name, "state": e.state} for e in entities if e.domain == "media_player"][:20]
        return info

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/home/discover")
        async def home_discover():
            return {"found": await discover(self._http, hosts=self._hosts)}

        @router.post("/home/connect", dependencies=[Depends(ui_only)])
        async def home_connect(body: ConnectIn, request: Request):
            try:
                return {"authorize_url": self.connector.start(body.url, str(request.base_url))}
            except HomeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @router.get("/home/callback")
        async def home_callback(state: str = "", code: str = "", error: str = ""):
            # The browser lands here after the person approves in Home Assistant: no custom header is possible, so the one-time `state` is the proof.
            if error or not code:
                self.connector._pending = None
                return _page("Conexão cancelada", "Você não aprovou o acesso. Se foi sem querer, tente de novo em Ajustes do Chakmati.", False)
            try:
                await self.connector.finish(state, code)
            except HomeError as exc:
                return _page("Não consegui conectar", str(exc), False)
            return _page("Pronto!", "O Chakmati já está conectado ao seu Home Assistant. Pode fechar esta janela e voltar ao Chakmati.", True)

        @router.get("/home/install")
        async def install_status():
            if self.installer is None:
                raise HTTPException(status_code=404, detail="a instalação do Home Assistant não está disponível")
            return await self.installer.inspect()

        @router.post("/home/install", dependencies=[Depends(ui_only)])
        async def install_start(body: InstallIn):
            if self.installer is None:
                raise HTTPException(status_code=404, detail="a instalação do Home Assistant não está disponível")
            if not body.confirm:
                raise HTTPException(status_code=400, detail="falta a sua confirmação para instalar")
            try:
                self.installer.start()
            except HomeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return await self.installer.inspect()

        @router.post("/home/install/account", dependencies=[Depends(ui_only)])
        async def install_account(body: AccountIn, request: Request):
            if self.installer is None:
                raise HTTPException(status_code=404, detail="a instalação do Home Assistant não está disponível")
            try:
                await self.installer.create_account(body.name, body.password, str(request.base_url))
            except HomeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return await self.installer.inspect()

        @router.get("/home/status")
        async def home_status():
            return await self.status()

        @router.delete("/home", dependencies=[Depends(ui_only)])
        async def home_disconnect():
            self.auth.forget()
            return await self.status()

        return router
