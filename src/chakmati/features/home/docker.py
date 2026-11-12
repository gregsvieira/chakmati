"""Home Assistant in Docker, looked after by the Chakmati so the person never types a Docker command.

Everything here is a plain `docker` command with a fixed list of arguments (never a shell, never text from the person). The container is
published on this computer only (127.0.0.1:8123): nothing on the network can reach it. Its settings live in a folder of the Chakmati's own
(~/.chakmati-agent/homeassistant), so removing the container loses nothing."""

import asyncio
import os
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

CONTAINER = "chakmati-homeassistant"
IMAGE = "ghcr.io/home-assistant/home-assistant:stable"
HOST_PORT = 8123
URL = f"http://localhost:{HOST_PORT}"
IMAGE_SIZE_MB = 1000   # an estimate for the question "may I download?"; the real size depends on the day's image
DOWNLOAD_PAGE = "https://www.docker.com/products/docker-desktop/"
MAC_APP = "/Applications/Docker.app"
WINDOWS_APP = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
MAC_CLI = "/Applications/Docker.app/Contents/Resources/bin/docker"
WINDOWS_CLI = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"   # just installed: not on the PATH of programs that were already open

Run = Callable[[list[str], float], Awaitable[tuple[int, str]]]
Stream = Callable[[list[str], Callable[[str], None], float], Awaitable[int]]


async def run(args: list[str], timeout: float = 60.0) -> tuple[int, str]:
    """(exit code, output) of one command; 127 when the program is not there, 124 when it took too long."""
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except (FileNotFoundError, PermissionError):
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, ""
    return proc.returncode or 0, out.decode("utf-8", "replace").strip()


async def stream(args: list[str], on_line: Callable[[str], None], timeout: float = 1800.0) -> int:
    """Runs a command and hands each line of its output to `on_line` as it appears (a download shows its progress that way)."""
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except (FileNotFoundError, PermissionError):
        return 127

    async def pump():
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                on_line(line)

    try:
        await asyncio.wait_for(pump(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124
    return await proc.wait()


def local_timezone() -> str:
    """The computer's time zone as Home Assistant wants it ("America/Sao_Paulo"); UTC when it cannot be told."""
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return os.environ.get("TZ") or "UTC"


class DockerHome:
    def __init__(self, config_dir: str, run_fn: Run = run, stream_fn: Stream = stream, which=shutil.which, platform: str = sys.platform,
                 exists=os.path.exists, sleep=asyncio.sleep, clock=time.monotonic, timezone: str | None = None):
        self._dir = config_dir
        self._run, self._stream, self._which = run_fn, stream_fn, which
        self._platform, self._exists, self._sleep, self._clock = platform, exists, sleep, clock
        self._tz = timezone

    # --- what is there -------------------------------------------------------------------------------------------------------------
    @property
    def config_dir(self) -> str:
        return self._dir

    def cli(self) -> str:
        """The `docker` program: by its name when the system finds it, otherwise where Docker Desktop puts it (it may be just installed)."""
        if self._which("docker"):
            return "docker"
        for system, path in (("darwin", MAC_CLI), ("win32", WINDOWS_CLI)):
            if self._platform == system and self._exists(path):
                return path
        return "docker"

    def installed(self) -> bool:
        return self._which("docker") is not None or self.desktop_app() is not None

    def desktop_app(self) -> str | None:
        """The Docker Desktop program this computer has, if any (the one the Chakmati can open for the person)."""
        for system, path in (("darwin", MAC_APP), ("win32", WINDOWS_APP)):
            if self._platform == system and self._exists(path):
                return path
        return None

    async def daemon_ready(self) -> bool:
        code, _ = await self._run([self.cli(), "info", "--format", "{{.ServerVersion}}"], 15.0)
        return code == 0

    async def container(self) -> str:
        """"none" (not created), "stopped" or "running"."""
        code, out = await self._run([self.cli(), "inspect", "--format", "{{.State.Running}}", CONTAINER], 15.0)
        if code != 0:
            return "none"
        return "running" if out.strip() == "true" else "stopped"

    async def moved(self) -> bool:
        """True when the container keeps its settings in another folder than the one the Chakmati uses now (the data folder was renamed from .lite-agent)."""
        code, out = await self._run([self.cli(), "inspect", "--format", '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}', CONTAINER], 15.0)
        source = out.strip() if code == 0 else ""
        return bool(source) and os.path.realpath(source) != os.path.realpath(self._dir)

    async def remove(self) -> bool:
        code, _ = await self._run([self.cli(), "rm", "-f", CONTAINER], 60.0)
        return code == 0

    # --- doing ----------------------------------------------------------------------------------------------------------------------
    async def open_desktop(self) -> bool:
        """Opens Docker Desktop (macOS and Windows); Linux has no program to open: the daemon is a system service."""
        app = self.desktop_app()
        if app is None:
            return False
        if self._platform == "darwin":
            code, _ = await self._run(["open", "-a", "Docker"], 20.0)
            return code == 0
        try:
            await asyncio.create_subprocess_exec(app, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return False
        return True

    async def wait_for_daemon(self, seconds: float = 240.0, every: float = 3.0) -> bool:
        deadline = self._clock() + seconds
        while self._clock() < deadline:
            if await self.daemon_ready():
                return True
            await self._sleep(every)
        return False

    async def pull(self, on_line: Callable[[str], None]) -> bool:
        return await self._stream([self.cli(), "pull", IMAGE], on_line, 3600.0) == 0

    async def create(self) -> tuple[bool, str]:
        Path(self._dir).mkdir(parents=True, exist_ok=True)
        code, out = await self._run([
            self.cli(), "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
            "-p", f"127.0.0.1:{HOST_PORT}:8123", "-v", f"{self._dir}:/config", "-e", f"TZ={self._tz or local_timezone()}", IMAGE], 180.0)
        return code == 0, out

    async def start(self) -> tuple[bool, str]:
        code, out = await self._run([self.cli(), "start", CONTAINER], 60.0)
        return code == 0, out

    async def restart(self) -> tuple[bool, str]:
        """Starts it again so it loads what was put in its folder while it ran (the Alexa integration)."""
        code, out = await self._run([self.cli(), "restart", CONTAINER], 120.0)
        return code == 0, out
