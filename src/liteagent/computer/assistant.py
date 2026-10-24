"""Natural-language front end for the computer. The model only turns the PERSON's request into {action, name, path, content, url};
every check (where files may go, which programs exist, which addresses are allowed) is code in `safety.py`."""

import json
import subprocess

from ..llm import ChatClient
from .safety import ComputerError
from .service import ComputerService

SYSTEM = """You turn a request to do something on the user's computer into JSON. Reply with ONLY one JSON object, no prose. Keys:
  "action": "create_file" (make a text file), "open_app" (open a program), "open_url" (open a website), "open_path" (open a file or folder), or "other"
  "app": the program name for open_app (for example "Safari", "Spotify"), otherwise null
  "url": the address for open_url (add https:// if missing), otherwise null
  "path": for create_file the file name WITH extension (for example "lista-de-compras.txt"; use .txt when the user gave none); for open_path the path; otherwise null
  "content": for create_file, the full text of the file. If the user dictated the text, use it exactly; if they asked you to write something, write it. Otherwise null
Never invent anything the user did not ask for. Never output commands."""

HELP = ("Não entendi o que fazer no computador. Exemplos: \"crie um arquivo lista.txt com leite, pão e ovos\", \"abre o Spotify\", "
        "\"abre o site do G1\", \"abre a pasta Downloads\".")
_ACTIONS = {"create_file", "open_app", "open_url", "open_path"}


def parse_intent(reply: str) -> dict:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return {"action": "other"}
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return {"action": "other"}
    if not isinstance(data, dict) or data.get("action") not in _ACTIONS:
        return {"action": "other"}
    return {k: (v.strip() if isinstance(v, str) else None) for k, v in data.items() if k in ("action", "app", "url", "path", "content")} | {"action": data["action"]}


class ComputerAssistant:
    def __init__(self, llm: ChatClient, service: ComputerService):
        self._llm = llm
        self._service = service

    async def handle(self, text: str) -> str:
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
        intent = parse_intent(reply)
        try:
            match intent["action"]:
                case "create_file":
                    if not intent.get("path"):
                        return "Qual o nome do arquivo?"
                    if intent.get("content") is None:
                        return "O que devo escrever no arquivo?"
                    action = self._service.propose_create_file(intent["path"], intent["content"])
                    return f"Vou criar o arquivo na pasta {self._service.workspace}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
                case "open_app":
                    return self._service.open_app(intent.get("app") or "")
                case "open_url":
                    return self._service.open_url(intent.get("url") or "")
                case "open_path":
                    return self._service.open_path(intent.get("path") or "")
                case _:
                    return HELP
        except ComputerError as exc:
            return f"Não consegui: {exc}."
        except (OSError, subprocess.SubprocessError) as exc:  # the opener failed
            return f"Não consegui abrir: {exc}."
