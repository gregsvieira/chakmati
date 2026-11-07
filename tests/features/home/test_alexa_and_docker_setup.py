"""The Alexa integration put in Home Assistant's folder, and Docker Desktop installed with the person's permission."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from chakmati.features.home import alexa
from chakmati.features.home.docker import MAC_CLI, WINDOWS_CLI, DockerHome
from chakmati.features.home.docker_setup import DockerSetup, applescript_quote
from chakmati.features.home.models import HomeError


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


# --- the Alexa integration ------------------------------------------------------------------------------------------------------------------------
def github(release: dict, zips: dict[str, bytes], seen: list | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if str(request.url) == alexa.RELEASE_API:
            return httpx.Response(200, json=release)
        body = zips.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


ASSET = "https://github.com/alandtse/alexa_media_player/releases/download/v5.0.0/alexa_media.zip"
FILES = {"manifest.json": '{"domain": "alexa_media"}', "__init__.py": "# integration", "translations/pt-BR.json": "{}"}


async def test_the_release_asset_is_unpacked_into_the_custom_components_folder(tmp_path):
    http = github({"tag_name": "v5.0.0", "assets": [{"name": "alexa_media.zip", "browser_download_url": ASSET}]}, {ASSET: make_zip(FILES)})
    assert await alexa.install(http, str(tmp_path)) == "v5.0.0"
    target = tmp_path / "custom_components" / "alexa_media"
    assert json.loads((target / "manifest.json").read_text())["domain"] == "alexa_media"
    assert (target / "translations" / "pt-BR.json").is_file() and alexa.installed(str(tmp_path))


async def test_the_source_zip_is_used_when_there_is_no_asset(tmp_path):
    zipball = "https://api.github.com/repos/alandtse/alexa_media_player/zipball/v5.0.0"
    nested = {f"alandtse-alexa_media_player-abc/custom_components/alexa_media/{k}": v for k, v in FILES.items()}
    nested["alandtse-alexa_media_player-abc/README.md"] = "outra coisa"
    http = github({"tag_name": "v5.0.0", "assets": [], "zipball_url": zipball}, {zipball: make_zip(nested)})
    assert await alexa.install(http, str(tmp_path)) == "v5.0.0"
    target = tmp_path / "custom_components" / "alexa_media"
    assert (target / "manifest.json").is_file() and not (target / "README.md").exists() and not (tmp_path / "custom_components" / "README.md").exists()


async def test_a_copy_that_is_already_there_is_left_alone_and_nothing_is_downloaded(tmp_path):
    (tmp_path / "custom_components" / "alexa_media").mkdir(parents=True)
    (tmp_path / "custom_components" / "alexa_media" / "manifest.json").write_text("{}")
    seen: list = []
    assert await alexa.install(github({}, {}, seen), str(tmp_path)) == "" and seen == []


def test_nothing_can_be_written_outside_the_folder(tmp_path):
    evil = make_zip({"manifest.json": "{}", "../escaped.txt": "x", "/abs.txt": "x", "sub/../../escaped2.txt": "x", "ok.py": "1"})
    destination = tmp_path / "custom_components" / "alexa_media"
    assert alexa.unpack(evil, destination) == 2
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "custom_components" / "escaped2.txt").exists() and not Path("/abs.txt").exists()
    assert sorted(p.name for p in destination.iterdir()) == ["manifest.json", "ok.py"]


def test_a_new_copy_replaces_the_old_one(tmp_path):
    destination = tmp_path / "alexa_media"
    alexa.unpack(make_zip({"manifest.json": "{}", "old.py": "x"}), destination)
    alexa.unpack(make_zip({"manifest.json": "{}", "new.py": "x"}), destination)
    assert sorted(p.name for p in destination.iterdir()) == ["manifest.json", "new.py"]


@pytest.mark.parametrize("archive,message", [(b"not a zip", "corrompida"), (make_zip({"readme.txt": "x"}), "não parece ser a integração da Alexa")])
def test_a_bad_download_is_a_sentence(tmp_path, archive, message):
    with pytest.raises(HomeError, match=message):
        alexa.unpack(archive, tmp_path / "a")
    assert not (tmp_path / "a").exists()


async def test_only_github_addresses_are_downloaded(tmp_path):
    seen: list = []
    http = github({"tag_name": "v5", "assets": [{"name": "alexa_media.zip", "browser_download_url": "https://evil.example/alexa_media.zip"}]}, {}, seen)
    with pytest.raises(HomeError, match="inesperado"):
        await alexa.install(http, str(tmp_path))
    assert seen == [alexa.RELEASE_API]
    with pytest.raises(HomeError, match="inesperado"):
        await alexa._get(github({}, {}), "http://github.com/x")                      # not https
    with pytest.raises(HomeError, match="inesperado"):
        await alexa._get(github({}, {}), "https://github.com.evil.example/x")        # looks like github, is not


async def test_a_github_that_does_not_answer_is_a_sentence(tmp_path):
    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(HomeError, match="o GitHub respondeu 503"):
        await alexa.install(down, str(tmp_path))

    def boom(request):
        raise httpx.ConnectError("sem internet")
    with pytest.raises(HomeError, match="não consegui baixar a integração da Alexa"):
        await alexa.install(httpx.AsyncClient(transport=httpx.MockTransport(boom)), str(tmp_path))


async def test_a_huge_file_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setattr(alexa, "MAX_BYTES", 10)
    with pytest.raises(HomeError, match="grande demais"):
        await alexa._get(github({}, {ASSET: b"x" * 100}), ASSET)


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
