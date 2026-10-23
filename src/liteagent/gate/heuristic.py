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


# Explicit "go and look it up" verbs win over calendar words ("pesquise a agenda política").
_EXPLICIT_SEARCH = re.compile(
    r"\b(?:pesquis\w*|busc\w*|busq\w*|procur\w*|search|google|look up|find out)\b", re.IGNORECASE
)
_CALENDAR = re.compile(
    r"\b(?:calend[aá]rio|agenda|agend\w+|reuni[aã]o|reuni[oõ]es|compromissos?|eventos?"
    r"|meetings?|calendar|appointments?|schedule)\b",
    re.IGNORECASE,
)


class HeuristicGate:
    source = "heuristic"

    def classify(self, text: str) -> GateResult:
        if _CALENDAR.search(text) and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.CALENDAR, 0.9, self.source)
        if _RESEARCH.search(text):
            return GateResult(Route.RESEARCH, 0.9, self.source)
        if _TASK.search(text):
            return GateResult(Route.TASK, 0.9, self.source)
        return GateResult(Route.CHAT, 0.55, self.source)
