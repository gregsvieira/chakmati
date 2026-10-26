"""Natural-language front end for the computer. The model only turns the PERSON's request into a small JSON (what to do, which
commands, which files); every rule (allowed commands, folders, secrets, approvals) is code in policy.py / service.py.

Only the person's own words reach the model here. A command's output is shown to the person and never sent back, and a file's
text reaches the model only for an edit the person asked for (fenced as untrusted, and refused if it holds secrets)."""

import json
import re
import subprocess
from collections.abc import Awaitable, Callable

from ..guard import UNTRUSTED_RULE, fence, strip_markers
from ..llm import ChatClient
from .safety import ComputerError, plain as plain_name
from .service import ComputerService

SYSTEM = """You turn a request to do something on the user's computer into JSON. Reply with ONLY one JSON object, no prose.
"action" is one of:
  "steps"      do things with commands or new files. Put them in "steps", in order (one step if the job is simple).
  "open_app"   open a program: "app" is its name (for example "Safari")
  "open_url"   open a website: "url" (add https:// if missing)
  "open_path"  open a file or folder: "path"
  "edit"       change an EXISTING text file: "path" and "instruction" (what to change)
  "revert"     undo your earlier edit of a file: "path"
  "trash"      the user wants a file or folder removed: "path" (it only goes to the Trash, never deleted)
  "other"      anything else
Each step is {"type":"command","command":"..."} or {"type":"create_file","path":"name.txt","content":"full text"}.
Commands are ONE program with plain words: no pipes, no >, no &&, no ;, no $, no wildcards, no ~. Allowed programs:
  pwd, date, ls [-la] [path], cat/head/tail/wc/stat/file <file>, grep [-nir] text file, du -sh path, mkdir [-p] folder, touch file.txt,
  cp [-r] source destination, mv source destination (new destinations only), echo text,
  python3/node/bash <script> (runs a script the user named), curl -L -o <file> https://... (download, https only).
Paths are inside the workspace folder (relative paths are fine). Use create_file to write text into a new file; never use echo for that.
For a task with several parts, give all the steps in order. Never invent files or contents the user did not ask for. Never output anything else."""

EDIT_SYSTEM = ("You edit a text file following the user's instruction. Reply with ONLY the complete new text of the file, nothing else, "
               "no explanations and no code fences." + UNTRUSTED_RULE)

HELP = ("Não entendi o que fazer no computador. Exemplos: \"crie um arquivo lista.txt com leite, pão e ovos\", \"crie a pasta projetos\", "
        "\"abre o Spotify\", \"edite a lista.txt trocando leite por café\", \"mande o rascunho.txt para a lixeira\".")


# --- Word / Excel / PowerPoint (Pages / Numbers / Keynote open them) ---------------------------------------------------------
_DOC_KIND = (
    ("pptx", re.compile(r"\b(?:slides?|apresenta[çc][ãa]o|apresenta[çc][õo]es|keynote|powerpoint|ppt)\b", re.IGNORECASE)),
    ("xlsx", re.compile(r"\b(?:planilha|numbers|excel|xlsx|tabela)\b", re.IGNORECASE)),
    ("docx", re.compile(r"\b(?:pages|word|docx|documento\s+de\s+texto|documento)\b", re.IGNORECASE)),
)
_MAKE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|mont\w+|ger[ae]\w*|escrev\w+|prepar\w+)\b", re.IGNORECASE)
_WEB = re.compile(r"\b(?:internet|wikip[eé]dia|site|web|copiad\w+|pesquis\w+|pesquisad\w+|fonte)\b", re.IGNORECASE)

META_SYSTEM = """From the user's request, reply with ONLY one JSON object: {"name":"short file name without extension, no spaces","topic":"the subject to look up or write about, in a few words"}."""

SPEC_SYSTEMS = {
    "docx": """Write a text document. Reply with ONLY one JSON object: {"title":"...","paragraphs":["...","..."]}.
Use 2 to 6 paragraphs. If source text is given, copy the relevant sentences from it faithfully (do not invent facts); otherwise write it yourself. Same language as the user.""",
    "xlsx": """Make a spreadsheet. Reply with ONLY one JSON object: {"sheets":[{"name":"...","rows":[[...],[...]]}]}.
The first row is the header. A cell is a number, a text, or a formula starting with "=" over cells of the same sheet, like "=SUM(B2:B4)", "=AVERAGE(B2:B4)", "=B2*C2".
Always include the formulas the user asked for (totals, averages, products) in the right cells, and realistic sample numbers if none were given. Same language as the user.""",
    "pptx": """Make a slide deck. Reply with ONLY one JSON object: {"title":"deck title","slides":[{"title":"...","bullets":["...","..."]}]}.
Use 4 to 7 slides with 2 to 4 short bullets each (the first slide is the introduction). If source text is given, base the slides on it; do not invent facts. Same language as the user.""",
}

ACTIONS = {"steps", "open_app", "open_url", "open_path", "edit", "revert", "trash"}
STEP_TYPES = ("command", "create_file")


def _shape(data: dict) -> dict:
    """Keep only the fields we know, as the strict reading of one JSON object."""
    action = data.get("action")
    if action is None and isinstance(data.get("steps"), list):  # small models often leave "action" out when there are steps
        action = "steps"
    if action not in ACTIONS:
        return {"action": "other"}
    out: dict = {"action": action}
    for key in ("app", "url", "path", "instruction", "goal"):
        if isinstance(data.get(key), str):
            out[key] = data[key].strip()
    steps = data.get("steps")
    if isinstance(steps, list):
        out["steps"] = [s for s in steps if isinstance(s, dict) and s.get("type") in STEP_TYPES][:12]
    return out


def _usable(intent: dict) -> bool:
    return intent["action"] != "other" and (intent["action"] != "steps" or bool(intent.get("steps")))


def _fix_step(step: object) -> object:
    """A step missing its "type" (or with an invented one) gets it from the fields it carries."""
    if not isinstance(step, dict) or step.get("type") in STEP_TYPES:
        return step
    if isinstance(step.get("command"), str):
        return {**step, "type": "command"}
    if isinstance(step.get("path"), str) and isinstance(step.get("content"), str):
        return {**step, "type": "create_file"}
    return step


def _repair(data: dict) -> dict | None:
    """Fix the shape slips small models make; the content is never invented, and policy.py still judges every command.

    Only used when the strict reading found nothing to do, and never on a reply that says "other" itself."""
    kind = data.get("type")
    if data.get("action") not in ACTIONS:
        if kind in ACTIONS:  # {"type":"open_url","url":...}: "type" where "action" belongs
            return {**data, "action": kind}
        bare = _fix_step(data)
        if isinstance(bare, dict) and bare.get("type") in STEP_TYPES:  # one step with no "steps" around it
            return {"action": "steps", "steps": [bare]}
    steps = data.get("steps")
    if isinstance(steps, list):
        fixed = [_fix_step(s) for s in steps]
        if not any(isinstance(s, dict) and s.get("type") in STEP_TYPES for s in fixed):
            only = fixed[0] if len(fixed) == 1 else None  # one action dressed as a step; with several we do not guess
            if isinstance(only, dict) and only.get("type") in ACTIONS:
                return {**only, "action": only["type"]}
            return None
        return {**data, "action": "steps", "steps": fixed}
    return None


def parse_intent(reply: str) -> dict:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return {"action": "other"}
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return {"action": "other"}
    if not isinstance(data, dict):
        return {"action": "other"}
    intent = _shape(data)
    if _usable(intent) or "other" in (data.get("action"), data.get("type")):
        return intent if _usable(intent) else {"action": "other"}
    fixed = _repair(data)
    if fixed is not None:
        repaired = _shape(fixed)
        if _usable(repaired):
            return repaired
    return intent


Gather = Callable[[str], Awaitable[tuple[str, list[str]]]]


def document_kind(text: str) -> str | None:
    """"pptx" | "xlsx" | "docx" when the request is to make such a file, decided by code and not by the model."""
    if not _MAKE.search(text):
        return None
    return next((kind for kind, pattern in _DOC_KIND if pattern.search(text)), None)


def _json_object(reply: str) -> dict | None:
    first, last = reply.find("{"), reply.rfind("}")
    try:
        data = json.loads(reply[first : last + 1]) if 0 <= first < last else None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class ComputerAssistant:
    def __init__(self, llm: ChatClient, service: ComputerService, gather: Gather | None = None):
        self._llm = llm
        self._service = service
        self._gather = gather  # (topic) -> (text found on the internet, source urls); None = no web access

    async def _document(self, kind: str, request: str) -> str:
        meta = _json_object(await self._llm.chat([{"role": "system", "content": META_SYSTEM}, {"role": "user", "content": request}])) or {}
        topic = str(meta.get("topic") or request)[:120]
        name = re.sub(r"[^a-z0-9_-]+", "-", plain_name(str(meta.get("name") or topic))).strip("-")[:40] or "documento"
        source, urls = "", []
        acronyms = sorted(set(re.findall(r"\b[A-Z]{2,6}\b", request)))
        topic = " ".join([topic, *(a for a in acronyms if a not in topic)])[:140]  # the model may drop (or invent a meaning for) "MCP": it stays in the query
        if self._gather is not None and (_WEB.search(request) or kind == "pptx"):
            try:
                source, urls = await self._gather(topic)
            except Exception:
                source, urls = "", []
            if not source or not all(a in source for a in acronyms):  # pages about something else that shares the letters: never build on them
                return (f"Não encontrei fontes que falem de {', '.join(acronyms) or topic}. Pode dizer o nome completo "
                        "(por exemplo, “Model Context Protocol da Anthropic”)?")
        user = request
        if source:
            user += f"\n\nSource text (from {', '.join(urls[:3])}):\n{fence(source, 'web')}"
        system = SPEC_SYSTEMS[kind] + " Write in the language of the user's request, even if the source text is in another language (translate it)." + (UNTRUSTED_RULE if source else "")
        spec = None
        for _ in range(2):  # a small model sometimes slips on the JSON: ask once more
            spec = _json_object(await self._llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}]))
            if spec:
                break
        if not spec:
            return "Não consegui montar o conteúdo do documento. Pode pedir de novo com mais detalhes?"
        if kind == "docx" and urls:
            spec["sources"] = urls[:3]
        action = self._service.propose_create_document(f"{name}.{kind}", kind, spec)
        first, *rest = action.summary.splitlines()
        return f"{first}\nConfirma? Diga sim ou não, ou aprove no painel.\n[[action:{action.id}]]"

    async def handle(self, text: str) -> str:
        kind = document_kind(text)
        if kind is not None:
            try:
                return await self._document(kind, text)
            except ComputerError as exc:
                return f"Não consegui: {exc}."
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
        intent = parse_intent(reply)
        if intent["action"] == "other" or (intent["action"] == "steps" and not intent.get("steps")):  # a small model sometimes slips: ask once more
            reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text + "\n\nReply with the JSON object only."}])
            intent = parse_intent(reply)
        try:
            return await self._act(intent, text)
        except ComputerError as exc:
            return f"Não consegui: {exc}."
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
            return f"Não consegui: {exc}."

    async def _act(self, intent: dict, request: str) -> str:
        s = self._service
        match intent["action"]:
            case "steps":
                steps = intent.get("steps") or []
                if not steps:
                    return HELP
                if len(steps) >= 2:
                    action = s.propose_plan(intent.get("goal") or request, steps)
                    return f"{action.summary}\n[[action:{action.id}]]"
                step = steps[0]
                if step["type"] == "create_file":
                    action, ran = s.propose_create_file(step.get("path", ""), step.get("content", ""))
                else:
                    action, ran = s.propose_command(step.get("command", ""))
                if action is None:
                    return ran or "Feito."
                first = action.summary.splitlines()[0]
                return f"{first}\nConfirma? Diga sim ou não, ou aprove no painel.\n[[action:{action.id}]]"
            case "open_app":
                action = s.propose_open_app(intent.get("app", ""))
                return f"{action.summary}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "open_path":
                action = s.propose_open_path(intent.get("path", ""))
                return f"{action.summary}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "open_url":
                return s.open_url(intent.get("url", ""))
            case "trash":
                action = s.propose_trash(intent.get("path", ""))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "revert":
                action = s.propose_revert(intent.get("path", ""))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "edit":
                path, old = s.read_for_edit(intent.get("path", ""))
                instruction = intent.get("instruction") or request
                new = await self._llm.chat([
                    {"role": "system", "content": EDIT_SYSTEM},
                    {"role": "user", "content": f"Instruction: {instruction}\n\nCurrent file {path.name}:\n{fence(old, 'file')}"},
                ])
                action = s.propose_edit(str(path), strip_markers(_unfence(new)))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case _:
                return HELP


def _unfence(text: str) -> str:
    t = text.strip("\n")
    if t.startswith("```") and t.rstrip().endswith("```"):
        lines = t.splitlines()
        return "\n".join(lines[1:-1]) + "\n"
    return t if t.endswith("\n") else t + "\n"
