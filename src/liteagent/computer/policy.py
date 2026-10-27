"""The command policy: what the agent may run, decided in code.

A command is a STRING from the person's request. It is never given to a shell: it is split into words, every word is checked
against a fixed table, and the program is started directly with those words (no pipes, no redirects, no expansion). Three classes:

  safe      read-only commands and creating/copying/moving things INSIDE the workspace without overwriting. These can be kept
            approved by the person ("manter aprovado").
  run       starting a script (python/node/shell) the person named: ALWAYS asks, never kept approved. The script is shown.
  download  fetching a file from the internet into the workspace: ALWAYS asks, never kept approved.

Everything else is refused: deleting, changing permissions, sudo, installing, archiving/converting, editing in place, running
programs of any other kind, executables (.exe .bat ...), anything outside the allowed folders, hidden or secret-looking files.
Checks run when a command is proposed AND again right before it runs."""

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .secrets import looks_secret

SAFE, RUN, DOWNLOAD = "safe", "run", "download"
EXECUTABLE_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".psm1", ".vbs", ".vbe", ".wsf", ".hta", ".jar", ".app", ".dmg", ".pkg",
                  ".command", ".apk", ".dll", ".so", ".dylib", ".bin", ".run", ".deb", ".rpm", ".appimage", ".lnk", ".reg", ".workflow", ".action", ".scpt", ".applescript"}
SCRIPT_RUNNERS = {"python3": {".py"}, "python": {".py"}, "node": {".js", ".mjs"}, "bash": {".sh", ".bash"}, "sh": {".sh"}, "zsh": {".sh", ".zsh"}}
MAX_COMMAND = 400
MAX_SCRIPT_BYTES = 200_000
_METACHAR = re.compile(r"[;&|<>`$(){}*?!\\\n\r\x00\[\]~#]")
_URL = re.compile(r"https://[^\s'\"`;|<>(){}\\]+")  # a web address may carry ? & # = (there is no shell to read them)
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_./=:@+,%-]{1,200}$")
_DANGEROUS_SCRIPT = [re.compile(p, re.IGNORECASE) for p in (
    r"\brm\s+-\w*[rf]", r"\brmdir\b", r"\bunlink\b", r"shutil\.rmtree", r"os\.(remove|unlink|rmdir|removedirs)\b", r"Path\([^)]*\)\.(unlink|rmdir)",
    r"fs\.(rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)\b", r"\bsudo\b", r"\bmkfs\b", r"\bdd\s+if=", r"chmod\s+[0-7]*7[0-7]*", r"curl[^\n|]*\|\s*(ba)?sh",
    r"wget[^\n|]*\|\s*(ba)?sh", r"/dev/(sd|disk|rdisk)", r"osascript", r"\bdiskutil\b", r"launchctl", r"\bkillall\b", r"/etc/|/System/|~/Library|/Library/",
    r"\.ssh|\.aws|\.gnupg|keychain|id_rsa", r"\bimport\s+(socket|requests|urllib|http|ftplib|smtplib|subprocess|ctypes)\b", r"\bfrom\s+(socket|requests|urllib|http|subprocess|ctypes)\b", r"require\(['\"](child_process|net|http|https|dgram|tls)['\"]\)", r"os\.system|subprocess|child_process|exec\(|eval\(|__import__\(|importlib", r"socket\.|urllib|requests\.|http\.client|fetch\(|XMLHttpRequest",
)]

REFUSED_WORDS = {
    "rm": "apagar arquivos", "rmdir": "apagar pastas", "unlink": "apagar arquivos", "shred": "apagar arquivos", "dd": "gravar direto em disco", "mkfs": "formatar disco",
    "diskutil": "mexer em discos", "sudo": "executar como administrador", "su": "trocar de usuário", "chmod": "mudar permissões", "chown": "mudar donos", "chgrp": "mudar grupos",
    "kill": "encerrar processos", "killall": "encerrar processos", "pkill": "encerrar processos", "launchctl": "serviços do sistema", "defaults": "preferências do sistema",
    "security": "chaveiro do sistema", "osascript": "automação do sistema", "ssh": "acesso remoto", "scp": "cópia remota", "sftp": "cópia remota", "nc": "rede", "ncat": "rede",
    "brew": "instalar programas", "pip": "instalar programas", "pip3": "instalar programas", "npm": "instalar programas", "npx": "instalar programas", "gem": "instalar programas",
    "apt": "instalar programas", "apt-get": "instalar programas", "yum": "instalar programas", "port": "instalar programas", "git": "git ainda não",
    "tar": "compactar/converter formatos", "zip": "compactar/converter formatos", "unzip": "descompactar", "gzip": "compactar/converter formatos", "sed": "editar no lugar",
    "awk": "scripts", "perl": "scripts", "ruby": "scripts", "xargs": "executar comandos montados", "env": "executar outros programas", "eval": "executar texto", "exec": "executar texto",
    "nano": "editor interativo (peça para criar ou editar o arquivo)", "vi": "editor interativo", "vim": "editor interativo", "emacs": "editor interativo", "open": "abrir (use \"abre o ...\")",
    "find": "pode apagar/executar", "tee": "escrever em arquivos", "ln": "atalhos", "mount": "montar discos", "umount": "montar discos", "shutdown": "desligar", "reboot": "reiniciar",
    "networksetup": "rede", "systemsetup": "sistema", "csrutil": "sistema", "spctl": "sistema", "xattr": "atributos de arquivo", "pbcopy": "área de transferência", "pbpaste": "área de transferência",
}


class PolicyError(Exception):
    """The command is not allowed; the message says why in Portuguese."""


@dataclass(frozen=True)
class Checked:
    argv: list[str]
    cls: str                       # SAFE | RUN | DOWNLOAD
    label: str                     # one line for the person
    checks: list[str] = field(default_factory=list)
    preview: Path | None = None    # a script the person should look at before saying yes
    reads: tuple[Path, ...] = ()
    writes: tuple[Path, ...] = ()
    timeout: int = 30

    @property
    def shown(self) -> str:
        return shlex.join(self.argv)


@dataclass(frozen=True)
class Roots:
    workspace: Path
    read_only: tuple[Path, ...]
    # Only when checking a plan: what the EARLIER steps of the plan will have created (so "create a.txt, then copy a.txt" is not refused
    # for a file that does not exist yet), and which of those are folders.
    planned: frozenset = frozenset()
    planned_dirs: frozenset = frozenset()

    def after(self, writes, dirs=()) -> "Roots":
        """The same roots as they will be once a step that writes `writes` (and creates the folders `dirs`) has run."""
        created = set(self.planned) | {Path(p) for p in writes} | {Path(p) for p in dirs}
        folders = set(self.planned_dirs) | {Path(p) for p in dirs}
        for path in list(created):  # the folders in between exist too
            for parent in path.parents:
                if parent == self.workspace or self.workspace not in parent.parents:
                    break
                created.add(parent)
                folders.add(parent)
        return Roots(self.workspace, self.read_only, frozenset(created), frozenset(folders))

    @classmethod
    def make(cls, workspace: str | Path, home: str | Path | None = None) -> "Roots":
        home_path = Path(home or Path.home()).expanduser().resolve()
        return cls(Path(workspace).expanduser().resolve(), tuple((home_path / d).resolve() for d in ("Documents", "Desktop", "Downloads")))

    @property
    def readable(self) -> tuple[Path, ...]:
        return (self.workspace, *self.read_only)


def exists_in(path: Path, roots: "Roots") -> bool:
    return path.exists() or path.is_symlink() or path in roots.planned


def is_dir_in(path: Path, roots: "Roots") -> bool:
    return path.is_dir() or path in roots.planned_dirs


def is_file_in(path: Path, roots: "Roots") -> bool:
    return path.is_file() or (path in roots.planned and path not in roots.planned_dirs)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _clean(path: Path, root: Path, what: str) -> None:
    rel = path.relative_to(root)
    if any(part.startswith(".") for part in rel.parts):
        raise PolicyError(f"{what}: não mexo em itens ocultos")
    if looks_secret(str(rel)) or looks_secret(path.name):
        raise PolicyError(f"{what}: o nome parece de senha/chave/documento pessoal, então não leio nem mexo")
    if path.suffix.lower() in EXECUTABLE_EXT:
        raise PolicyError(f"{what}: não mexo em programas executáveis ({path.suffix})")


def resolve(word: str, roots: Roots, *, write: bool = False, must_exist: bool | None = None, what: str = "caminho", editable: bool = False) -> Path:
    """The resolved path for a word, inside the allowed folders only (writes: only the workspace)."""
    if not word or word.startswith("-") or "\x00" in word:
        raise PolicyError(f"{what} inválido")
    raw = Path(word)
    path = (raw if raw.is_absolute() else roots.workspace / raw).resolve()
    allowed = list(roots.readable) if editable else ([roots.workspace] if write else list(roots.readable))
    root = next((r for r in allowed if _inside(path, r)), None)
    if root is None:
        where = "a pasta de trabalho" if write else "a pasta de trabalho, Documentos, Mesa ou Downloads"
        raise PolicyError(f"{what}: só posso {'escrever em' if write else 'usar'} {where}")
    if path != root:
        _clean(path, root, what)
    exists = exists_in(path, roots)
    if must_exist is True and not exists:
        raise PolicyError(f"{what}: não existe")
    if must_exist is False and exists:
        raise PolicyError(f"{what}: já existe (não sobrescrevo)")
    return path


def _flags(args: list[str], allowed: set[str], what: str) -> tuple[set[str], list[str]]:
    flags: set[str] = set()
    rest: list[str] = []
    for a in args:
        if a.startswith("-") and len(a) > 1 and not re.fullmatch(r"-\d+", a):
            letters = a[1:]
            if a.startswith("--") or not set(letters) <= allowed:
                raise PolicyError(f"{what}: opção {a} não permitida")
            flags |= set(letters)
        else:
            rest.append(a)
    return flags, rest


def _split(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
        raise PolicyError("comando vazio ou grande demais")
    if _METACHAR.search(_URL.sub("", command)):
        raise PolicyError("comando com encadeamento, redirecionamento, curingas ou expansão (; | & > < $ ` * ? ~ ...) não é permitido: um comando por vez, sem atalhos do shell")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        raise PolicyError("aspas do comando não fecham") from None
    if not argv or any("\x00" in a for a in argv):
        raise PolicyError("comando vazio")
    return argv


def check(command: str, roots: Roots) -> Checked:
    argv = _split(command)
    name = argv[0]
    if "/" in name:
        raise PolicyError("rode só pelo nome do programa (nada de caminho ou ./)")
    if name in REFUSED_WORDS:
        raise PolicyError(f"não faço isso ({REFUSED_WORDS[name]})")
    args = argv[1:]
    handler = _HANDLERS.get(name)
    if handler is not None:
        return handler(name, args, roots)
    if name in SCRIPT_RUNNERS:
        return _run_script(name, args, roots)
    raise PolicyError(f"o comando \"{name}\" não está na lista de comandos permitidos")


# ---------------------------------------------------------------------------------------------------- safe commands
def _simple(name: str, args: list[str], roots: Roots) -> Checked:
    flags_ok = {"pwd": set(), "date": set(), "df": {"h"}, "echo": set()}[name]
    if name == "echo":
        return Checked([name, *args], SAFE, "mostrar texto", ["sem redirecionamento"])
    flags, rest = _flags(args, flags_ok, name)
    if rest:
        raise PolicyError(f"{name} não aceita argumentos aqui")
    return Checked([name, *[f"-{f}" for f in sorted(flags)]], SAFE, {"pwd": "mostrar a pasta atual", "date": "mostrar a data", "df": "mostrar o espaço em disco"}[name], ["somente leitura"])


def _read_paths(name: str, args: list[str], roots: Roots, flag_set: set[str], *, min_paths: int = 1, max_paths: int = 8, dirs_ok: bool = True) -> tuple[list[str], list[Path]]:
    flags, rest = _flags(args, flag_set, name)
    if not (min_paths <= len(rest) <= max_paths):
        raise PolicyError(f"{name}: informe {min_paths}{'' if min_paths == max_paths else ' a ' + str(max_paths)} caminho(s)")
    paths = [resolve(w, roots, must_exist=True, what=name) for w in rest]
    if not dirs_ok and any(is_dir_in(p, roots) for p in paths):
        raise PolicyError(f"{name}: só funciona com arquivos")
    return [f"-{f}" for f in sorted(flags)], paths


def _ls(name, args, roots):
    flags, rest = _flags(args, set("lahtrR1S"), "ls")
    paths = [resolve(w, roots, must_exist=True, what="ls") for w in rest] or [roots.workspace]
    if len(paths) > 4:
        raise PolicyError("ls: no máximo 4 caminhos")
    return Checked(["ls", *[f"-{f}" for f in sorted(flags)], *map(str, paths)], SAFE, "listar", ["somente leitura", "dentro das pastas permitidas"], reads=tuple(paths))


def _cat_like(name, args, roots):
    flag_set = {"cat": set(), "head": set(), "tail": set(), "wc": set("lwc"), "stat": set(), "file": set("b")}[name]
    extra: list[str] = []
    if name in ("head", "tail") and len(args) >= 2 and args[0] == "-n" and re.fullmatch(r"\d{1,4}", args[1]):
        extra, args = ["-n", args[1]], args[2:]
    flags, paths = _read_paths(name, args, roots, flag_set, dirs_ok=name in ("stat", "file", "wc") and False)
    for p in paths:
        if p.stat().st_size > 5_000_000:
            raise PolicyError(f"{name}: arquivo grande demais (mais de 5 MB)")
    return Checked([name, *extra, *flags, *map(str, paths)], SAFE, f"mostrar ({name})", ["somente leitura", "o resultado passa por um filtro que esconde senhas e dados pessoais"], reads=tuple(paths))


def _du(name, args, roots):
    flags, paths = _read_paths("du", args, roots, set("sh"), min_paths=1, max_paths=3)
    return Checked(["du", *flags, *map(str, paths)], SAFE, "tamanho", ["somente leitura"], reads=tuple(paths))


def _grep(name, args, roots):
    flags, rest = _flags(args, set("nicrlvH"), "grep")
    if len(rest) < 2 or len(rest) > 5:
        raise PolicyError("grep: use grep [opções] texto arquivo")
    pattern, files = rest[0], rest[1:]
    if pattern.startswith("-") or len(pattern) > 100:
        raise PolicyError("grep: texto de busca inválido")
    paths = [resolve(w, roots, must_exist=True, what="grep") for w in files]
    return Checked(["grep", *[f"-{f}" for f in sorted(flags)], "-e", pattern, "--", *map(str, paths)], SAFE, f"buscar \"{pattern}\"", ["somente leitura"], reads=tuple(paths))


def _mkdir(name, args, roots):
    flags, rest = _flags(args, {"p"}, "mkdir")
    if not 1 <= len(rest) <= 5:
        raise PolicyError("mkdir: informe de 1 a 5 pastas")
    paths = []
    for w in rest:
        path = resolve(w, roots, write=True, what="mkdir")
        if path == roots.workspace:
            raise PolicyError("mkdir: a pasta de trabalho já existe")
        if exists_in(path, roots) and "p" not in flags:
            raise PolicyError("mkdir: já existe")
        if exists_in(path, roots) and not is_dir_in(path, roots):
            raise PolicyError("mkdir: já existe um arquivo com esse nome")
        if len(path.relative_to(roots.workspace).parts) > 6:
            raise PolicyError("mkdir: caminho fundo demais")
        paths.append(path)
    return Checked(["mkdir", *(["-p"] if "p" in flags else []), *map(str, paths)], SAFE, "criar pasta", ["dentro da pasta de trabalho", "não sobrescreve nada"], writes=tuple(paths))


def _touch(name, args, roots):
    _, rest = _flags(args, set(), "touch")
    if not 1 <= len(rest) <= 5:
        raise PolicyError("touch: informe de 1 a 5 arquivos")
    paths = [resolve(w, roots, write=True, must_exist=False, what="touch") for w in rest]
    for p in paths:
        if p.suffix.lower() not in _TEXT_EXT:
            raise PolicyError("touch: só crio arquivos de texto (.txt, .md, .csv, .json ...)")
        if not is_dir_in(p.parent, roots):
            raise PolicyError("touch: a pasta não existe (crie com mkdir antes)")
    return Checked(["touch", *map(str, paths)], SAFE, "criar arquivo vazio", ["dentro da pasta de trabalho", "arquivo novo"], writes=tuple(paths))


def _cp_mv(name, args, roots):
    flags, rest = _flags(args, {"r"} if name == "cp" else set(), name)
    if len(rest) != 2:
        raise PolicyError(f"{name}: use {name} origem destino")
    src = resolve(rest[0], roots, write=(name == "mv"), must_exist=True, what=f"{name} (origem)")
    into = resolve(rest[1], roots, write=True, what=f"{name} (destino)")
    if is_dir_in(into, roots) and into != roots.workspace and (is_file_in(src, roots) or name == "mv"):
        into = into / src.name  # "mv lista.txt arquivos" when arquivos is a folder: it goes inside, with its own name
    dst = resolve(str(into), roots, write=True, must_exist=False, what=f"{name} (destino)")
    if is_dir_in(src, roots) and not (name == "mv" or "r" in flags):
        raise PolicyError("cp: para pastas use -r")
    if is_file_in(src, roots) and src.suffix.lower() != dst.suffix.lower():
        raise PolicyError(f"{name}: não mudo o formato do arquivo (a extensão tem que continuar {src.suffix or 'sem extensão'})")
    if src == roots.workspace or _inside(roots.workspace, src):
        raise PolicyError(f"{name}: não movo nem copio a pasta de trabalho inteira")
    if not is_dir_in(dst.parent, roots):
        raise PolicyError(f"{name}: a pasta de destino não existe")
    if is_dir_in(src, roots) and _inside(dst, src):
        raise PolicyError(f"{name}: não copio uma pasta para dentro dela mesma")
    if name == "mv" and src.name.startswith("backup_"):
        raise PolicyError("mv: backups só mudam por \"reverter\"")
    return Checked([name, *(["-r"] if "r" in flags else []), str(src), str(dst)], SAFE, "copiar" if name == "cp" else "mover", ["destino novo (sem sobrescrever)", "mesmo formato", "dentro das pastas permitidas"], reads=(src,), writes=(dst,))


_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".py", ".sql", ".xml", ".log", ".ini", ".toml", ".tex", ".rtf", ".ics", ".srt"}


# ---------------------------------------------------------------------------------------------------- run / download
def script_warnings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["não consegui ler o script"]
    return sorted({p.pattern for p in _DANGEROUS_SCRIPT if p.search(text)})


def _run_script(name: str, args: list[str], roots: Roots) -> Checked:
    if not args or args[0].startswith("-"):
        raise PolicyError(f"{name}: informe o arquivo do script primeiro (sem opções como -c)")
    script = resolve(args[0], roots, must_exist=True, what="script")
    if not script.is_file() or script.suffix.lower() not in SCRIPT_RUNNERS[name]:
        raise PolicyError(f"{name}: só rodo arquivos {', '.join(sorted(SCRIPT_RUNNERS[name]))}")
    if script.stat().st_size > MAX_SCRIPT_BYTES:
        raise PolicyError("script grande demais")
    extra = args[1:]
    if len(extra) > 6 or any(not _SAFE_ARG.match(a) for a in extra):
        raise PolicyError("argumentos do script com caracteres não permitidos")
    bad = script_warnings(script)
    if bad:
        raise PolicyError("o script tem trechos que não rodo (apagar, rede, sistema, executar outros programas...): " + ", ".join(bad[:4]))
    return Checked([name, str(script), *extra], RUN, f"rodar o script {script.name}", ["pede aprovação sempre", "o script foi lido: sem apagar, rede, sistema nem outros programas"], preview=script, reads=(script,), timeout=60)


_DL_FLAGS = {"curl": set("LsSf"), "wget": set()}


def _download(name: str, args: list[str], roots: Roots) -> Checked:
    out_flag = "-o" if name == "curl" else "-O"
    if out_flag not in args:
        raise PolicyError(f"{name}: informe o arquivo de destino com {out_flag}")
    i = args.index(out_flag)
    if i + 1 >= len(args):
        raise PolicyError(f"{name}: falta o nome do arquivo depois de {out_flag}")
    out_word, rest = args[i + 1], args[:i] + args[i + 2 :]
    flags, urls = _flags(rest, _DL_FLAGS[name], name)
    if len(urls) != 1:
        raise PolicyError(f"{name}: informe exatamente um endereço")
    url = urlparse(urls[0])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise PolicyError(f"{name}: só baixo de endereços https")
    out = resolve(out_word, roots, write=True, must_exist=False, what=f"{name} (destino)")
    if out.suffix.lower() in EXECUTABLE_EXT or out.suffix.lower() in {".sh", ".py", ".js", ".bash", ".zsh"}:
        raise PolicyError(f"{name}: não baixo programas nem scripts")
    if not is_dir_in(out.parent, roots):
        raise PolicyError(f"{name}: a pasta de destino não existe")
    if name == "curl":
        argv = ["curl", "--proto", "=https", "--max-filesize", "52428800", "--max-time", "120", *[f"-{f}" for f in sorted(flags)], "-o", str(out), urls[0]]
    else:
        argv = ["wget", "--https-only", "--quiet", "--timeout=60", "-O", str(out), urls[0]]
    return Checked(argv, DOWNLOAD, f"baixar de {url.hostname} para {out.name}", ["pede aprovação sempre", "só https", "não baixo programas nem scripts", "no máximo 50 MB"], writes=(out,), timeout=130)


_HANDLERS = {
    "pwd": _simple, "date": _simple, "df": _simple, "echo": _simple, "ls": _ls, "cat": _cat_like, "head": _cat_like, "tail": _cat_like, "wc": _cat_like,
    "stat": _cat_like, "file": _cat_like, "du": _du, "grep": _grep, "mkdir": _mkdir, "touch": _touch, "cp": _cp_mv, "mv": _cp_mv, "curl": _download, "wget": _download,
}

ENV_KEEP = ("PATH", "LANG", "LC_ALL", "TMPDIR")


def clean_env() -> dict[str, str]:
    """Only these variables reach a command: no tokens, keys or credentials that may sit in the engine's environment."""
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
    return env
