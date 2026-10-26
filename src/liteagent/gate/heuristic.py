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


# Asking for the browser to be used ("use o navegador para...", "pelo Chrome", "navegue até..."): wins over everything else.
# ("abre o Chrome" alone is opening a program: that stays with the computer.)
_BROWSER = re.compile(
    r"\b(?:use|usa|usar|utilize|utilizar|usando|utilizando|pelo|no|via|com\s+o)\s+(?:o\s+)?(?:navegador|browser|chrome)\b|\bnavegu?e\w*\b|\bnavegar\b",
    re.IGNORECASE,
)

# Making a Word / Excel / PowerPoint style file ("crie slides sobre...", "monte uma planilha no Numbers"): a computer job even when
# the request also says to look something up ("... sobre o tema pesquisado").
_DOC_MAKE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|mont\w+|ger[ae]\w*|escrev\w+|prepar\w+)\b", re.IGNORECASE)
_DOC_NOUN = re.compile(r"\b(?:slides?|apresenta[çc][ãa]o|apresenta[çc][õo]es|keynote|powerpoint|planilha|numbers|excel|tabela|pages|docx|documento)\b", re.IGNORECASE)

# Creating a rule that runs by itself: "automatize...", "toda vez que ... responda", "todo dia às 9h mande...".
_AUTOMATION_WORD = re.compile(r"\bautoma\w+", re.IGNORECASE)
_AUTOMATION_TRIGGER = re.compile(r"\b(?:toda\s+vez\s+que|sempre\s+que|a\s+cada\s+vez\s+que|todo\s+dia|todos\s+os\s+dias|todo\s+santo\s+dia)\b", re.IGNORECASE)
_AUTOMATION_VERB = re.compile(r"\b(?:respond\w*|envi\w*|mand\w*|avis\w*|lembr\w*)\b", re.IGNORECASE)

# The house: a device word AND something said about it ("liga a luz da sala", "a porta está trancada?").
_HOME_NOUN = re.compile(r"\b(luz(?:es)?|l[âa]mpadas?|tomadas?|ventilador|ar[- ]condicionado|termostato|persianas?|cortinas?|port[ãa]o|garagem|fechadura|alexa|home assistant)\b", re.IGNORECASE)
_HOME_VERB = re.compile(r"\b(lig\w+|deslig\w+|apag\w+|acend\w+|abr\w+|fech\w+|tranc\w+|destranc\w+|ajust\w+|coloc\w+|ativ\w+|diminu\w+|aument\w+|est[áa]|esta)\b", re.IGNORECASE)
_HOME_PHRASE = re.compile(r"\b(?:ativ\w+|coloc\w+)\s+(?:a\s+)?cena\b|\bporta\b.{0,25}\b(?:trancad\w+|aberta|fechada|destranc\w+)\b|\b(?:tranc\w+|destranc\w+)\s+a\s+porta\b", re.IGNORECASE)

# The computer itself: making a file, opening a program / site / folder (an imperative at the start: "abre o Spotify").
_COMPUTER_FILE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|salv\w+|grav\w+|escrev\w+|ger[ae]\w*|mont\w+)\b[^.?!]{0,40}\b(?:arquivo|documento|txt|csv|planilha|anota[çc][ãa]o|nota|pasta|diret[óo]rio)\b"
                           r"|\b(?:mov\w+|mand\w+|copi\w+|renome\w+|edit\w+|apag\w+|delet\w+|exclu\w+|remov\w+|baix\w+|rod[ae]\w*|execut\w+|revert\w+|list\w+|mostr\w+)\b[^?!]{0,40}\b(?:arquivo|pasta|diret[óo]rio|script|lixeira|backup)\b", re.IGNORECASE)
_COMPUTER_OPEN = re.compile(r"^\W*(?:por favor,?\s*|pode\s+)?(?:abr\w+|inici\w+|lan[çc]\w+)\s+(?:o\s+|a\s+|os\s+|as\s+|um\s+|uma\s+)?\w", re.IGNORECASE)

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
        if _BROWSER.search(text):
            return GateResult(Route.BROWSER, 0.9, self.source)
        if (_HOME_NOUN.search(text) and _HOME_VERB.search(text) and not _WHATSAPP.search(text)) or _HOME_PHRASE.search(text):
            return GateResult(Route.HOME, 0.9, self.source)
        if _DOC_MAKE.search(text) and _DOC_NOUN.search(text) and not _WHATSAPP.search(text):
            return GateResult(Route.COMPUTER, 0.9, self.source)
        if _AUTOMATION_WORD.search(text) or (_AUTOMATION_TRIGGER.search(text) and _AUTOMATION_VERB.search(text)):
            return GateResult(Route.AUTOMATION, 0.9, self.source)
        if _WHATSAPP.search(text) and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.WHATSAPP, 0.9, self.source)
        is_calendar = _CALENDAR.search(text) or (_SCHEDULE_VERB.search(text) and _WHEN.search(text))
        if is_calendar and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.CALENDAR, 0.9, self.source)
        if (_COMPUTER_FILE.search(text) or _COMPUTER_OPEN.search(text)) and not _EXPLICIT_SEARCH.search(text):
            return GateResult(Route.COMPUTER, 0.9, self.source)
        if _RESEARCH.search(text):
            return GateResult(Route.RESEARCH, 0.9, self.source)
        if _TASK.search(text):
            return GateResult(Route.TASK, 0.9, self.source)
        return GateResult(Route.CHAT, 0.55, self.source)
