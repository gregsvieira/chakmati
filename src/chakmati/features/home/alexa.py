"""The Alexa integration for Home Assistant (*Alexa Media Player*), put in place before Home Assistant starts, so the person never opens a store of add-ons.

It is a folder of files that Home Assistant loads from its own settings folder (`custom_components/alexa_media`). The Chakmati downloads the project's
latest release from GitHub and unpacks it there. Logging in to Amazon is still done once, inside Home Assistant (it needs the person's own account)."""

import io
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from chakmati.features.home.models import HomeError

RELEASE_API = "https://api.github.com/repos/alandtse/alexa_media_player/releases/latest"
INTEGRATION = "alexa_media"
HELP_PAGE = "https://github.com/alandtse/alexa_media_player"
MAX_BYTES = 30 * 1024 * 1024
ALLOWED_HOSTS = ("github.com", "api.github.com", "githubusercontent.com", "codeload.github.com")


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return urlsplit(url).scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def target_dir(config_dir: str) -> Path:
    return Path(config_dir) / "custom_components" / INTEGRATION


def installed(config_dir: str) -> bool:
    return (target_dir(config_dir) / "manifest.json").is_file()


async def _get(http: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    if not _host_ok(url):
        raise HomeError("endereço de download inesperado: não baixei nada")
    try:
        response = await http.get(url, follow_redirects=True, timeout=60.0, **kw)
    except httpx.HTTPError as exc:
        raise HomeError(f"não consegui baixar a integração da Alexa: {exc}") from exc
    if response.status_code != 200 or not _host_ok(str(response.url)):
        raise HomeError(f"não consegui baixar a integração da Alexa (o GitHub respondeu {response.status_code})")
    if len(response.content) > MAX_BYTES:
        raise HomeError("o arquivo da integração da Alexa veio grande demais: não usei")
    return response


def unpack(archive: bytes, destination: Path) -> int:
    """Unpacks the integration into `destination` (emptied first). Handles both shapes of the release: the files at the top of the zip, or inside
    `<repo>/custom_components/alexa_media/`. Nothing can land outside `destination`. Returns how many files were written."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise HomeError("a integração da Alexa veio corrompida") from exc
    marker = f"/custom_components/{INTEGRATION}/"
    names = [n for n in zf.namelist() if not n.endswith("/")]
    nested = [n for n in names if marker in "/" + n]
    members = [(n, n.split(marker.lstrip("/"), 1)[1]) for n in nested] if nested else [(n, n) for n in names]
    if not any(rel == "manifest.json" for _, rel in members):
        raise HomeError("o arquivo baixado não parece ser a integração da Alexa")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    root = destination.resolve()
    written = 0
    for name, rel in members:
        out = (destination / rel).resolve()
        if root != out and root not in out.parents:      # "../x" or an absolute path in the zip: never written
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(name))
        written += 1
    return written


async def install(http: httpx.AsyncClient, config_dir: str) -> str:
    """Downloads and unpacks the latest release. Returns its version. A copy that is already there is left alone (returns "")."""
    if installed(config_dir):
        return ""
    meta = (await _get(http, RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Chakmati"})).json()
    asset = next((a.get("browser_download_url") for a in meta.get("assets", []) if a.get("name") == f"{INTEGRATION}.zip"), None)
    url = asset or meta.get("zipball_url")
    if not url:
        raise HomeError("não achei onde baixar a integração da Alexa")
    unpack((await _get(http, url, headers={"User-Agent": "Chakmati"})).content, target_dir(config_dir))
    return str(meta.get("tag_name") or "")
