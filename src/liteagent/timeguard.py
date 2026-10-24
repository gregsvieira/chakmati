"""Questions that depend on today's date or on recent events.

A language model does not know what day it is and does not know recent events, and it will answer anyway. This guard
decides, from the user's own text (never from third-party content), what to do:
  * a date question the model can solve once it is told the date ("que dia é amanhã?")  -> send today's date with the prompt;
  * a question about events or recent facts ("os últimos filmes de 2026", "quem ganhou ontem") -> search the web, or, when
    search is off, tell the model the date and that it has no internet, so it says it does not know instead of inventing.
"""

import re
import unicodedata
from datetime import date, datetime, timedelta

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
    recent_year = any(y >= now.year - 1 for y in years)  # this year, last year or the future: the model cannot know what happened
    if recent_year and not _bissexto(t):
        return True
    if _RECENT.search(t) and (recent_year or _TIMELY.search(t)):
        return True
    return False


def _bissexto(t: str) -> bool:
    """Questions about the calendar itself ("2026 é bissexto?") are solved without the web."""
    return bool(re.search(r"\bbissext", t))


def _event_without_time(t: str) -> bool:
    """Words that are only about the present moment even without a date ("qual a cotação do dólar")."""
    return bool(re.search(r"\b(cotacao|dolar|bitcoin|previsao do tempo|vai chover|noticias?|manchetes?|placar|classificacao|lancamentos?|estreias?)\b", t))


# ----------------------------------------------------------------------------- calendar arithmetic, done in code
_MONTH_NUMBER = {_plain(m): i for i, m in enumerate(_MONTHS, 1)}
_NAMED = {"natal": (12, 25, "o Natal"), "ano novo": (1, 1, "o Ano Novo"), "reveillon": (12, 31, "o Réveillon")}
_UNITS = {"dia": "days", "dias": "days", "semana": "weeks", "semanas": "weeks", "mes": "months", "meses": "months", "ano": "years", "anos": "years"}


def _describe(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]}, {d.day} de {_MONTHS[d.month - 1]} de {d.year} ({d:%d/%m/%Y})"


def _shift(d: date, amount: int, unit: str) -> date:
    if unit == "days":
        return d + timedelta(days=amount)
    if unit == "weeks":
        return d + timedelta(weeks=amount)
    months = amount * (12 if unit == "years" else 1) if unit in ("months", "years") else 0
    index = d.year * 12 + d.month - 1 + months
    year, month = divmod(index, 12)
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month])
    return date(year, month + 1, day)


def _next(month: int, day: int, today: date) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _count(target: date, today: date, label: str) -> str:
    days = (target - today).days
    when = "é hoje" if days == 0 else f"falta 1 dia" if days == 1 else f"faltam {days} dias"
    return f"{label}: {_describe(target)}; {when}."


def calendar_facts(text: str, now: datetime) -> list[str]:
    """Date arithmetic the model would get wrong ("quantos dias faltam para o Natal"), computed here and handed to it."""
    t = _plain(text)
    today = now.date()
    facts: list[str] = []
    rest = t
    for phrase, delta, label in (("depois de amanha", 2, "Depois de amanhã"), ("anteontem", -2, "Anteontem"), ("amanha", 1, "Amanhã"), ("ontem", -1, "Ontem")):
        if re.search(rf"\b{phrase}\b", rest):
            facts.append(f"{label}: {_describe(today + timedelta(days=delta))}.")
            rest = re.sub(rf"\b{phrase}\b", " ", rest)
    for name, (month, day, label) in _NAMED.items():
        if re.search(rf"\b{name}\b", t) and (target := _next(month, day, today)):
            facts.append(_count(target, today, label.capitalize()))
    for amount, unit in re.findall(r"\bdaqui a (\d{1,3}) (dias?|semanas?|mes|meses|anos?)\b", t):
        facts.append(f"Daqui a {amount} {unit}: {_describe(_shift(today, int(amount), _UNITS[unit]))}.")
    for amount, unit in re.findall(r"\bha (\d{1,3}) (dias?|semanas?|mes|meses|anos?)\b", t):
        facts.append(f"Há {amount} {unit}: {_describe(_shift(today, -int(amount), _UNITS[unit]))}.")
    for d_, m_, y_ in re.findall(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):
        month, day = int(m_), int(d_)
        if y_:
            year = int(y_) + (2000 if len(y_) == 2 else 0)
            try:
                facts.append(_count(date(year, month, day), today, f"{day:02d}/{month:02d}/{year}"))
            except ValueError:
                pass
        elif target := _next(month, day, today):
            facts.append(_count(target, today, f"{day:02d}/{month:02d}"))
    for d_, name in re.findall(r"\bdia (\d{1,2}) de ([a-z]+)\b", t):
        if name in _MONTH_NUMBER and (target := _next(_MONTH_NUMBER[name], int(d_), today)):
            facts.append(_count(target, today, f"{int(d_)} de {_MONTHS[_MONTH_NUMBER[name] - 1]}"))
    return facts


# ----------------------------------------------------------------------------- "the latest": dates in pages, ordering, queries
_MONTH_ABBREVIATION = {name[:3]: number for name, number in _MONTH_NUMBER.items()}
_MONTH_WORDS = "|".join(sorted(set(_MONTH_NUMBER) | set(_MONTH_ABBREVIATION), key=len, reverse=True))
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO_DATE = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
_WRITTEN_DATE = re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+)?({_MONTH_WORDS})\.?(?:\s*(?:de\s+)?(20\d\d))?\b")
_MONTH_YEAR = re.compile(rf"\b({_MONTH_WORDS})\.?\s*(?:de\s+)?(20\d\d)\b")


def _month_number(word: str) -> int | None:
    return _MONTH_NUMBER.get(word) or _MONTH_ABBREVIATION.get(word)


def extract_dates(text: str, now: datetime) -> list[date]:
    """The dates a page writes, in the order they appear: 22/10/2026, 2026-10-22, "22 de outubro (de 2026)", "22 out 2026"
    and "outubro de 2026" (taken as the 1st). A date without a year is read as this year."""
    t = _plain(text)
    found: list[tuple[int, date]] = []

    def add(position: int, year: int, month: int, day: int) -> None:
        try:
            found.append((position, date(year, month, day)))
        except ValueError:
            pass

    spans: list[tuple[int, int]] = []
    for m in _NUMERIC_DATE.finditer(t):
        add(m.start(), int(m.group(3)), int(m.group(2)), int(m.group(1))); spans.append(m.span())
    for m in _ISO_DATE.finditer(t):
        add(m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3))); spans.append(m.span())
    for m in _WRITTEN_DATE.finditer(t):
        if any(s <= m.start() < e for s, e in spans):
            continue
        month = _month_number(m.group(2))
        if month:
            add(m.start(), int(m.group(3)) if m.group(3) else now.year, month, int(m.group(1))); spans.append(m.span())
    for m in _MONTH_YEAR.finditer(t):
        if any(s <= m.start() < e for s, e in spans):
            continue
        month = _month_number(m.group(1))
        if month:
            add(m.start(), int(m.group(2)), month, 1)
    return [d for _, d in sorted(found, key=lambda pair: pair[0])]


def passage_date(text: str, now: datetime) -> date | None:
    """The most recent date in the passage that is not in the future (a release date, not an announcement)."""
    past = [d for d in extract_dates(text, now) if d <= now.date()]
    return max(past) if past else None


def order_by_date(passages: list[str], now: datetime) -> list[tuple[str, date | None]]:
    """Most recent dated passage first; the undated ones keep their order after the dated ones."""
    dated = [(p, passage_date(p, now)) for p in passages]
    with_date = sorted((x for x in dated if x[1] is not None), key=lambda x: x[1], reverse=True)
    without = [x for x in dated if x[1] is None]
    return with_date + without


_RECENCY = re.compile(
    r"\b(ultim[oa]s?|mais (recente|novo|nova|novos|novas)|recentes?|acabou de (sair|estrear|ser lancad[oa])|acabaram de (sair|estrear)|"
    r"novidades?|estreias?|estreou|lancamentos?|em cartaz|saiu agora)\b"
)


def is_recency_question(text: str) -> bool:
    return bool(_RECENCY.search(_plain(text)))


_LEADING = re.compile(r"^(me (diga|fale|conte|mostre)|diga|qual|quais|que|quem|o que|como)\b( (e|eh|foi|sao|foram|ha|tem|existe|existem))?( (o|a|os|as|um|uma|uns|umas))?\s*")


def recency_fallback_query(text: str, now: datetime) -> str:
    """A search query that names the month and year: "último filme lançado no cinema outubro de 2026"."""
    core = re.sub(r"[?!.]+", " ", text.strip())
    core = re.sub(r"\s+", " ", _LEADING.sub("", core.lower())).strip() or text.strip()
    return f"{core} {_MONTHS[now.month - 1]} de {now.year}"
