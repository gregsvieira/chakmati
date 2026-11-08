"""Docker Desktop installed with the person's permission."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from chakmati.features.home.docker import MAC_CLI, WINDOWS_CLI, DockerHome
from chakmati.features.home.docker_setup import DockerSetup, applescript_quote
from chakmati.features.home.models import HomeError


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


# --- Docker Desktop ------------------------------------------------------------------------------------------------------------------------------
def setup(platform="darwin", machine="arm64", tmp_path=None, run=None, user="maria"):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 3000, headers={"content-length": "3000"})))
    return DockerSetup(http, run_fn=run, sys_platform=platform, machine=machine, tmp_dir=str(tmp_path) if tmp_path else None, user=lambda: user)


@pytest.mark.parametrize("platform,machine,url", [
    ("darwin", "arm64", "https://desktop.docker.com/mac/main/arm64/Docker.dmg"),
    ("darwin", "x86_64", "https://desktop.docker.com/mac/main/amd64/Docker.dmg"),
    ("win32", "AMD64", "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"),
    ("win32", "ARM64", "https://desktop.docker.com/win/main/arm64/Docker%20Desktop%20Installer.exe"),
])
def test_the_official_installer_for_each_system(platform, machine, url):
    s = setup(platform, machine)
    assert s.url() == url and s.supported() and s.size_mb() > 0


def test_linux_is_not_installed_by_the_chakmati():
    s = setup("linux")
    assert s.url() is None and not s.supported() and s.size_mb() == 0
    with pytest.raises(HomeError, match="gerenciador de pacotes"):
        s.command(Path("/tmp/x"))


def test_on_macos_the_installer_runs_through_the_system_password_window(tmp_path):
    cmd = setup("darwin", tmp_path=tmp_path).command(tmp_path / "Docker.dmg")
    assert cmd[:2] == ["osascript", "-e"] and cmd[2].startswith("do shell script ") and cmd[2].endswith(" with administrator privileges")
    for part in ("hdiutil attach -nobrowse -quiet", "/Volumes/Docker/Docker.app/Contents/MacOS/install", "--accept-license", "--user='maria'", "hdiutil detach /Volumes/Docker -quiet"):
        assert part in cmd[2]


def test_on_windows_the_installer_runs_elevated_with_wsl2(tmp_path):
    cmd = setup("win32", "AMD64", tmp_path).command(tmp_path / "DockerDesktopInstaller.exe")
    assert cmd[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert "-Verb RunAs" in cmd[4] and "'install','--quiet','--accept-license','--backend=wsl-2'" in cmd[4] and "exit $p.ExitCode" in cmd[4]


@pytest.mark.parametrize("user", ["maria; rm -rf /", "a b", "$(whoami)", ""])
def test_a_strange_user_name_never_reaches_the_command(tmp_path, user):
    with pytest.raises(HomeError, match="seu usuário"):
        setup("darwin", tmp_path=tmp_path, user=user).command(tmp_path / "Docker.dmg")


def test_quotes_in_the_script_cannot_break_out_of_the_applescript_string():
    assert applescript_quote('a "b" \\ c') == '"a \\"b\\" \\\\ c"'


async def test_the_download_reports_progress_and_writes_the_file(tmp_path):
    s = setup("darwin", tmp_path=tmp_path)
    seen: list = []
    path = await s.download(lambda done, total: seen.append((done, total)))
    assert path == tmp_path / "Docker.dmg" and path.stat().st_size == 3000 and seen[-1] == (3000, 3000)


async def test_a_download_that_fails_or_is_huge_is_a_sentence(tmp_path, monkeypatch):
    bad = DockerSetup(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))), sys_platform="darwin", machine="arm64", tmp_dir=str(tmp_path))
    with pytest.raises(HomeError, match="o servidor respondeu 503"):
        await bad.download(lambda d, t: None)
    monkeypatch.setattr("chakmati.features.home.docker_setup.MAX_BYTES", 100)
    with pytest.raises(HomeError, match="grande demais"):
        await setup("darwin", tmp_path=tmp_path).download(lambda d, t: None)
    with pytest.raises(HomeError, match="não sei instalar"):
        await setup("linux").download(lambda d, t: None)


async def test_installing_runs_the_command_deletes_the_installer_and_reports_a_failure(tmp_path):
    calls: list = []

    async def ok(args, timeout):
        calls.append((args[0], timeout))
        return 0, ""
    file = tmp_path / "Docker.dmg"
    file.write_bytes(b"x")
    await setup("darwin", tmp_path=tmp_path, run=ok).install(file)
    assert calls[0][0] == "osascript" and not file.exists()

    async def fails(args, timeout):
        return 1, "execution error: User canceled. (-128)"
    file.write_bytes(b"x")
    with pytest.raises(HomeError, match="foi cancelada"):
        await setup("darwin", tmp_path=tmp_path, run=fails).install(file)

    async def broken(args, timeout):
        return 9, "falhou"
    file.write_bytes(b"x")
    with pytest.raises(HomeError, match="não terminou bem \\(código 9"):
        await setup("darwin", tmp_path=tmp_path, run=broken).install(file)


# --- the docker program, just installed -----------------------------------------------------------------------------------------------------------
def test_docker_is_found_by_name_or_where_docker_desktop_puts_it(tmp_path):
    named = DockerHome(str(tmp_path), which=lambda n: "/usr/local/bin/docker", platform="darwin", exists=lambda p: False)
    assert named.cli() == "docker"
    just_installed_mac = DockerHome(str(tmp_path), which=lambda n: None, platform="darwin", exists=lambda p: p == MAC_CLI)
    assert just_installed_mac.cli() == MAC_CLI
    just_installed_win = DockerHome(str(tmp_path), which=lambda n: None, platform="win32", exists=lambda p: p == WINDOWS_CLI)
    assert just_installed_win.cli() == WINDOWS_CLI
    assert DockerHome(str(tmp_path), which=lambda n: None, platform="linux", exists=lambda p: True).cli() == "docker"


async def test_the_commands_use_the_program_that_was_found_and_restart_exists(tmp_path):
    calls: list = []

    async def run_fn(args, timeout=60.0):
        calls.append(args)
        return 0, "true"
    d = DockerHome(str(tmp_path), run_fn=run_fn, which=lambda n: None, platform="darwin", exists=lambda p: p == MAC_CLI)
    await d.daemon_ready()
    await d.container()
    await d.restart()
    assert [c[0] for c in calls] == [MAC_CLI] * 3 and calls[2][1:] == ["restart", "chakmati-homeassistant"]
    assert d.config_dir == str(tmp_path)
