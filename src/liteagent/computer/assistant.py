"""Natural-language front end for the computer. The model only turns the PERSON's request into a small JSON (what to do, which
commands, which files); every rule (allowed commands, folders, secrets, approvals) is code in policy.py / service.py.

Only the person's own words reach the model here. A command's output is shown to the person and never sent back, and a file's
text reaches the model only for an edit the person asked for (fenced as untrusted, and refused if it holds secrets)."""

import json
import subprocess

from ..guard import UNTRUSTED_RULE, fence, strip_markers
from ..llm import ChatClient
from .safety import ComputerError
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


def parse_intent(reply: str) -> dict:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return {"action": "other"}
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return {"action": "other"}
    if not isinstance(data, dict) or data.get("action") not in {"steps", "open_app", "open_url", "open_path", "edit", "revert", "trash"}:
        return {"action": "other"}
    out: dict = {"action": data["action"]}
    for key in ("app", "url", "path", "instruction", "goal"):
        if isinstance(data.get(key), str):
            out[key] = data[key].strip()
    steps = data.get("steps")
    if isinstance(steps, list):
        out["steps"] = [s for s in steps if isinstance(s, dict) and s.get("type") in ("command", "create_file")][:12]
    return out


class ComputerAssistant:
    def __init__(self, llm: ChatClient, service: ComputerService):
        self._llm = llm
        self._service = service

    async def handle(self, text: str) -> str:
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
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
