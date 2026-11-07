"""Natural-language front end for the house. The model only turns the PERSON's request into {action, target, value}; the device
is found by matching its name in code, the service call comes from a fixed table, and anything that opens the house waits for
approval. Nothing read from messages or the web ever reaches this."""

import json

from chakmati.shared.llm import ChatClient
from chakmati.features.home import rules
from chakmati.features.home.models import ACTIONS, MEDIA_ACTIONS, HomeError
from chakmati.features.home.service import HomeService

SYSTEM = """You turn a smart-home request into JSON. Reply with ONLY one JSON object, no prose. Keys:
  "action": one of on, off, toggle, lock, unlock, open, close, set_temperature, brightness, scene, status, list, play, pause, stop, next, previous, volume_up, volume_down, volume, other
  "target": the name of the device or scene as the user said it (for example "luz da sala"), or null
  "value": a number for set_temperature (degrees), brightness (percent) or volume (percent), otherwise null
Use "scene" to activate a scene, "status" to ask whether something is on or off, "list" to list the devices. For music (Alexa, speakers): "next"/"previous" change the track, "play"/"pause"/"stop", "volume_up"/"volume_down", "volume" sets a percent; "target" is the device if the user said one, otherwise null. Never invent a device."""

HELP = "Não entendi o pedido para a casa. Exemplos: \"liga a luz da sala\", \"apaga o quarto\", \"coloca o ar em 23 graus\", \"a porta está trancada?\", \"próxima música\", \"volume em 30\"."
STATE_WORDS = {"on": "ligado", "off": "desligado", "locked": "trancado", "unlocked": "destrancado", "open": "aberto", "closed": "fechado",
               "unavailable": "indisponível", "unknown": "sem informação", "playing": "tocando", "paused": "pausado", "idle": "parado", "standby": "em espera", "buffering": "carregando"}


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
        ruled = rules.media_by_rule(text)  # a music command is read by code: instant, and the model cannot get it wrong
        music = ruled is not None
        if ruled is not None:
            action, target, value = ruled
        else:
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
            music = music or action in MEDIA_ACTIONS     # (a music question the model understood as a status is about the players too only when the rule said so)
            if not target and music:
                entity, candidates = self._service.default_player(entities)
                if entity is None:
                    if candidates:
                        return "Em qual aparelho?\n" + "\n".join(f"- {c.name} ({STATE_WORDS.get(c.state, c.state)})" for c in candidates) + "\nPeça de novo dizendo o aparelho, por exemplo \"próxima música da sala\"."
                    return "Não encontrei nenhum aparelho de música no Home Assistant. A Alexa aparece lá pela integração Alexa Media Player."
                target = entity.name
            elif not target:
                return "Qual dispositivo? Diga o nome, por exemplo \"a luz da sala\"."
            else:
                # a music command looks only among the music players: "pausa a música da sala" must not hesitate between the Echo and the light of the same room
                pool = [e for e in entities if e.domain == "media_player"] if music else entities
                entity, candidates = self._service.find(pool, target)
            if entity is None:
                if candidates:
                    return "Qual destes você quer dizer?\n" + "\n".join(f"- {c.name}" for c in candidates) + "\nPeça de novo com o nome completo."
                return f"Não encontrei nenhum dispositivo chamado \"{target}\"."
            if action == "status":
                unit = f" {entity.unit}" if entity.unit else ""
                playing = f" Tocando: {entity.detail}." if entity.detail else ""
                return f"{entity.name}: {STATE_WORDS.get(entity.state, entity.state)}{unit}.{playing}"
            said, proposal = await self._service.do(action, entity, value)
            if proposal is not None:
                return f"{said}. Isso abre a casa, então preciso da sua confirmação. Confirma? Diga sim ou não.\n[[action:{proposal.id}]]"
            return f"Feito: {said}."
        except HomeError as exc:
            return f"Não consegui: {exc}."
