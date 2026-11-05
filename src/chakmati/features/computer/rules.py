"""Requests whose words settle what is meant, read by rules instead of by the model.

The model gets these wrong now and then (it turned "apague tudo" into `ls`, "baixe" into opening the page, a file name into another one) and it is
slow; a pattern that matches the whole request is exact, instant, and cheap. Each rule matches the WHOLE sentence or nothing: anything with an
"and then", an unusual name or an unknown word is left to the model. What the rules return is the same small intent the model would have returned,
so everything after (the checks, the plan, the approval) is the same."""

import re
from pathlib import Path
from urllib.parse import urlparse

_NAME = r"[\w\-.]+"
_PATH = r"[\w\-./]+"
_END = r"\W*$"
_START = r"^\W*(?:por favor,?\s*|pode\s+)?"


def _cmd(*commands: str) -> dict:
    return {"action": "steps", "steps": [{"type": "command", "command": c} for c in commands]}


_MKDIR = re.compile(_START + r"(?:crie|criar|fa[çc]a|fazer|monte|montar)\s+(?:a\s+|as\s+|uma\s+|duas\s+|tr[êe]s\s+|quatro\s+|cinco\s+)?(?:nova\s+|novas\s+)?pastas?\s+(?:chamadas?\s+|de nome\s+|com o nome\s+)?(" + _NAME + r"(?:\s*(?:,|\be\b)\s*" + _NAME + r")*)" + _END, re.IGNORECASE)
_LS = re.compile(_START + r"(?:liste|listar|mostre|mostrar|veja|ver|exiba)\s+(?:todos\s+)?(?:os\s+)?(?:arquivos|itens|conte[úu]do)(?:\s+(?:da|de|na|em|do)\s+(?:pasta\s+)?(" + _PATH + r"))?" + _END, re.IGNORECASE)
_CAT = re.compile(_START + r"(?:mostre|mostrar|leia|ler|exiba|exibir|veja|ver)\s+(?:o\s+|a\s+)?(?:conte[úu]do\s+(?:d[oa]\s+)?)?(?:arquivo\s+)?(" + _PATH + r")" + _END, re.IGNORECASE)
_DOWNLOAD = re.compile(_START + r"(?:baixe|baixar|fa[çc]a o download d[eoa]|download d[eoa])\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(https://\S+?)(?:\s+(?:como|com o nome|para|em)\s+(" + _NAME + r"))?" + _END, re.IGNORECASE)
_RENAME = re.compile(_START + r"(?:renomeie|renomear|troque o nome d[oa]|mude o nome d[oa])\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(" + _PATH + r")\s+(?:para|por|como)\s+(" + _PATH + r")" + _END, re.IGNORECASE)
_COPY = re.compile(_START + r"(?:copie|copiar|duplique|duplicar)\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(" + _PATH + r")\s+(?:para|como|em)\s+(" + _PATH + r")" + _END, re.IGNORECASE)
_OPEN_APP = re.compile(_START + r"(?:abr[ae]|abrir|inicie|iniciar|lance|lan[çc]ar|execute)\s+(?:o\s+|a\s+)?(?:aplicativo\s+|app\s+|programa\s+)?(.+?)" + _END, re.IGNORECASE)
_OPEN_FILE = re.compile(_START + r"(?:abr[ae]|abrir)\s+(?:o\s+)?(?:arquivo\s+)?(" + _NAME + r"\.[A-Za-z0-9]{1,5})" + _END, re.IGNORECASE)
_NOT_A_FILE = {"arquivos", "itens", "conteudo", "conteúdo", "pasta", "tudo"}


def _split_names(text: str) -> list[str]:
    return [n.rstrip(".") for n in re.split(r"\s*(?:,|\be\b)\s*", text.strip()) if n.rstrip(".")]


def by_rule(text: str, service) -> dict | None:
    """The intent for a request that a rule settles, or None (the model will read it). `service` is the ComputerService, to look at the workspace and the apps."""
    t = text.strip()
    if m := _DOWNLOAD.search(t):
        url, name = m.group(1), m.group(2)
        name = name or Path(urlparse(url).path).name
        if name and re.fullmatch(_NAME, name) and "." in name:
            return _cmd(f"curl -L -o {name} {url}")
        return None
    if m := _MKDIR.search(t):
        names = _split_names(m.group(1))
        if 1 <= len(names) <= 5 and not any(n.lower() in {"e", "dentro"} for n in names):
            return _cmd(*[f"mkdir {n}" for n in names])
        return None
    if m := _LS.search(t):
        return _cmd("ls -l" + (f" {m.group(1)}" if m.group(1) else ""))
    if m := _RENAME.search(t):
        return _cmd(f"mv {m.group(1)} {_with_extension(m.group(1), m.group(2), service)}")
    if m := _COPY.search(t):
        return _cmd(f"cp {m.group(1)} {_with_extension(m.group(1), m.group(2), service)}")
    if m := _OPEN_FILE.search(t):
        return {"action": "open_path", "path": m.group(1)}
    if m := _CAT.search(t):
        word = m.group(1)
        if word.lower() not in _NOT_A_FILE and ("." in word or service.find_candidates(word)) and not re.search(r"\babr[ae]\b", t, re.IGNORECASE):
            return _cmd(f"cat {word}")
        return None
    if m := _OPEN_APP.search(t):
        name = m.group(1).strip()
        if name and not re.search(r"\b(?:site|p[áa]gina|https?|www|\.com|\.br)\b", name, re.IGNORECASE):
            from chakmati.features.computer.safety import find_app
            app, candidates = find_app(name, service._apps())
            if app or candidates:
                return {"action": "open_app", "app": name}
    return None


def _with_extension(source: str, target: str, service) -> str:
    """"renomeie a lista para compras": the extension stays (a file keeps its format), unless the target is a folder."""
    src_ext = Path(source).suffix
    if Path(target).suffix or not src_ext:
        return target
    folder = service.workspace / target
    return target if folder.is_dir() else target + src_ext


_JOINER = re.compile(r"\s*(?:,\s*(?:e\s+)?(?:depois|ent[ãa]o|em seguida)|\s+(?:e\s+)?(?:depois|ent[ãa]o|em seguida)|;)\s+", re.IGNORECASE)


def split_compound(text: str) -> list[str]:
    """"crie a pasta x e depois copie a para b" -> two requests, in order. Only the clear joiners split ("depois", "então", "em seguida", ";"):
    a plain "e" is part of lists ("crie as pastas a e b") and of names, so it never splits. One part, or more than four, means do not split."""
    parts = [p.strip(" .") for p in _JOINER.split(text.strip())]
    parts = [p for p in parts if p]
    return parts if 2 <= len(parts) <= 4 else [text.strip()]
