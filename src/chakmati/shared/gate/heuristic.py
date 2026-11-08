import re

from chakmati.shared.gate.base import GateResult, Route

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

# Opening a page FOR THE PERSON to use ("abrir uma página no navegador para eu baixar"): it is their own browser (the computer opens the address), not the
# automatic browser that works through a site by itself. Anything that has the agent do the work on the page (sign in, add to the cart) still goes to the agent.
_AGENT_WORK = re.compile(r"\b(?:entr(?:e|ar)\s+(?:no|na)|logu\w+|preench\w+|cliqu\w+|digit\w+|adicion\w+|compr\w+|carrinho|senha|login)\b", re.IGNORECASE)
_OWN_BROWSER = re.compile(r"\b(?:abr\w+|abra|mostr\w+)\b.{0,40}\b(?:p[áa]gina|site|link|endere[çc]o)\b.{0,40}\b(?:para|pra)\s+eu\b", re.IGNORECASE)

# Making a Word / Excel / PowerPoint style file ("crie slides sobre...", "monte uma planilha no Numbers"): a computer job even when
# the request also says to look something up ("... sobre o tema pesquisado").
_DOC_MAKE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|mont\w+|ger[ae]\w*|escrev\w+|prepar\w+)\b", re.IGNORECASE)
_DOC_NOUN = re.compile(r"\b(?:slides?|apresenta[çc][ãa]o|apresenta[çc][õo]es|keynote|powerpoint|planilha|numbers|excel|tabela|pages|docx|documento)\b", re.IGNORECASE)

_GRADE = re.compile(r"\b(?:corrij\w+|corrig\w+|corre[çc][ãa]o)\b.{0,60}\bprovas?\b|\bprovas?\b.{0,60}\b(?:corrij\w+|corrig\w+)", re.IGNORECASE)  # "corrija as provas..."

# A site or social network named with something to do there ("acesse meu instagram e envie...", "entre no youtube"): the browser, not WhatsApp or the calendar.
_SITE_NAME = re.compile(r"\b(?:instagram|facebook|youtube|linkedin|twitter|tiktok|github|gmail|outlook|netflix|amazon|mercado\s?livre|x\.com|shein|aliexpress|shopee|magalu|magazine\s?luiza|americanas|zara|nike|renner|lojas\s?renner|c&a|riachuelo|hering|centauro|netshoes|kabum|casas\s?bahia|carrefour|leroy\s?merlin|ifood|submarino|shoptime|dafiti|farfetch|ebay|etsy)\b", re.IGNORECASE)
# Shopping done on a site, said without naming it ("adicione ao carrinho", "coloque na sacola"): the browser, never a web search
_CART = re.compile(r"\b(?:adicion\w+|coloc\w+|p[oô]n\w+|ponha|add|inclu\w+|jog\w+|mand\w+)\b.{0,50}\b(?:carrinho|cesta|sacola)\b", re.IGNORECASE)
_STORE_PHRASE = re.compile(r"\b(?:na|no|em)\s+(?:a\s+|o\s+)?(?:loja|site|app|aplicativo|p[áa]gina)\s+(?:da|do|de)\s+\w+", re.IGNORECASE)
_SITE_ACT = re.compile(r"\b(?:acess\w+|entr\w+|abr\w+|logu\w+|naveg\w+|v[áa]\s+(?:para|ao|no|na)|envi\w+|mand\w+|post\w+|curt\w+|segu\w+|pesquis\w+|busc\w+|busqu\w+|procur\w+|compar\w+|ach\w+|encontr\w+|traga|liste)\b", re.IGNORECASE)

# An address with something to DO on the page ("entre em https://... com o meu usuário", "abra https://... e me diga o título"): the browser agent.
# A bare "abra https://..." is just opening the page in the person's own browser (the computer).
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_URL_TASK = re.compile(r"\b(?:acess\w+|entr\w+|logu\w+|naveg\w+|cliqu\w+|digit\w+|preench\w+|diga|dizer|copi\w+|le(?:ia|r)|encontr\w+|extra\w+|resum\w+|compar\w+|me\s+(?:diga|mostre|conte)|usu[áa]rio|senha|login)\b", re.IGNORECASE)

# Things said about files in plain words: a file name with an extension and a verb to do something with it, the trash, a copy "do X", downloading from an address.
_FILE_TOKEN = re.compile(r"\b[\w-]+\.(?:txt|md|csv|json|pdf|docx|xlsx|pptx|py|js|html|xml|log|jpg|jpeg|png|zip)\b|\b\w+/[\w-]+\.\w{2,5}\b", re.IGNORECASE)
_FILE_VERB = re.compile(r"\b(?:copi\w+|renome\w+|mov\w+|mand\w+|mostr\w+|leia|ler|abr\w+|edit\w+|apag\w+|delet\w+|exclu\w+|list\w+|cri\w+|fa[çc]a|troque|mude)\b", re.IGNORECASE)
_COMPUTER_WORDS = re.compile(r"^\W*edit\w+\s+(?:o|a|os|as)\s+\w+|\blixeira\b|\bc[óo]pia\s+d[oae]s?\b|\b(?:apag\w+|delet\w+|exclu\w+|remov\w+|limp\w+)\b.{0,20}\b(?:tudo|todos|todas)\b|\b(?:baix\w+|download)\b[^\n]*https://", re.IGNORECASE)

# Creating a rule that runs by itself: "automatize...", "toda vez que ... responda", "todo dia às 9h mande...".
_AUTOMATION_WORD = re.compile(r"\bautoma\w+", re.IGNORECASE)
_AUTOMATION_TRIGGER = re.compile(r"\b(?:toda\s+vez\s+que|sempre\s+que|a\s+cada\s+vez\s+que|todo\s+dia|todos\s+os\s+dias|todo\s+santo\s+dia)\b", re.IGNORECASE)
_AUTOMATION_VERB = re.compile(r"\b(?:respond\w*|envi\w*|mand\w*|avis\w*|lembr\w*)\b", re.IGNORECASE)

# The house: a device word AND something said about it ("liga a luz da sala", "a porta está trancada?").
_HOME_NOUN = re.compile(r"\b(luz(?:es)?|l[âa]mpadas?|tomadas?|ventilador|ar[- ]condicionado|termostato|persianas?|cortinas?|port[ãa]o|garagem|fechadura|alexa|home assistant)\b", re.IGNORECASE)
_HOME_VERB = re.compile(r"\b(lig\w+|deslig\w+|apag\w+|acend\w+|abr\w+|fech\w+|tranc\w+|destranc\w+|ajust\w+|coloc\w+|ativ\w+|diminu\w+|aument\w+|est[áa]|esta)\b", re.IGNORECASE)
# Music on the speakers (Alexa) through the house: "próxima música", "pausa a música da sala", "volume em 30", "aumenta o volume".
_HOME_MUSIC = re.compile(
    r"\b(?:pr[óo]xima|pul[ae]r?|pula|troc\w+|mud\w+|volt\w+|anterior|paus\w+|pause|continu\w+|retom\w+)\b.{0,25}\b(?:m[úu]sica|faixa|can[çc][ãa]o)\b"
    r"|\b(?:aument\w+|diminu\w+|abaix\w+|baix\w+|sobe|suba|reduz\w*)\b.{0,20}\bvolume\b|\bvolume\b.{0,20}\b\d{1,3}\b|^\W*pr[óo]xima\W*$"
    r"|\b(?:o\s+que|que\s+m[úu]sica|qual\s+m[úu]sica|que\s+faixa)\b.{0,20}\b(?:est[áa]\s+tocando|toca|tocando)\b"
    # asking the Echo for something to play: "toca Raul Seixas na Alexa", "coloca Djavan no echo da sala", "Alexa, toca Anitta" (a play verb at the start AND the Alexa named)
    r"|^\W*(?:(?:ei|oi|ol[áa])?\W*alexa\W+)?(?:toca|toque|tocar|coloca|coloque|p[õo]e|ponha|bota|quero\s+(?:ouvir|escutar))\b(?:.{0,80}\b(?:alexa|echo|caixa\s+de\s+som)\b|(?<=alexa, toca)\b.{0,80})",
    re.IGNORECASE,
)
_HOME_PHRASE = re.compile(r"\b(?:ativ\w+|coloc\w+)\s+(?:a\s+)?cena\b|\bporta\b.{0,25}\b(?:trancad\w+|aberta|fechada|destranc\w+)\b|\b(?:tranc\w+|destranc\w+)\s+a\s+porta\b", re.IGNORECASE)

# The computer itself: making a file, opening a program / site / folder (an imperative at the start: "abre o Spotify").
_COMPUTER_FILE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|salv\w+|grav\w+|escrev\w+|ger[ae]\w*|mont\w+)\b[^.?!]{0,40}\b(?:arquivo|documento|txt|csv|planilha|anota[çc][ãa]o|nota|pastas?|diret[óo]rio)\b"
                           r"|\b(?:mov\w+|mand\w+|copi\w+|renome\w+|edit\w+|apag\w+|delet\w+|exclu\w+|remov\w+|baix\w+|rod[ae]\w*|execut\w+|revert\w+|list\w+|mostr\w+)\b[^?!]{0,40}\b(?:arquivos?|pastas?|diret[óo]rio|script|lixeira|backup)\b", re.IGNORECASE)
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
        if _OWN_BROWSER.search(text) and not (_CART.search(text) or _AGENT_WORK.search(text)):
            return GateResult(Route.COMPUTER, 0.9, self.source)
        if _BROWSER.search(text) or _CART.search(text) or (_URL.search(text) and _URL_TASK.search(text) and not re.search(r"\bwhats\w*|\bzap", text, re.IGNORECASE)) or ((_SITE_NAME.search(text) or _STORE_PHRASE.search(text)) and _SITE_ACT.search(text) and not re.search(r"\bwhats\w*|\bzap", text, re.IGNORECASE)):
            return GateResult(Route.BROWSER, 0.9, self.source)
        if (_HOME_NOUN.search(text) and _HOME_VERB.search(text) and not _WHATSAPP.search(text)) or _HOME_PHRASE.search(text) or _HOME_MUSIC.search(text):
            return GateResult(Route.HOME, 0.9, self.source)
        if _GRADE.search(text):
            return GateResult(Route.COMPUTER, 0.9, self.source)
        if (_COMPUTER_WORDS.search(text) or (_FILE_TOKEN.search(text) and _FILE_VERB.search(text))) and not (_URL.search(text) and _URL_TASK.search(text)) and not _WHATSAPP.search(text):
            return GateResult(Route.COMPUTER, 0.9, self.source)
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
