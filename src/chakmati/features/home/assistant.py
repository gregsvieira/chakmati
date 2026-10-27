"""Natural-language front end for the house. The model only turns the PERSON's request into {action, target, value}; the device
is found by matching its name in code, the service call comes from a fixed table, and anything that opens the house waits for
approval. Nothing read from messages or the web ever reaches this."""

import json

from chakmati.shared.llm import ChatClient
from chakmati.features.home.models import ACTIONS, HomeError
from chakmati.features.home.service import HomeService

SYSTEM = """You turn a smart-home request into JSON. Reply with ONLY one JSON object, no prose. Keys:
  "action": one of on, off, toggle, lock, unlock, open, close, set_temperature, brightness, scene, status, list, other
  "target": the name of the device or scene as the user said it (for example "luz da sala"), or null
  "value": a number for set_temperature (degrees) or brightness (percent), otherwise null
Use "scene" to activate a scene, "status" to ask whether something is on or off, "list" to list the devices. Never invent a device."""

HELP = "Não entendi o pedido para a casa. Exemplos: \"liga a luz da sala\", \"apaga o quarto\", \"coloca o ar em 23 graus\", \"a porta está trancada?\"."
STATE_WORDS = {"on": "ligado", "off": "desligado", "locked": "trancado", "unlocked": "destrancado", "open": "aberto", "closed": "fechado",
               "unavailable": "indisponível", "unknown": "sem informação"}


def parse_intent(reply: str) -> tuple[str, str | None, float | None]:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return "other", None, None
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return "other", None, None
    if not isinstance(data, dict) or data.get("action") not in ACTIONS:
        return "other", None, None
    target = data.get("target")
    value = data.get("value")
    return (data["action"], target.strip() or None if isinstance(target, str) else None,
            value if isinstance(value, (int, float)) and not isinstance(value, bool) else None)


class HomeAssistantBot:
    def __init__(self, llm: ChatClient, service: HomeService):
        self._llm = llm
        self._service = service

    async def handle(self, text: str) -> str:
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
        action, target, value = parse_intent(reply)
        if action == "other":
            return HELP
        try:
            entities = await self._service.entities()
            if action == "list":
                if not entities:
                    return "Não encontrei nenhum dispositivo na casa."
                return "Dispositivos da casa:\n" + "\n".join(f"- {e.name} ({STATE_WORDS.get(e.state, e.state)})" for e in entities[:40])
            if not target:
                return "Qual dispositivo? Diga o nome, por exemplo \"a luz da sala\"."
            entity, candidates = self._service.find(entities, target)
            if entity is None:
                if candidates:
                    return "Qual destes você quer dizer?\n" + "\n".join(f"- {c.name}" for c in candidates) + "\nPeça de novo com o nome completo."
                return f"Não encontrei nenhum dispositivo chamado \"{target}\"."
            if action == "status":
                unit = f" {entity.unit}" if entity.unit else ""
                return f"{entity.name}: {STATE_WORDS.get(entity.state, entity.state)}{unit}."
            said, proposal = await self._service.do(action, entity, value)
            if proposal is not None:
                return f"{said}. Isso abre a casa, então preciso da sua confirmação. Confirma? Diga sim ou não.\n[[action:{proposal.id}]]"
            return f"Feito: {said}."
        except HomeError as exc:
            return f"Não consegui: {exc}."
