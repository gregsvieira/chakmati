"""Installing Docker Desktop for someone who does not have it, with the person's permission (the system asks for the administrator password).

Only the official installer is used, downloaded over https from desktop.docker.com, and run with the options Docker documents for a command-line install.
macOS and Windows only: on Linux Docker is a system service that the distribution's own tools install, so the Chakmati says so instead of running a script as root.
Windows may ask to restart (WSL2): the install then continues from where it stopped when the Chakmati is opened again."""

import asyncio
import getpass
import platform
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from chakmati.features.home.docker import run as run_command
from chakmati.features.home.models import HomeError

HOST = "desktop.docker.com"
MAC = "https://desktop.docker.com/mac/main/{arch}/Docker.dmg"
WINDOWS = "https://desktop.docker.com/win/main/{arch}/Docker%20Desktop%20Installer.exe"
SIZE_MB = {"darwin": 700, "win32": 600}   # estimates, for the question "may I download?"
MAX_BYTES = 2 * 1024 ** 3


def applescript_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class DockerSetup:
    def __init__(self, http: httpx.AsyncClient, run_fn=run_command, sys_platform: str = sys.platform, machine: str | None = None,
                 tmp_dir: str | None = None, user: Callable[[], str] = getpass.getuser):
        self._http, self._run = http, run_fn
        self._platform = sys_platform
        self._machine = (machine or platform.machine()).lower()
        self._tmp = Path(tmp_dir or tempfile.gettempdir())
        self._user = user

    def supported(self) -> bool:
        return self._platform in SIZE_MB

    def size_mb(self) -> int:
        return SIZE_MB.get(self._platform, 0)

    def url(self) -> str | None:
        arch = "arm64" if self._machine in ("arm64", "aarch64") else "amd64"
        if self._platform == "darwin":
            return MAC.format(arch=arch)
        if self._platform == "win32":
            return WINDOWS.format(arch=arch)
        return None

    def _file(self) -> Path:
        return self._tmp / ("Docker.dmg" if self._platform == "darwin" else "DockerDesktopInstaller.exe")

    async def download(self, on_progress: Callable[[int, int], None]) -> Path:
        url = self.url()
        if url is None or urlsplit(url).hostname != HOST:
            raise HomeError("não sei instalar o Docker neste sistema")
        target = self._file()
        try:
            async with self._http.stream("GET", url, follow_redirects=True, timeout=None) as response:
                if response.status_code != 200 or urlsplit(str(response.url)).scheme != "https":
                    raise HomeError(f"não consegui baixar o Docker Desktop (o servidor respondeu {response.status_code})")
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        done += len(chunk)
                        if done > MAX_BYTES:
                            raise HomeError("o instalador do Docker veio grande demais: não usei")
                        handle.write(chunk)
                        on_progress(done, total)
        except httpx.HTTPError as exc:
            raise HomeError(f"não consegui baixar o Docker Desktop: {exc}") from exc
        return target

    def command(self, installer: Path) -> list[str]:
        """The command that runs the installer with administrator rights (the system shows its own password window)."""
        if self._platform == "darwin":
            user = self._user()
            if not re.fullmatch(r"[A-Za-z0-9._-]+", user):
                raise HomeError("não consegui descobrir o seu usuário para instalar o Docker")
            q = lambda s: "'" + str(s).replace("'", "'\\''") + "'"   # noqa: E731
            script = (f"hdiutil attach -nobrowse -quiet {q(installer)} && {q('/Volumes/Docker/Docker.app/Contents/MacOS/install')} --accept-license --user={q(user)}; "
                      f"status=$?; hdiutil detach /Volumes/Docker -quiet; exit $status")
            return ["osascript", "-e", f"do shell script {applescript_quote(script)} with administrator privileges"]
        if self._platform == "win32":
            ps = ("$p = Start-Process -FilePath '" + str(installer).replace("'", "''") + "' -ArgumentList 'install','--quiet','--accept-license','--backend=wsl-2' "
                  "-Verb RunAs -PassThru -Wait; exit $p.ExitCode")
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
        raise HomeError("neste sistema o Docker se instala pelo gerenciador de pacotes da sua distribuição (veja docs.docker.com/engine/install)")

    async def install(self, installer: Path) -> None:
        code, out = await self._run(self.command(installer), 1800.0)
        installer.unlink(missing_ok=True)
        if code != 0:
            if code in (1, 128) and "cancel" in out.lower():
                raise HomeError("a instalação do Docker foi cancelada")
            raise HomeError(f"o instalador do Docker não terminou bem (código {code}{': ' + out[-100:] if out else ''})")
