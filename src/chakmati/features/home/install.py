"""Putting a Home Assistant on this computer, for someone who has never used Docker. Two moments, so the person is asked for a name and a password only
when everything is ready:

  1. `start` PREPARES it, in the background, telling each step in plain words: installs Docker if it is missing (the system asks for the administrator
     password), opens it if it is off, downloads Home Assistant, puts the Alexa integration in its folder, starts it, waits for it, and looks at it.
  2. `create_account` takes the name and the password, creates the owner through Home Assistant's own onboarding and connects.

Linux has no program to open or install for the person, and Windows may ask to restart: the status says so in words and the install continues from where it
stopped. Logging in to Amazon (the Alexa itself) is done once inside Home Assistant."""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx

from chakmati.features.home import alexa, docker as dock, onboarding
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.connect import probe
from chakmati.features.home.docker_setup import DockerSetup
from chakmati.features.home.models import HomeError

log = logging.getLogger("chakmati.home.install")

DOCKER_MISSING = "O Docker não está instalado neste computador, e neste sistema ele se instala pelo gerenciador de pacotes (veja docs.docker.com/engine/install). Depois toque em tentar de novo."
DOCKER_SLOW = "O Docker não ficou pronto a tempo. Abra o Docker Desktop, espere ele terminar de iniciar e toque em tentar de novo."
DOCKER_OFF = "O Docker está desligado. Inicie o serviço do Docker e toque em tentar de novo."
REBOOT = "O Docker foi instalado, mas o computador precisa ser reiniciado para ele funcionar. Reinicie, abra o Chakmati de novo e toque em Começar: ele continua daqui."
HA_SLOW = "O Home Assistant demorou para ligar. Espere alguns minutos e toque em tentar de novo."
READY = "Tudo pronto e funcionando. Escolha um nome e uma senha para o seu Home Assistant."
HAS_OWNER = "O Home Assistant já tem uma conta. Toque em Conectar para entrar com ela."


class HomeInstaller:
    def __init__(self, docker: dock.DockerHome, auth: HomeAuth, http: httpx.AsyncClient, state_file: str, setup: DockerSetup | None = None,
                 wait_seconds: float = 420.0, sleep=asyncio.sleep, clock=time.monotonic, alexa_install=alexa.install):
        self._docker, self._auth, self._http, self._setup = docker, auth, http, setup
        self._file = Path(state_file)
        self._wait, self._sleep, self._clock, self._alexa = wait_seconds, sleep, clock, alexa_install
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

    def _set(self, state: str, phase: str, message: str, code: str = "") -> None:
        self._status = {"state": state, "phase": phase, "message": message, "code": code}

    async def inspect(self) -> dict:
        """What the person needs to know before starting, and how a start in progress is going."""
        if not self._docker.installed():
            docker_state = "no_docker"
        else:
            docker_state = "ready" if await self._docker.daemon_ready() else "daemon_off"
        container = await self._docker.container() if docker_state == "ready" else "unknown"
        installable = self._setup is not None and self._setup.supported()
        return {**self._status, "docker": docker_state, "container": container, "managed": self.managed, "can_open_docker": self._docker.desktop_app() is not None,
                "platform": sys.platform, "docker_installable": installable, "docker_mb": self._setup.size_mb() if installable else 0, "image_mb": dock.IMAGE_SIZE_MB,
                "alexa_ready": alexa.installed(self._docker.config_dir), "alexa_help": alexa.HELP_PAGE, "download_page": "https://www.docker.com/products/docker-desktop/"}

    # --- 1. preparing ---------------------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """Starts preparing in the background (a download takes minutes); the progress is read with `inspect`."""
        if self._task is not None and not self._task.done():
            raise HomeError("a instalação já está em andamento")
        self._set("running", "docker", "Verificando o Docker…")
        self._task = asyncio.create_task(self._guarded())

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def _guarded(self) -> None:
        try:
            await self._prepare()
        except HomeError as exc:
            text = str(exc)
            self._set("error", self._status["phase"], text[0].upper() + text[1:] + ("" if text.endswith((".", "!")) else "."), "error")
        except Exception as exc:   # a surprise must not leave the person with a spinner that never ends
            log.exception("preparing Home Assistant failed")
            self._set("error", self._status["phase"], f"Algo inesperado aconteceu: {type(exc).__name__}. Tente de novo.", "error")

    async def _prepare(self) -> None:
        d = self._docker
        if not await self._ensure_docker():
            return
        newly = await self._put_alexa()
        state = await d.container()
        if state == "none":
            self._set("running", "image", "Baixando o Home Assistant… (pode levar vários minutos, depende da sua internet)")
            if not await d.pull(lambda line: self._set("running", "image", f"Baixando o Home Assistant… {line[:80]}")):
                raise HomeError("não consegui baixar o Home Assistant: confira a internet e tente de novo")
            self._set("running", "container", "Criando o Home Assistant…")
            ok, out = await d.create()
            if not ok:
                raise HomeError(f"não consegui criar o Home Assistant ({out[-120:] or 'sem detalhes'})")
        elif state == "stopped":
            self._set("running", "container", "Ligando o Home Assistant…")
            ok, out = await d.start()
            if not ok:
                raise HomeError(f"não consegui ligar o Home Assistant ({out[-120:] or 'sem detalhes'})")
        elif newly:   # it was already running: it only sees the new integration after a restart
            self._set("running", "container", "Reiniciando o Home Assistant para carregar a Alexa…")
            ok, out = await d.restart()
            if not ok:
                raise HomeError(f"não consegui reiniciar o Home Assistant ({out[-120:] or 'sem detalhes'})")
        self._mark_managed()
        self._set("running", "waiting", "Iniciando o Home Assistant pela primeira vez… pode levar alguns minutos.")
        if not await self._wait_for_home():
            self._set("error", "waiting", HA_SLOW, "ha_slow")
            return
        self._set("running", "looking", "Conferindo tudo…")
        if "user" in await onboarding.open_steps(self._http, dock.URL):
            self._set("ready", "account", READY, "needs_account")
        else:
            self._set("ready", "account", HAS_OWNER, "has_owner")

    async def _put_alexa(self) -> bool:
        """The Alexa integration in Home Assistant's folder. True when it was just put there."""
        self._set("running", "alexa", "Baixando a integração da Alexa (alexa_media_player)…")
        version = await self._alexa(self._http, self._docker.config_dir)
        return bool(version)

    async def _ensure_docker(self) -> bool:
        """True when Docker answers. Otherwise the status already says what the person must do."""
        d = self._docker
        if not d.installed():
            if self._setup is None or not self._setup.supported():
                self._set("error", "docker", DOCKER_MISSING, "docker_missing")
                return False
            await self._install_docker()
            if not d.installed():
                self._set("error", "docker_install", REBOOT, "reboot")
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

    async def _install_docker(self) -> None:
        assert self._setup is not None

        def progress(done: int, total: int) -> None:
            shown = f"{done // 1048576}/{total // 1048576} MB" if total else f"{done // 1048576} MB"
            self._set("running", "docker_install", f"Baixando o Docker Desktop… {shown}")

        self._set("running", "docker_install", "Baixando o Docker Desktop…")
        installer = await self._setup.download(progress)
        self._set("running", "docker_install", "Instalando o Docker Desktop… o computador vai pedir a sua senha de administrador.")
        await self._setup.install(installer)

    async def _wait_for_home(self) -> bool:
        deadline = self._clock() + self._wait
        while self._clock() < deadline:
            if await probe(dock.URL, self._http):
                return True
            await self._sleep(3.0)
        return False

    # --- 2. the account -------------------------------------------------------------------------------------------------------------
    async def create_account(self, name: str, password: str, engine_base: str) -> dict:
        """Creates the owner with the name and the password and connects. Raises HomeError with a sentence when it cannot; the status is then left as it was."""
        if self._status["code"] != "needs_account":
            raise HomeError("o Home Assistant ainda não está pronto para receber a sua conta")
        if len(password) < onboarding.MIN_PASSWORD:
            raise HomeError(f"escolha uma senha com pelo menos {onboarding.MIN_PASSWORD} caracteres")
        base = engine_base if engine_base.endswith("/") else engine_base + "/"
        self._set("running", "account", "Criando a sua conta no Home Assistant…")
        try:
            tokens = await onboarding.create_owner(self._http, dock.URL, base, name, password)
        except HomeError:
            self._set("ready", "account", READY, "needs_account")   # the person can try again with another password
            raise
        self._auth.save(dock.URL, str(tokens["access_token"]), str(tokens["refresh_token"]), tokens.get("expires_in", 1800), base)
        self._set("done", "done", "Pronto! O Home Assistant está instalado e conectado.")
        return self._status

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
