"""Putting a Home Assistant on this computer through Docker, for someone who has never used Docker: every command is fixed, every state has a sentence."""

import asyncio
import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.features.home import docker as dock
from chakmati.features.home import onboarding
from chakmati.features.home.api import HomeLink
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.docker import CONTAINER, IMAGE, DockerHome
from chakmati.features.home.install import DOCKER_MISSING, DOCKER_OFF, DOCKER_SLOW, HA_SLOW, HAS_OWNER, READY, REBOOT, HomeInstaller
from chakmati.features.home.models import HomeError
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore

ENGINE = "http://127.0.0.1:8765/"


# --- real commands, the safe ones ------------------------------------------------------------------------------------------------------------
async def test_run_returns_the_exit_code_and_the_output():
    assert await dock.run([sys.executable, "-c", "print('oi')"], 10) == (0, "oi")
    code, out = await dock.run([sys.executable, "-c", "import sys; print('erro'); sys.exit(3)"], 10)
    assert (code, out) == (3, "erro")


async def test_a_missing_program_and_a_slow_one_are_told_apart():
    assert (await dock.run(["programa-que-nao-existe-xyz"], 5))[0] == 127
    assert (await dock.run([sys.executable, "-c", "import time; time.sleep(30)"], 0.3))[0] == 124


async def test_stream_hands_over_each_line_as_it_comes():
    lines: list[str] = []
    code = await dock.stream([sys.executable, "-u", "-c", "print('a'); print('b')"], lines.append, 10)
    assert code == 0 and lines == ["a", "b"]
    assert await dock.stream(["programa-que-nao-existe-xyz"], lines.append, 5) == 127


def test_the_time_zone_comes_from_the_system(monkeypatch):
    monkeypatch.setattr("chakmati.features.home.docker.os.readlink", lambda p: "/var/db/timezone/zoneinfo/America/Sao_Paulo")
    assert dock.local_timezone() == "America/Sao_Paulo"
    monkeypatch.setattr("chakmati.features.home.docker.os.readlink", lambda p: (_ for _ in ()).throw(OSError()))
    monkeypatch.setenv("TZ", "Europe/Lisbon")
    assert dock.local_timezone() == "Europe/Lisbon"
    monkeypatch.delenv("TZ")
    assert dock.local_timezone() == "UTC"


# --- DockerHome, with fake commands ------------------------------------------------------------------------------------------------------------
class Cmd:
    """A fake `run`: answers by the first words of the command and remembers every command."""

    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    async def __call__(self, args, timeout=60.0):
        self.calls.append(args)
        for prefix, answer in self.answers.items():
            if " ".join(args).startswith(prefix):
                return answer
        return 0, ""


def docker_home(tmp_path, cmd=None, which="/usr/local/bin/docker", platform="darwin", exists=lambda p: False, **kw):
    return DockerHome(str(tmp_path / "ha"), run_fn=cmd or Cmd(), which=lambda name: which, platform=platform, exists=exists, timezone="America/Sao_Paulo", **kw)


def test_docker_is_there_when_the_program_or_the_desktop_app_is(tmp_path):
    assert docker_home(tmp_path).installed()
    assert not docker_home(tmp_path, which=None).installed()
    assert docker_home(tmp_path, which=None, exists=lambda p: p == dock.MAC_APP).installed()
    assert docker_home(tmp_path, which=None, platform="win32", exists=lambda p: p == dock.WINDOWS_APP).installed()
    assert not docker_home(tmp_path, which=None, platform="linux", exists=lambda p: True).installed()    # on Linux there is no app to open


async def test_the_daemon_and_the_container_are_asked_with_fixed_commands(tmp_path):
    cmd = Cmd({"docker info": (1, "Cannot connect")})
    d = docker_home(tmp_path, cmd)
    assert await d.daemon_ready() is False
    assert cmd.calls[0] == ["docker", "info", "--format", "{{.ServerVersion}}"]
    assert await docker_home(tmp_path, Cmd({"docker inspect": (1, "No such object")})).container() == "none"
    assert await docker_home(tmp_path, Cmd({"docker inspect": (0, "true")})).container() == "running"
    assert await docker_home(tmp_path, Cmd({"docker inspect": (0, "false")})).container() == "stopped"
    inspect = Cmd({"docker inspect": (0, "true")})
    await docker_home(tmp_path, inspect).container()
    assert inspect.calls[0] == ["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER]


async def test_docker_desktop_is_opened_on_macos_only_through_open(tmp_path):
    cmd = Cmd()
    assert await docker_home(tmp_path, cmd, exists=lambda p: p == dock.MAC_APP).open_desktop() is True
    assert cmd.calls == [["open", "-a", "Docker"]]
    cmd2 = Cmd()
    assert await docker_home(tmp_path, cmd2, platform="linux", exists=lambda p: True).open_desktop() is False
    assert cmd2.calls == []                                                 # nothing is run when there is nothing to open


async def test_waiting_for_the_daemon_gives_up_after_the_time(tmp_path):
    clock = [0.0]
    ready_at = [3]

    async def sleep(seconds):
        clock[0] += seconds

    async def run_fn(args, timeout=60.0):
        ready_at[0] -= 1
        return (0 if ready_at[0] <= 0 else 1), ""

    d = DockerHome(str(tmp_path), run_fn=run_fn, sleep=sleep, clock=lambda: clock[0])
    assert await d.wait_for_daemon(seconds=60) is True
    never = DockerHome(str(tmp_path), run_fn=Cmd({"docker info": (1, "")}), sleep=sleep, clock=lambda: clock[0])
    assert await never.wait_for_daemon(seconds=30) is False


async def test_the_container_is_published_on_this_computer_only_with_its_settings_in_our_folder(tmp_path):
    cmd = Cmd()
    d = docker_home(tmp_path, cmd)
    assert (await d.create())[0] is True
    assert cmd.calls[0] == ["docker", "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped", "-p", "127.0.0.1:8123:8123",
                            "-v", f"{tmp_path / 'ha'}:/config", "-e", "TZ=America/Sao_Paulo", IMAGE]
    assert (tmp_path / "ha").is_dir()
    assert (await docker_home(tmp_path, Cmd({"docker run": (125, "pull access denied")})).create()) == (False, "pull access denied")


async def test_start_and_pull_use_the_fixed_names(tmp_path):
    cmd = Cmd()
    assert (await docker_home(tmp_path, cmd).start())[0] is True and cmd.calls[0] == ["docker", "start", CONTAINER]
    seen = []

    async def stream_fn(args, on_line, timeout):
        seen.append(args)
        on_line("Pulling fs layer")
        return 0

    lines = []
    assert await DockerHome(str(tmp_path), stream_fn=stream_fn).pull(lines.append) is True
    assert seen == [["docker", "pull", IMAGE]] and lines == ["Pulling fs layer"]


# --- the owner of a new Home Assistant ----------------------------------------------------------------------------------------------------------
class FakeHA:
    """A fresh Home Assistant: onboarding open, then an owner, then the tokens."""

    def __init__(self, steps=None, ready_after=0, users_status=200, token_ok=True):
        self.steps = steps if steps is not None else ["user", "core_config", "analytics", "integration"]
        self.ready_after, self.users_status, self.token_ok = ready_after, users_status, token_ok
        self.calls: list = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = request.content.decode()
        self.calls.append((request.method, path, body, request.headers.get("authorization")))
        if path == "/manifest.json":
            if self.ready_after > 0:
                self.ready_after -= 1
                return httpx.Response(503)
            return httpx.Response(200, json={"name": "Home Assistant"})
        if path == "/api/onboarding" and request.method == "GET":
            return httpx.Response(200, json=[{"step": s, "done": False} for s in self.steps])
        if path == "/api/onboarding/users":
            return httpx.Response(self.users_status, json={"auth_code": "THECODE"})
        if path == "/auth/token":
            return httpx.Response(200, json={"access_token": "ACCESS", "refresh_token": "REFRESH", "expires_in": 1800} if self.token_ok else {})
        if path.startswith("/api/onboarding/"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


async def test_onboarding_creates_the_owner_and_finishes_the_other_steps():
    ha = FakeHA()
    tokens = await onboarding.create_owner(ha.client(), dock.URL, ENGINE, "Maria", "senha-forte-1")
    assert tokens["refresh_token"] == "REFRESH"
    sent = {path: (json.loads(body) if body.startswith("{") else body) for _, path, body, _ in ha.calls if method_post(path)}
    assert sent["/api/onboarding/users"] == {"client_id": ENGINE, "name": "Maria", "username": "chakmati", "password": "senha-forte-1", "language": "pt-BR"}
    assert "grant_type=authorization_code" in sent["/auth/token"] and "code=THECODE" in sent["/auth/token"]
    steps = [(p, a) for _, p, _, a in ha.calls if p in ("/api/onboarding/core_config", "/api/onboarding/analytics", "/api/onboarding/integration")]
    assert [p for p, _ in steps] == ["/api/onboarding/core_config", "/api/onboarding/analytics", "/api/onboarding/integration"]
    assert all(a == "Bearer ACCESS" for _, a in steps)                              # the other steps are done as the new owner


def method_post(path: str) -> bool:
    return path in ("/api/onboarding/users", "/auth/token")


async def test_a_short_password_is_refused_before_anything_is_sent():
    ha = FakeHA()
    with pytest.raises(HomeError, match="pelo menos 8 caracteres"):
        await onboarding.create_owner(ha.client(), dock.URL, ENGINE, "Maria", "curta")
    assert ha.calls == []


async def test_a_home_assistant_that_already_has_an_owner_is_not_touched():
    ha = FakeHA(steps=[])
    with pytest.raises(HomeError, match="já tem um dono"):
        await onboarding.create_owner(ha.client(), dock.URL, ENGINE, "Maria", "senha-forte-1")
    assert [c[1] for c in ha.calls] == ["/api/onboarding"]
    assert await onboarding.open_steps(FakeHA(steps=["analytics"]).client(), dock.URL) == ["analytics"]
    gone = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert await onboarding.open_steps(gone, dock.URL) == []                        # no onboarding at all: finished long ago


@pytest.mark.parametrize("ha,message", [(FakeHA(users_status=400), "não aceitou criar a conta"), (FakeHA(token_ok=False), "não entregou o acesso")])
async def test_each_refusal_is_a_sentence(ha, message):
    with pytest.raises(HomeError, match=message):
        await onboarding.create_owner(ha.client(), dock.URL, ENGINE, "Maria", "senha-forte-1")


async def test_a_home_assistant_that_stops_answering_is_a_sentence():
    def boom(request):
        raise httpx.ConnectError("caiu")
    with pytest.raises(HomeError, match="não consegui falar"):
        await onboarding.open_steps(httpx.AsyncClient(transport=httpx.MockTransport(boom)), dock.URL)


# --- the whole install: 1. preparing, 2. the account ----------------------------------------------------------------------------------------------
class FakeDocker:
    """The same questions as DockerHome, with answers set by the test; remembers what was done and in which order."""

    def __init__(self, installed=True, daemon=True, desktop=True, container="none", opens=True, daemon_after_open=True, pull_ok=True, create=(True, ""), start=(True, ""), restart=(True, ""), config_dir="/x"):
        self._installed, self.daemon, self._desktop = installed, daemon, desktop
        self.state, self.opens, self.daemon_after_open, self.pull_ok = container, opens, daemon_after_open, pull_ok
        self._create, self._start, self._restart, self.config_dir = create, start, restart, config_dir
        self.did: list[str] = []

    def installed(self): return self._installed
    def desktop_app(self): return "/Applications/Docker.app" if self._desktop else None
    async def daemon_ready(self): return self.daemon
    async def container(self): return self.state

    async def open_desktop(self):
        self.did.append("open")
        return self.opens

    async def wait_for_daemon(self, seconds=240.0, every=3.0):
        self.did.append("wait_daemon")
        self.daemon = self.daemon_after_open
        return self.daemon

    async def pull(self, on_line):
        self.did.append("pull")
        on_line("Downloading 12MB/100MB")
        return self.pull_ok

    async def create(self):
        self.did.append("create")
        if self._create[0]:
            self.state = "running"
        return self._create

    async def start(self):
        self.did.append("start")
        if self._start[0]:
            self.state = "running"
        return self._start

    async def restart(self):
        self.did.append("restart")
        return self._restart


class FakeSetup:
    """DockerSetup without the download or the administrator window: records, and installs Docker into the FakeDocker when asked to."""

    def __init__(self, docker, supported=True, installs=True, fails=None, mb=700):
        self.docker, self._supported, self.installs, self.fails, self.mb = docker, supported, installs, fails, mb
        self.did: list[str] = []

    def supported(self): return self._supported
    def size_mb(self): return self.mb

    async def download(self, on_progress):
        self.did.append("download")
        on_progress(12 * 1048576, 700 * 1048576)
        return "/tmp/Docker.dmg"

    async def install(self, path):
        self.did.append("install")
        if self.fails:
            raise self.fails
        if self.installs:
            self.docker._installed = True


def make_alexa(version="v5.0.0", fails=None):
    calls: list = []

    async def fake(http, config_dir):
        calls.append(config_dir)
        if fails:
            raise fails
        return version
    fake.calls = calls
    return fake


def make_installer(tmp_path, docker=None, ha=None, wait=30.0, setup=None, alexa=None):
    ha = ha or FakeHA()
    docker = docker or FakeDocker()
    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds
    auth = HomeAuth(str(tmp_path / "auth.json"))
    installer = HomeInstaller(docker, auth, ha.client(), str(tmp_path / "docker.json"), setup=setup, wait_seconds=wait, sleep=sleep, clock=lambda: clock[0],
                              alexa_install=alexa or make_alexa())
    return installer, auth, ha


async def prepare(installer):
    installer.start()
    await installer.wait()
    return installer._status


async def test_preparing_ends_asking_for_the_account_and_nothing_is_connected_yet(tmp_path):
    d = FakeDocker()
    alexa = make_alexa()
    installer, auth, ha = make_installer(tmp_path, d, FakeHA(ready_after=2), alexa=alexa)
    status = await prepare(installer)
    assert status == {"state": "ready", "phase": "account", "message": READY, "code": "needs_account"}
    assert d.did == ["pull", "create"] and len(alexa.calls) == 1
    assert installer.managed and not auth.configured                         # it is up, and the person is asked for the name and the password next
    assert [c[1] for c in ha.calls if c[1] == "/api/onboarding/users"] == []


async def test_the_alexa_integration_is_put_in_place_before_home_assistant_starts(tmp_path):
    order: list[str] = []

    class Ordered(FakeDocker):
        async def create(self):
            order.append("create")
            return await super().create()

    async def alexa(http, config_dir):
        order.append("alexa")
        return "v5"
    installer, *_ = make_installer(tmp_path, Ordered(), alexa=alexa)
    await prepare(installer)
    assert order == ["alexa", "create"]


async def test_the_account_connects_and_keeps_the_password_nowhere(tmp_path):
    installer, auth, ha = make_installer(tmp_path)
    await prepare(installer)
    status = await installer.create_account("Maria", "senha-forte-1", ENGINE)
    assert status["state"] == "done" and status["message"] == "Pronto! O Home Assistant está instalado e conectado."
    assert auth.oauth and auth.base_url == "http://localhost:8123"
    saved = (tmp_path / "auth.json").read_text()
    assert "REFRESH" in saved and "senha-forte-1" not in saved and "senha-forte-1" not in (tmp_path / "docker.json").read_text()


async def test_the_account_is_only_taken_when_it_is_time_and_with_a_real_password(tmp_path):
    installer, auth, _ = make_installer(tmp_path)
    with pytest.raises(HomeError, match="ainda não está pronto"):
        await installer.create_account("Maria", "senha-forte-1", ENGINE)
    await prepare(installer)
    with pytest.raises(HomeError, match="pelo menos 8 caracteres"):
        await installer.create_account("Maria", "curta", ENGINE)
    assert installer._status["code"] == "needs_account" and not auth.configured


async def test_a_refused_account_leaves_the_person_able_to_try_again(tmp_path):
    installer, auth, _ = make_installer(tmp_path, ha=FakeHA(users_status=400))
    await prepare(installer)
    with pytest.raises(HomeError, match="não aceitou criar a conta"):
        await installer.create_account("Maria", "senha-forte-1", ENGINE)
    assert installer._status["state"] == "ready" and installer._status["code"] == "needs_account" and not auth.configured


async def test_a_home_assistant_that_already_has_an_owner_goes_to_the_normal_connection(tmp_path):
    installer, auth, _ = make_installer(tmp_path, FakeDocker(container="running"), FakeHA(steps=[]), alexa=make_alexa(""))
    status = await prepare(installer)
    assert (status["state"], status["code"], status["message"]) == ("ready", "has_owner", HAS_OWNER) and not auth.configured
    with pytest.raises(HomeError):
        await installer.create_account("Maria", "senha-forte-1", ENGINE)


async def test_a_docker_that_is_off_is_opened_for_the_person(tmp_path):
    d = FakeDocker(daemon=False)
    installer, *_ = make_installer(tmp_path, d)
    assert (await prepare(installer))["state"] == "ready"
    assert d.did[:2] == ["open", "wait_daemon"]


@pytest.mark.parametrize("docker,code,message", [
    (FakeDocker(installed=False), "docker_missing", DOCKER_MISSING),                      # no setup for this system (Linux)
    (FakeDocker(daemon=False, desktop=False), "docker_off", DOCKER_OFF),
    (FakeDocker(daemon=False, daemon_after_open=False), "docker_slow", DOCKER_SLOW),
    (FakeDocker(daemon=False, opens=False), "docker_slow", DOCKER_SLOW),
])
async def test_a_docker_that_cannot_be_used_says_what_to_do(tmp_path, docker, code, message):
    installer, auth, _ = make_installer(tmp_path, docker)
    status = await prepare(installer)
    assert (status["state"], status["code"], status["message"]) == ("error", code, message)
    assert "pull" not in docker.did and not auth.configured


async def test_a_missing_docker_is_installed_then_opened_then_everything_goes_on(tmp_path):
    d = FakeDocker(installed=False, daemon=False)
    setup = FakeSetup(d)
    installer, *_ = make_installer(tmp_path, d, setup=setup)
    messages: list[str] = []
    original = installer._set
    installer._set = lambda *a, **k: (messages.append(a[2]), original(*a, **k))[1]
    status = await prepare(installer)
    assert status["state"] == "ready" and setup.did == ["download", "install"]
    assert d.did[:2] == ["open", "wait_daemon"] and "pull" in d.did
    assert any(m.startswith("Baixando o Docker Desktop… 12/700 MB") for m in messages)
    assert any("pedir a sua senha de administrador" in m for m in messages)


async def test_a_docker_that_needs_a_restart_says_so_and_stops(tmp_path):
    d = FakeDocker(installed=False, daemon=False)
    installer, *_ = make_installer(tmp_path, d, setup=FakeSetup(d, installs=False))
    status = await prepare(installer)
    assert (status["state"], status["code"], status["message"]) == ("error", "reboot", REBOOT) and "pull" not in d.did


async def test_a_failed_docker_install_is_a_sentence(tmp_path):
    d = FakeDocker(installed=False)
    installer, auth, _ = make_installer(tmp_path, d, setup=FakeSetup(d, fails=HomeError("a instalação do Docker foi cancelada")))
    status = await prepare(installer)
    assert status["state"] == "error" and status["message"] == "A instalação do Docker foi cancelada." and not auth.configured


async def test_an_existing_container_is_not_created_again(tmp_path):
    stopped = FakeDocker(container="stopped")
    installer, *_ = make_installer(tmp_path, stopped)
    assert (await prepare(installer))["state"] == "ready" and stopped.did == ["start"]
    running = FakeDocker(container="running")
    installer, *_ = make_installer(tmp_path, running, alexa=make_alexa(""))              # the integration was already there
    assert (await prepare(installer))["state"] == "ready" and running.did == []


async def test_a_running_home_assistant_is_restarted_when_the_alexa_was_just_added(tmp_path):
    running = FakeDocker(container="running")
    installer, *_ = make_installer(tmp_path, running, alexa=make_alexa("v5.0.0"))
    assert (await prepare(installer))["state"] == "ready" and running.did == ["restart"]
    failing = FakeDocker(container="running", restart=(False, "boom"))
    installer, *_ = make_installer(tmp_path, failing, alexa=make_alexa("v5.0.0"))
    status = await prepare(installer)
    assert status["state"] == "error" and "Não consegui reiniciar o Home Assistant" in status["message"]


@pytest.mark.parametrize("docker,text", [
    (FakeDocker(pull_ok=False), "Não consegui baixar o Home Assistant"),
    (FakeDocker(create=(False, "port is already allocated")), "port is already allocated"),
    (FakeDocker(container="stopped", start=(False, "boom")), "Não consegui ligar o Home Assistant"),
])
async def test_a_failing_step_is_a_sentence_with_the_reason(tmp_path, docker, text):
    installer, auth, _ = make_installer(tmp_path, docker)
    status = await prepare(installer)
    assert status["state"] == "error" and text in status["message"] and status["message"].endswith(".") and not auth.configured


async def test_a_failing_alexa_download_stops_before_home_assistant_is_touched(tmp_path):
    d = FakeDocker()
    installer, *_ = make_installer(tmp_path, d, alexa=make_alexa(fails=HomeError("não consegui baixar a integração da Alexa (o GitHub respondeu 503)")))
    status = await prepare(installer)
    assert status["state"] == "error" and "integração da Alexa" in status["message"] and d.did == []


async def test_a_home_assistant_that_never_comes_up_says_so(tmp_path):
    installer, auth, _ = make_installer(tmp_path, FakeDocker(), FakeHA(ready_after=10_000), wait=20.0)
    status = await prepare(installer)
    assert (status["state"], status["code"], status["message"]) == ("error", "ha_slow", HA_SLOW) and not auth.configured


async def test_two_installs_do_not_overlap(tmp_path):
    installer, *_ = make_installer(tmp_path)
    installer.start()
    with pytest.raises(HomeError, match="já está em andamento"):
        installer.start()
    await installer.wait()


async def test_a_surprise_ends_in_a_sentence_not_in_a_spinner(tmp_path):
    class Broken(FakeDocker):
        async def pull(self, on_line):
            raise RuntimeError("inesperado")
    installer, *_ = make_installer(tmp_path, Broken())
    status = await prepare(installer)
    assert status["state"] == "error" and "RuntimeError" in status["message"]


async def test_inspect_says_what_is_there_before_starting(tmp_path):
    d = FakeDocker(installed=False)
    installer, *_ = make_installer(tmp_path, d, setup=FakeSetup(d))
    info = await installer.inspect()
    assert info["docker"] == "no_docker" and info["container"] == "unknown" and info["docker_installable"] is True and info["docker_mb"] == 700 and info["managed"] is False
    assert info["alexa_help"].startswith("https://github.com/") and info["alexa_ready"] is False and info["platform"] in ("darwin", "win32", "linux")
    installer, *_ = make_installer(tmp_path, FakeDocker(daemon=False))
    info = await installer.inspect()
    assert info["docker"] == "daemon_off" and info["docker_installable"] is False and info["docker_mb"] == 0
    installer, *_ = make_installer(tmp_path, FakeDocker(container="running"))
    info = await installer.inspect()
    assert info["docker"] == "ready" and info["container"] == "running" and info["can_open_docker"] is True and info["image_mb"] > 0


# --- switching it on again when the Chakmati starts -----------------------------------------------------------------------------------------------
async def test_a_home_assistant_the_chakmati_installed_is_switched_on_at_start(tmp_path):
    d = FakeDocker(daemon=False, container="stopped")
    installer, *_ = make_installer(tmp_path, d)
    installer._mark_managed()
    await installer.ensure_up()
    assert d.did == ["open", "wait_daemon", "start"]


async def test_nothing_is_done_at_start_when_it_is_not_ours_or_already_running(tmp_path):
    d = FakeDocker(daemon=False, container="stopped")
    installer, *_ = make_installer(tmp_path, d)
    await installer.ensure_up()                                                     # not installed by the Chakmati: not touched
    assert d.did == []
    running = FakeDocker(container="running")
    installer, *_ = make_installer(tmp_path, running)
    installer._mark_managed()
    await installer.ensure_up()
    assert running.did == []
    missing = FakeDocker(installed=False)
    installer, *_ = make_installer(tmp_path, missing)
    installer._mark_managed()
    await installer.ensure_up()
    assert missing.did == []


async def test_it_never_installs_or_downloads_at_start_and_never_raises(tmp_path):
    d = FakeDocker(container="none")
    installer, *_ = make_installer(tmp_path, d)
    installer._mark_managed()
    await installer.ensure_up()
    assert "pull" not in d.did and "create" not in d.did                            # the person removed it: it is not brought back behind their back

    class Broken(FakeDocker):
        async def container(self):
            raise RuntimeError("boom")
    installer, *_ = make_installer(tmp_path, Broken())
    installer._mark_managed()
    await installer.ensure_up()


# --- the routes --------------------------------------------------------------------------------------------------------------------------------
UI = {"X-LiteAgent-UI": "1"}


class Gate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class LLM:
    async def chat(self, messages):
        return "ok"


def route_client(tmp_path, with_installer=True, docker=None):
    installer, auth, ha = make_installer(tmp_path, docker or FakeDocker(), FakeHA())
    link = HomeLink(auth, HomeAssistantClient(auth=auth), ha.client(), hosts=[], installer=installer if with_installer else None)
    store = JobStore(":memory:")
    return TestClient(create_app(Engine(Gate(), LLM(), store), store, home_link=link), base_url="http://127.0.0.1:8765"), installer, auth


def test_the_install_routes_are_not_there_without_an_installer(tmp_path):
    client, *_ = route_client(tmp_path, with_installer=False)
    assert client.get("/home/install").status_code == 404
    assert client.post("/home/install", json={"confirm": True}, headers=UI).status_code == 404
    assert client.post("/home/install/account", json={"password": "senha-forte-1"}, headers=UI).status_code == 404


def test_starting_needs_the_app_window_and_the_confirmation(tmp_path):
    client, installer, _ = route_client(tmp_path)
    assert client.post("/home/install", json={"confirm": True}).status_code == 403                 # a web page cannot start a download
    refused = client.post("/home/install", json={"confirm": False}, headers=UI)
    assert refused.status_code == 400 and "confirmação" in refused.json()["detail"]
    assert installer._status["state"] == "idle"
    assert client.post("/home/install/account", json={"password": "senha-forte-1"}).status_code == 403


def test_the_whole_install_through_the_routes(tmp_path):
    client, installer, auth = route_client(tmp_path)
    with client:
        before = client.get("/home/install").json()
        assert before["docker"] == "ready" and before["container"] == "none" and before["state"] == "idle"
        assert client.post("/home/install", json={"confirm": True}, headers=UI).status_code == 200
        for _ in range(500):
            status = client.get("/home/install").json()
            if status["state"] != "running":
                break
        assert status["state"] == "ready" and status["code"] == "needs_account" and not auth.configured
        short = client.post("/home/install/account", json={"name": "Maria", "password": "curta"}, headers=UI)
        assert short.status_code == 400 and "pelo menos 8" in short.json()["detail"]
        done = client.post("/home/install/account", json={"name": "Maria", "password": "senha-forte-1"}, headers=UI)
        assert done.status_code == 200 and done.json()["state"] == "done" and auth.oauth
        assert client.get("/home/status").json()["configured"] is True
