import re

from .base import GateResult, Route

# Research is checked before task: "search and write a summary" is research.
_RESEARCH = re.compile(
    r"\b(?:search|google|look up|find out|latest|news"
    r"|pesquis\w*|busc\w*|busq\w*|procur\w*|not[ií]cias|[uú]ltim\w+)\b",
    re.IGNORECASE,
)
_TASK = re.compile(
    r"\b(?:write|create|build|implement|refactor|run|script|code|file"
    r"|escrev\w*|cri[ae]\w*|implement\w*|rod[ae]\w*|c[óo]digo|arquivo\w*)\b",
    re.IGNORECASE,
)


# Creating a rule that runs by itself: "automatize...", "toda vez que ... responda", "todo dia às 9h mande...".
_AUTOMATION_WORD = re.compile(r"\bautoma\w+", re.IGNORECASE)
_AUTOMATION_TRIGGER = re.compile(r"\b(?:toda\s+vez\s+que|sempre\s+que|a\s+cada\s+vez\s+que|todo\s+dia|todos\s+os\s+dias|todo\s+santo\s+dia)\b", re.IGNORECASE)
_AUTOMATION_VERB = re.compile(r"\b(?:respond\w*|envi\w*|mand\w*|avis\w*|lembr\w*)\b", re.IGNORECASE)

# Explicit "go and look it up" verbs win over calendar words ("pesquise a agenda política").
_EXPLICIT_SEARCH = re.compile(
    r"\b(?:pesquis\w*|busc\w*|busq\w*|procur\w*|search|google|look up|find out)\b", re.IGNORECASE
)
_CALENDAR = re.compile(
    r"\b(?:calend[aá]rio|agenda|agend\w+|reuni[aã]o|reuni[oõ]es|compromissos?|eventos?"
    r"|meetings?|calendar|appointments?|schedule)\b",
    re.IGNORECASE,
)
_WHATSAPP = re.compile(
    r"\b(?:whats\w*|zap(?:zap)?|wpp|mensagens?\s+(?:novas?|n[ãa]o\s+lidas?)"
    r"|(?:manda|mande|envie|enviar|mandar)\s+(?:uma?\s+)?mensagem)\b",
    re.IGNORECASE,
)
# "marque dentista dia 30 às 9h": a scheduling verb PLUS a hint of WHEN (a verb alone is too common: "marque o gol").
_SCHEDULE_VERB = re.compile(
    r"\b(?:(?:des|re)?marcar|(?:des|re)?marque[m]?|cancelar|cancele[m]?)\b", re.IGNORECASE
)  # marcar -> marque (c becomes qu)
_WHEN = re.compile(
    r"\b(?:dia\s+\d{1,2}|\d{1,2}\s*h\b|\d{1,2}:\d{2}|\d{1,2}\s*horas?|amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta"
    r"|s[áa]bado|domingo|pr[óo]xim[ao]|meio-dia|meia-noite)\b",
    re.IGNORECASE,
)


class HeuristicGate:
    source = "heuristic"

    def classify(self, text: str) -> GateResult:
        if _AUTOMATION_WORD.search(text) or (_AUTOMATION_TRIGGER.search(text) and _AUTOMATION_VERB.search(text)):
            return GateResult(Route.AUTOMATION, 0.9, self.source)
        if _WHATSAPP.search(text) and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.WHATSAPP, 0.9, self.source)
        is_calendar = _CALENDAR.search(text) or (_SCHEDULE_VERB.search(text) and _WHEN.search(text))
        if is_calendar and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.CALENDAR, 0.9, self.source)
        if _RESEARCH.search(text):
            return GateResult(Route.RESEARCH, 0.9, self.source)
        if _TASK.search(text):
            return GateResult(Route.TASK, 0.9, self.source)
        return GateResult(Route.CHAT, 0.55, self.source)
