"""What the agent may do on the computer, decided here in code and never by the model.

Files are created only inside a workspace folder (default ~/Documents/Chakmati) and only with ordinary text extensions; the path
is checked after resolving `..` and symbolic links, nothing is ever overwritten silently, and nothing is made executable.
Programs are opened only if they are installed applications found on disk (never an arbitrary command); websites only
over http(s). Every name and text comes from the person's own request, never from a message or a web page."""

import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".py", ".sql", ".xml", ".log", ".ini", ".toml", ".tex", ".rtf", ".ics", ".srt"}
MAX_CONTENT = 100_000
MAX_NAME = 120
_BAD_NAME = re.compile(r"[\x00-\x1f<>:\"|?*\\]")


class ComputerError(Exception):
    pass


def plain(text: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c) and (c.isalnum() or c.isspace())).split())


def resolve_new_file(workspace: str | Path, relative: str) -> Path:
    """The absolute path for a new file named `relative` inside the workspace, or ComputerError."""
    root = Path(workspace).expanduser().resolve()
    name = (relative or "").strip().replace("\\", "/")
    if not name or len(name) > MAX_NAME * 2 or _BAD_NAME.search(name.replace("/", "")):
        raise ComputerError("nome de arquivo inválido")
    candidate = Path(name)
    if candidate.is_absolute() or name.startswith("~"):
        try:  # an absolute path is fine only if it is already inside the workspace
            candidate = Path(os.path.expanduser(name)).resolve().relative_to(root)
        except ValueError:
            raise ComputerError(f"só posso criar arquivos dentro de {root}") from None
    parts = candidate.parts
    if any(p in ("..", "") or p.startswith(".") for p in parts):
        raise ComputerError("não crio arquivos ocultos nem fora da pasta de trabalho")
    if len(parts) > 4 or any(len(p) > MAX_NAME for p in parts):
        raise ComputerError("caminho longo demais")
    if candidate.suffix.lower() not in TEXT_EXTENSIONS:
        raise ComputerError(f"só crio arquivos de texto ({', '.join(sorted(TEXT_EXTENSIONS)[:8])}…)")
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ComputerError(f"só posso criar arquivos dentro de {root}") from None
    return target


def check_content(content: str) -> str:
    if not isinstance(content, str) or len(content) > MAX_CONTENT or "\x00" in content:
        raise ComputerError("conteúdo inválido ou grande demais")
    return content


def check_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ComputerError("só abro endereços http ou https")
    return parsed.geturl()


def installed_apps() -> dict[str, str]:
    """{plain name: app name} of the applications installed (macOS). Empty elsewhere."""
    if sys.platform != "darwin":
        return {}
    found: dict[str, str] = {}
    for folder in ("/Applications", "/System/Applications", "/System/Applications/Utilities", "/Applications/Utilities", os.path.expanduser("~/Applications")):
        try:
            for entry in os.listdir(folder):
                if entry.endswith(".app"):
                    found.setdefault(plain(entry[:-4]), entry[:-4])
        except OSError:
            continue
    return found


def find_app(query: str, apps: dict[str, str]) -> tuple[str | None, list[str]]:
    """(app, []) when the name is clear, (None, candidates) when several fit, (None, []) when none."""
    q = plain(query)
    if not q:
        return None, []
    if q in apps:
        return apps[q], []
    words = set(q.split())
    fits = sorted({real for key, real in apps.items() if words <= set(key.split()) or q in key})
    if len(fits) == 1:
        return fits[0], []
    # one app whose name starts with the query ("chrome" -> "Google Chrome" is handled above; "cal" -> "Calendar")
    starts = [real for key, real in apps.items() if key.startswith(q)]
    if len(starts) == 1:
        return starts[0], []
    return None, fits[:5]


def check_openable_path(path: str, workspace: str | Path) -> Path:
    """A file or folder to open: inside the workspace or the person's Documents/Desktop/Downloads, never hidden."""
    target = Path(os.path.expanduser(path)).resolve()
    home = Path.home().resolve()
    roots = [Path(workspace).expanduser().resolve(), home / "Documents", home / "Desktop", home / "Downloads"]
    root = next((r for r in roots if _inside(target, r)), None)
    if root is None or any(part.startswith(".") for part in target.relative_to(root).parts):
        raise ComputerError("só abro itens da pasta de trabalho, Documentos, Mesa ou Downloads")
    if not target.exists():
        raise ComputerError("esse item não existe")
    return target


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
