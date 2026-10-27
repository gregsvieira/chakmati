"""A small five-field cron matcher (minute hour day-of-month month day-of-week), enough for "every day at 9", "weekdays at 8:30".

Day of week: 0 or 7 is Sunday, 6 is Saturday. As in classic cron, when both day-of-month and day-of-week are restricted, either
may match.
"""

from datetime import datetime, timedelta

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
_DAY_NAMES = {0: "domingo", 1: "segunda-feira", 2: "terça-feira", 3: "quarta-feira", 4: "quinta-feira", 5: "sexta-feira", 6: "sábado", 7: "domingo"}


class CronError(ValueError):
    pass


def _field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"invalid step in {text!r}")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"invalid range in {text!r}")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise CronError(f"invalid value {part!r}")
        if start > end or start < low or end > high:
            raise CronError(f"value out of range in {text!r}")
        values.update(range(start, end + 1, step))
    return values


def _parse(expr: str) -> list[set[int]]:
    fields = (expr or "").split()
    if len(fields) != 5:
        raise CronError("a cron expression has five fields: minute hour day month weekday")
    parsed = [_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES, strict=True)]
    parsed[4] = {0 if d == 7 else d for d in parsed[4]}
    return parsed


def validate_cron(expr: str) -> None:
    _parse(expr)


def cron_matches(expr: str, when: datetime) -> bool:
    minute, hour, dom, month, dow = _parse(expr)
    fields = (expr or "").split()
    weekday = (when.weekday() + 1) % 7  # Python: Monday=0; cron: Sunday=0
    day_ok, dow_ok = when.day in dom, weekday in dow
    if fields[2] != "*" and fields[4] != "*":
        day_match = day_ok or dow_ok
    else:
        day_match = day_ok and dow_ok
    return when.minute in minute and when.hour in hour and when.month in month and day_match


def fires_per_day(expr: str) -> int:
    """How many minutes of an ordinary day the expression fires in (used to refuse schedules that would spam)."""
    start = datetime(2026, 1, 5, 0, 0)  # a Monday: day-of-week restrictions are judged over a typical day
    return sum(1 for i in range(1440) if cron_matches(expr, start + timedelta(minutes=i)))


def describe_cron(expr: str) -> str:
    fields = expr.split()
    unusual = f"no horário agendado ({expr})"
    if len(fields) != 5 or not (fields[0].isdigit() and fields[1].isdigit()) or fields[2] != "*" or fields[3] != "*":
        return unusual
    at = f"às {int(fields[1]):02d}:{int(fields[0]):02d}"
    dow = fields[4]
    if dow == "*":
        return f"todo dia {at}"
    if dow == "1-5":
        return f"de segunda a sexta {at}"
    if dow in ("0,6", "6,0"):
        return f"aos sábados e domingos {at}"
    if dow.isdigit() and int(dow) in _DAY_NAMES:
        name = _DAY_NAMES[int(dow)]
        return f"toda {name} {at}" if name.endswith("feira") else f"todo {name} {at}"
    return unusual
