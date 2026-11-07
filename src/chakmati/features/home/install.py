"""Putting a Home Assistant on this computer, for someone who has never used Docker: check Docker, open it if needed, download and start Home Assistant
in a container, wait for it, create the owner and connect. One call from Ajustes; the progress is a plain sentence at each step.

What it cannot do by itself, and says so in words: install Docker (it needs the person's permission as administrator and, on Windows, WSL2 and
a restart), and link the Alexa (that is a login to Amazon, inside Home Assistant)."""

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from chakmati.features.home import docker as dock
from chakmati.features.home import onboarding
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.connect import probe
from chakmati.features.home.models import HomeError

log = logging.getLogger("chakmati.home.install")

DOCKER_MISSING = "O Docker não está instalado neste computador. Instale o Docker Desktop (é grátis para uso pessoal), abra-o uma vez e toque em tentar de novo."
DOCKER_SLOW = "O Docker não ficou pronto a tempo. Abra o Docker Desktop, espere ele terminar de iniciar e toque em tentar de novo."
DOCKER_OFF = "O Docker está desligado. Inicie o serviço do Docker e toque em tentar de novo."
HA_SLOW = "O Home Assistant demorou para ligar. Espere alguns minutos e toque em tentar de novo."


class HomeInstaller:
    def __init__(self, docker: dock.DockerHome, auth: HomeAuth, http: httpx.AsyncClient, state_file: str, wait_seconds: float = 420.0,
                 sleep=asyncio.sleep, clock=time.monotonic):
        self._docker, self._auth, self._http = docker, auth, http
        self._file = Path(state_file)
        self._wait, self._sleep, self._clock = wait_seconds, sleep, clock
        self._status = {"state": "idle", "phase": "", "message": "", "code": ""}
        self._task: asyncio.Task | None = None

    # --- what is known ---------------------------------------------------------------------------------------------------------------
    @property
    def managed(self) -> bool:
        try:
            return bool(json.loads(self._file.read_text(encoding="utf-8")).get("managed"))
        except (OSError, ValueError):
            return False

    def _mark_managed(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps({"managed": True, "container": dock.CONTAINER, "url": dock.URL}), encoding="utf-8")

    async def inspect(self) -> dict:
        """What the person needs to know before installing, and how an install in progress is going."""
        if not self._docker.installed():
            docker_state = "no_docker"
        else:
            docker_state = "ready" if await self._docker.daemon_ready() else "daemon_off"
        container = await self._docker.container() if docker_state == "ready" else "unknown"
        return {**self._status, "docker": docker_state, "container": container, "managed": self.managed, "can_open_docker": self._docker.desktop_app() is not None,
                "download_page": dock.DOWNLOAD_PAGE, "image_mb": dock.IMAGE_SIZE_MB}

    def _set(self, state: str, phase: str, message: str, code: str = "") -> None:
        self._status = {"state": state, "phase": phase, "message": message, "code": code}

    # --- installing ------------------------------------------------------------------------------------------------------------------
    def start(self, name: str, password: str, engine_base: str) -> None:
        """Starts the install in the background (a download takes minutes); the progress is read with `inspect`."""
        if self._task is not None and not self._task.done():
            raise HomeError("a instalação já está em andamento")
        if len(password) < onboarding.MIN_PASSWORD:
            raise HomeError(f"escolha uma senha com pelo menos {onboarding.MIN_PASSWORD} caracteres")
        base = engine_base if engine_base.endswith("/") else engine_base + "/"
        self._set("running", "docker", "Verificando o Docker…")
        self._task = asyncio.create_task(self._guarded(name, password, base))

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def _guarded(self, name: str, password: str, client_id: str) -> None:
        try:
            await self._install(name, password, client_id)
        except HomeError as exc:
            text = str(exc)
            self._set("error", self._status["phase"], text[0].upper() + text[1:] + ".", "has_owner" if "já tem um dono" in text else "error")
        except Exception as exc:   # a surprise must not leave the person with a spinner that never ends
            log.exception("installing Home Assistant failed")
            self._set("error", self._status["phase"], f"Algo inesperado aconteceu: {type(exc).__name__}. Tente de novo.", "error")

    async def _install(self, name: str, password: str, client_id: str) -> None:
        d = self._docker
        if not await self._ensure_docker():
            return
        phase = "image"
        if await d.container() == "none":
            self._set("running", phase, "Baixando o Home Assistant… (pode levar vários minutos, depende da sua internet)")
            if not await d.pull(lambda line: self._set("running", "image", f"Baixando o Home Assistant… {line[:80]}")):
                raise HomeError("não consegui baixar o Home Assistant: confira a internet e tente de novo")
            self._set("running", "container", "Criando o Home Assistant…")
            ok, out = await d.create()
            if not ok:
                raise HomeError(f"não consegui criar o Home Assistant ({out[-120:] or 'sem detalhes'})")
        elif await d.container() == "stopped":
            self._set("running", "container", "Ligando o Home Assistant…")
            ok, out = await d.start()
            if not ok:
                raise HomeError(f"não consegui ligar o Home Assistant ({out[-120:] or 'sem detalhes'})")
        self._set("running", "waiting", "Iniciando o Home Assistant pela primeira vez… pode levar alguns minutos.")
        if not await self._wait_for_home():
            self._set("error", "waiting", HA_SLOW, "ha_slow")
            return
        self._set("running", "account", "Criando a sua conta no Home Assistant…")
        tokens = await onboarding.create_owner(self._http, dock.URL, client_id, name, password)
        self._auth.save(dock.URL, str(tokens["access_token"]), str(tokens["refresh_token"]), tokens.get("expires_in", 1800), client_id)
        self._mark_managed()
        self._set("done", "done", "Pronto! O Home Assistant está instalado e conectado.")

    async def _ensure_docker(self) -> bool:
        """True when Docker answers. Otherwise the status already says what the person must do."""
        d = self._docker
        if not d.installed():
            self._set("error", "docker", DOCKER_MISSING, "docker_missing")
            return False
        if await d.daemon_ready():
            return True
        if not d.desktop_app():
            self._set("error", "docker", DOCKER_OFF, "docker_off")
            return False
        self._set("running", "docker", "Abrindo o Docker… (pode levar um minuto)")
        if not await d.open_desktop() or not await d.wait_for_daemon():
            self._set("error", "docker", DOCKER_SLOW, "docker_slow")
            return False
        return True

    async def _wait_for_home(self) -> bool:
        deadline = self._clock() + self._wait
        while self._clock() < deadline:
            if await probe(dock.URL, self._http):
                return True
            await self._sleep(3.0)
        return False

    # --- every time the Chakmati starts -----------------------------------------------------------------------------------------------
    async def ensure_up(self) -> None:
        """If the Chakmati installed the Home Assistant, it is switched on again when the Chakmati starts (the container itself restarts with Docker).
        Quiet: nothing here is an error for the person, and nothing is installed or downloaded."""
        if not self.managed or not self._docker.installed():
            return
        try:
            if not await self._docker.daemon_ready():
                if not self._docker.desktop_app() or not await self._docker.open_desktop() or not await self._docker.wait_for_daemon():
                    return
            if await self._docker.container() == "stopped":
                await self._docker.start()
        except Exception:
            log.exception("could not switch the Home Assistant on")
