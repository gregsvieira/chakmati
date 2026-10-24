"""Questions that depend on today's date or on recent events.

A language model does not know what day it is and does not know recent events, and it will answer anyway. This guard
decides, from the user's own text (never from third-party content), what to do:
  * a date question the model can solve once it is told the date ("que dia é amanhã?")  -> send today's date with the prompt;
  * a question about events or recent facts ("os últimos filmes de 2026", "quem ganhou ontem") -> search the web, or, when
    search is off, tell the model the date and that it has no internet, so it says it does not know instead of inventing.
"""

import re
import unicodedata
from datetime import datetime

_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"\s+", " ", "".join(c for c in decomposed if not unicodedata.combining(c))).strip()


def today_line(now: datetime) -> str:
    zone = now.strftime("%z")
    zone = f"UTC{zone[:3]}:{zone[3:]}" if zone else ""
    return (f"Hoje é {_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year} "
            f"({now:%d/%m/%Y}), {now:%H:%M}{', fuso ' + zone if zone else ''}.")


_TODAY = re.compile(
    r"\b(que dia (e|eh|sera|foi|cai|vai ser)|dia da semana|que data|data de hoje|data atual|em que (ano|mes|dia)|ano atual|mes atual|"
    r"quantos dias|quanto tempo (falta|faltam|passou)|faltam quantos|quantas semanas|quantos meses|"
    r"amanha|ontem|anteontem|depois de amanha|semana que vem|proxim[oa] (semana|mes|ano|sexta|segunda|terca|quarta|quinta|sabado|domingo)|"
    r"feriado|natal|ano novo|que horas|hora atual|horas sao|daqui a \d+|ha \d+ (dias|semanas|meses|anos)|dias ate|hoje e)\b"
)

_EVENT = re.compile(
    r"\b(quem (ganhou|venceu|foi eliminado|e o campeao|ta ganhando)|resultado d[aeo]s?|placar|classificacao|rodada|cotacao|dolar|euro hoje|"
    r"bitcoin|previsao do tempo|vai chover|noticias?|manchetes?|o que aconteceu|aconteceu|trending|em alta|"
    r"lancamentos?|lancad[oa]s?|estreias?|estreou|estreiam)\b"
)
_RECENT = re.compile(r"\b(ultim[oa]s?|recentes?|novidades?|atual|atualmente|agora|nesta semana|esta semana|neste mes|este mes|este ano|neste ano)\b")
_TIMELY = re.compile(r"\b(hoje|ontem|esta semana|nesta semana|este mes|neste mes|este ano|neste ano|agora|atualmente)\b")
_YEAR = re.compile(r"\b(20\d\d)\b")


def needs_today(text: str) -> bool:
    return bool(_TODAY.search(_plain(text)))


def needs_web(text: str, now: datetime) -> bool:
    t = _plain(text)
    if _TODAY.search(t) and not _EVENT.search(t):
        return False  # a calendar question, solved with the date alone
    if _EVENT.search(t) and (_TIMELY.search(t) or _RECENT.search(t) or re.search(r"\b(ontem|hoje|amanha)\b", t) or _event_without_time(t)):
        return True
    years = [int(y) for y in _YEAR.findall(t)]
    if _RECENT.search(t) and (any(y >= now.year - 1 for y in years) or _TIMELY.search(t)):
        return True
    return False


def _event_without_time(t: str) -> bool:
    """Words that are only about the present moment even without a date ("qual a cotação do dólar")."""
    return bool(re.search(r"\b(cotacao|dolar|bitcoin|previsao do tempo|vai chover|noticias?|manchetes?|placar|classificacao|lancamentos?|estreias?)\b", t))
