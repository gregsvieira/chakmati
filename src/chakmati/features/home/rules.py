"""Music commands read by rules, not by the model: "próxima música", "pausa", "aumenta o volume", "volume em 30", "pula a música da sala".
Exact and instant, so changing the track never waits for a model (and a small one cannot get "pausa" wrong). The device is only taken
from the words after the last "na/no/da/do" ("... da sala"); with none, the service picks the player that is playing."""

import re
import unicodedata

_VOLUME_SET = re.compile(r"\bvolume\b.{0,20}?\b(\d{1,3})\b|\b(\d{1,3})\s*(?:%|por\s*cento)\s+(?:de\s+)?volume", re.IGNORECASE)
_MUSIC = r"(?:m[úu]sica|faixa|can[çc][ãa]o|som)"

_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("status", re.compile(r"\b(?:o\s+que|que\s+m[úu]sica|qual\s+m[úu]sica|que\s+faixa|qual\s+faixa)\b.{0,25}\b(?:est[áa]\s+tocando|toca|tocando)\b", re.IGNORECASE)),
    ("next", re.compile(r"\b(?:pr[óo]xima|pul[ae]r?|pula|avan[çc]a\w*|passa\w*|troc\w+|mud\w+)\b.{0,25}\b" + _MUSIC + r"\b|\b" + _MUSIC + r"\b.{0,15}\b(?:seguinte|pr[óo]xima)\b|^\W*pr[óo]xima\W*$", re.IGNORECASE)),
    ("previous", re.compile(r"\b(?:anterior|volt\w+|retrocede\w*)\b.{0,25}\b" + _MUSIC + r"\b|\b" + _MUSIC + r"\b.{0,15}\banterior\b", re.IGNORECASE)),
    ("pause", re.compile(r"\b(?:paus\w+|pause|par[ae]|interromp\w+|silencia\w*)\b.{0,20}\b" + _MUSIC + r"\b|^\W*paus\w+\W*$", re.IGNORECASE)),
    # "toca/toque ..." is NOT here: "toque uma música do Pelé" asks for a song, not for the player to resume
    ("play", re.compile(r"\b(?:continu\w+|retom\w+|d[êe]\s+play|play|despausa\w*)\b.{0,20}\b" + _MUSIC + r"\b|^\W*(?:play|continua\w*|retoma\w*)\W*$", re.IGNORECASE)),
    ("volume_up", re.compile(r"\b(?:aument\w+|sobe|suba|subir|eleva\w*)\b.{0,20}\bvolume\b|\bvolume\b.{0,15}\b(?:mais\s+alto|maior)\b|\bmais\s+alto\b", re.IGNORECASE)),
    ("volume_down", re.compile(r"\b(?:diminu\w+|abaix\w+|baix\w+|reduz\w*)\b.{0,20}\bvolume\b|\bvolume\b.{0,15}\b(?:mais\s+baixo|menor)\b|\bmais\s+baixo\b", re.IGNORECASE)),
)


_PREPOSITIONS = {"na", "no", "da", "do"}
_SKIP = {"a", "o", "as", "os", "de", "alexa", "echo", "dot", "caixa", "som"}                      # between the preposition and the device's name
_NOT_A_NAME = _SKIP | {"musica", "faixa", "cancao", "volume", "em", "para", "pra", "por", "cento", "essa", "esta", "dessa", "desta"}


def _device(text: str) -> str | None:
    """The device named after the LAST "na/no/da/do" ("pula a música da sala" -> "sala", "volume da sala em 40" -> "sala"); None when the words after it
    are only "a Alexa", "a música" and the like."""
    words = _plain(text).split()
    for i in range(len(words) - 1, -1, -1):
        if words[i] not in _PREPOSITIONS:
            continue
        rest = [w for w in words[i + 1:]]
        while rest and rest[0] in _SKIP:
            rest.pop(0)
        while rest and (rest[-1] in _NOT_A_NAME or rest[-1].isdigit()):
            rest.pop()
        if rest and not (set(rest) <= _NOT_A_NAME):
            return " ".join(rest)
    return None


def _plain(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", folded)).strip()


def media_by_rule(text: str) -> tuple[str, str | None, float | None] | None:
    """(action, device name or None, percent or None) for a music command, or None when the words are not one (the model reads it)."""
    t = text.strip()
    if m := _VOLUME_SET.search(t):
        action, value = "volume", float(m.group(1) or m.group(2))
    else:
        action = next((name for name, rx in _RULES if rx.search(t)), None)
        value = None
    if action is None:
        return None
    return action, _device(t), value


_PLAY_VERB = re.compile(r"^\W*(?:(?:ei|oi|ol[áa])?\W*alexa\W+)?(?:toca|toque|tocar|coloca|coloque|p[õo]e|ponha|bota|quero\s+ouvir|quero\s+escutar|ouvir|escutar)\s+(?P<rest>.+?)\W*$", re.IGNORECASE)
_GENERIC = {"musica", "a musica", "uma musica", "som", "o som", "algo", "alguma coisa", "alguma musica", "isso", "a", "uma"}


def _strip_where(words: list[str]) -> list[str]:
    """Drops a trailing "na Alexa" / "no echo" / "na caixa" (just a way to say where), however many of them end the request."""
    while len(words) > 1:
        for i in range(len(words) - 1, 0, -1):
            if _plain(words[i - 1]) in _PREPOSITIONS:
                tail = [_plain(w) for w in words[i:]]
                if tail and set(tail) <= _SKIP:
                    words = words[: i - 1]
                    break
                return words
        else:
            return words
    return words


def play_by_rule(text: str) -> tuple[str, str | None, str] | None:
    """(what to play, device name or None, the whole request) for "toca Raul Seixas na Alexa" / "coloca Legião Urbana na sala"; None when it is not a request for
    something to play ("toca" alone and "toca a música" mean resuming). The words after the last "na/no/da/do" are the device only when they are not just
    "a Alexa"; the service checks whether that is a device and, when it is not ("toca uma do Pelé"), the whole request is the thing to play."""
    m = _PLAY_VERB.match(text.strip())
    if not m:
        return None
    rest = m.group("rest").strip()
    full = " ".join(_strip_where(rest.split())).strip(" ,.;:!?")
    if not _plain(full) or _plain(full) in _GENERIC:
        return None
    device = _device(" ".join(_strip_where(rest.split())))
    query = full
    if device:
        words = full.split()
        for i in range(len(words) - 1, 0, -1):
            if _plain(words[i - 1]) in _PREPOSITIONS:
                query = " ".join(_strip_where(words[: i - 1])).strip(" ,.;:!?")   # "Legião Urbana no echo da sala": the "no echo" goes too
                break
    return query, device, full
