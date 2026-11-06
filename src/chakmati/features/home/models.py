"""Smart-home vocabulary: what a device is and what can be done to it. The mapping from words to a Home Assistant service call
is done HERE, in code, from a fixed table; the model only picks an action name and a device name."""

import re
import unicodedata
from dataclasses import dataclass

ALLOWED_DOMAINS = ("light", "switch", "fan", "cover", "lock", "climate", "scene", "input_boolean", "media_player")  # media_player: speakers and TVs, Alexa among them (Alexa Media Player in Home Assistant)
SENSITIVE_COVERS = ("garage", "door", "gate")
MEDIA_ACTIONS = ("play", "pause", "stop", "next", "previous", "volume_up", "volume_down", "volume")
ACTIONS = ("on", "off", "toggle", "lock", "unlock", "open", "close", "set_temperature", "brightness", "scene", "status", "list", *MEDIA_ACTIONS)
_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


class HomeError(Exception):
    pass


@dataclass(frozen=True)
class Entity:
    id: str
    name: str
    domain: str
    state: str
    device_class: str = ""
    unit: str = ""
    detail: str = ""  # what a media player is playing ("Artista - Título")

    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Command:
    entity: Entity
    domain: str
    service: str
    data: dict
    sensitive: bool
    text: str  # what will happen, in plain Portuguese: this is what the person approves


def plain(text: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c) and (c.isalnum() or c.isspace())).split())


def valid_entity_id(entity_id: str) -> bool:
    return bool(_ID.match(entity_id)) and entity_id.split(".")[0] in ALLOWED_DOMAINS


def plan(action: str, entity: Entity, value=None) -> Command:
    """The service call for (action, device), or HomeError when that makes no sense for that kind of device."""
    if not valid_entity_id(entity.id):
        raise HomeError("dispositivo não permitido")
    domain, name = entity.domain, entity.name

    def cmd(service: str, data: dict | None, text: str, sensitive: bool = False) -> Command:
        return Command(entity, domain, service, {"entity_id": entity.id, **(data or {})}, sensitive, text)

    covers_door = domain == "cover" and entity.device_class in SENSITIVE_COVERS
    if action in ("on", "off", "toggle") and domain in ("light", "switch", "fan", "input_boolean", "climate", "scene"):
        if domain == "scene":
            if action != "on":
                raise HomeError("uma cena só pode ser ativada")
            return cmd("turn_on", None, f"Ativar a cena {name}")
        service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
        return cmd(service, None, {"on": f"Ligar {name}", "off": f"Desligar {name}", "toggle": f"Alternar {name}"}[action])
    if action == "scene" and domain == "scene":
        return cmd("turn_on", None, f"Ativar a cena {name}")
    if action in ("open", "on") and domain == "cover":
        return cmd("open_cover", None, f"Abrir {name}", sensitive=covers_door)
    if action in ("close", "off") and domain == "cover":
        return cmd("close_cover", None, f"Fechar {name}")
    if action == "lock" and domain == "lock":
        return cmd("lock", None, f"Trancar {name}")
    if action in ("unlock", "open") and domain == "lock":
        return cmd("unlock", None, f"Destrancar {name}", sensitive=True)
    if action == "set_temperature" and domain == "climate":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 10 <= value <= 32:
            raise HomeError("a temperatura deve ficar entre 10 e 32 graus")
        return cmd("set_temperature", {"temperature": value}, f"Colocar {name} em {value:g} °C")
    if action == "brightness" and domain == "light":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 100:
            raise HomeError("o brilho deve ficar entre 1 e 100%")
        return cmd("turn_on", {"brightness_pct": int(value)}, f"Colocar {name} com {int(value)}% de brilho")
    if domain == "media_player" and action in MEDIA_ACTIONS:
        simple = {
            "play": ("media_play", f"Tocar em {name}"), "pause": ("media_pause", f"Pausar {name}"), "stop": ("media_stop", f"Parar {name}"),
            "next": ("media_next_track", f"Próxima música em {name}"), "previous": ("media_previous_track", f"Música anterior em {name}"),
            "volume_up": ("volume_up", f"Aumentar o volume de {name}"), "volume_down": ("volume_down", f"Diminuir o volume de {name}"),
        }
        if action in simple:
            service, text = simple[action]
            return cmd(service, None, text)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise HomeError("o volume deve ficar entre 0 e 100%")
        return cmd("volume_set", {"volume_level": round(value / 100, 2)}, f"Colocar o volume de {name} em {int(value)}%")
    raise HomeError(f"não dá para fazer isso com {name}")
