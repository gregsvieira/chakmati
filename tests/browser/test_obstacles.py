"""Cookie notices and pop-ups that cover a shop are pressed away by code before the model is asked anything (the Shein case)."""

from liteagent.browser.agent import BrowserAgent, start_url
from liteagent.browser.frames import FrameStore
from liteagent.browser.session import Snapshot
from liteagent.gate.base import Route
from liteagent.gate.heuristic import HeuristicGate

JOB = "c" * 32


def el(i, label, tag="button", overlay=False, cls="", type_=""):
    return {"id": i, "tag": tag, "type": type_, "label": label, "overlay": overlay, "cls": cls}


COOKIES = Snapshot("https://loja.test/", "Loja", "Usamos cookies para melhorar a sua experiência. Política de Privacidade", [
    el(1, "Configurar cookies"), el(2, "Aceitar todos os cookies"), el(3, "Vestido", tag="input")])
COOKIES_WITH_CHOICE = Snapshot("https://loja.test/", "Loja", "Este site usa cookies", [el(1, "Aceitar todos"), el(2, "Rejeitar não essenciais")])
POPUP = Snapshot("https://loja.test/", "Loja", "Já sou cliente / Registrar", [el(1, "", overlay=True, cls="login-modal__close icon"), el(2, "Prosseguir com Facebook", overlay=True)])
CLEAN = Snapshot("https://loja.test/", "Loja", "Camisetas", [el(1, "Entrar"), el(2, "Pesquisar", tag="input")])


def test_cookies_the_strictest_choice_offered_wins():
    assert BrowserAgent.obstacle(COOKIES_WITH_CHOICE)[0]["id"] == 2


def test_when_only_accept_is_offered_it_is_pressed():
    element, note = BrowserAgent.obstacle(COOKIES)
    assert element["id"] == 2 and "cookies" in note


def test_a_popup_is_closed_by_its_own_close_button_even_without_a_label():
    element, note = BrowserAgent.obstacle(POPUP)
    assert element["id"] == 1 and note == "Fechando um aviso do site"


def test_a_page_with_nothing_in_the_way_is_left_alone():
    assert BrowserAgent.obstacle(CLEAN) is None


def test_the_word_accept_on_a_page_without_a_cookie_notice_is_not_pressed():
    page = Snapshot("https://x.test/", "Convite", "Você recebeu um convite para a reunião", [el(1, "Aceitar convite")])
    assert BrowserAgent.obstacle(page) is None


def test_a_close_button_that_is_not_part_of_a_popup_is_not_pressed():
    page = Snapshot("https://x.test/", "Editor", "Texto", [el(1, "Fechar", overlay=False)])   # "Fechar" of the page itself (close the document)
    assert BrowserAgent.obstacle(page) is None


class Session:
    def __init__(self, pages):
        self.pages, self.clicks, self.i = pages, [], 0

    async def start(self): pass
    async def close(self): pass
    async def goto(self, url): pass
    async def back(self): pass
    async def scroll(self, down): pass
    async def type(self, ident, text, submit, secret=False): pass
    async def screenshot(self): return b"\xff\xd8x"
    async def snapshot(self): return self.pages[min(self.i, len(self.pages) - 1)]

    async def click(self, ident):
        self.clicks.append(ident)
        self.i += 1   # pressing it makes the next page appear


class LLM:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return '{"action":"done","answer":"pronto"}'


async def test_the_agent_clears_the_notices_before_asking_the_model(tmp_path):
    session, llm = Session([COOKIES, POPUP, CLEAN]), LLM()
    agent = BrowserAgent(llm, FrameStore(tmp_path), lambda: session)
    out = [p async for p in agent.run(JOB, "abra https://loja.test/ e liste as camisetas")]
    assert out == ["pronto"] and session.clicks == [2, 1]                  # cookies, then the pop-up
    assert "Camisetas" in llm.prompts[0]
    assert "Usamos cookies" not in llm.prompts[0]                           # the model only sees the clean page
    notes = [f["note"] for f in FrameStore(tmp_path).list(JOB)]
    assert "Fechando o aviso de cookies" in notes and "Fechando um aviso do site" in notes


async def test_a_notice_that_will_not_go_away_is_tried_a_few_times_only(tmp_path):
    class Stuck(Session):
        async def click(self, ident): self.clicks.append(ident)               # nothing changes
    session = Stuck([COOKIES])
    agent = BrowserAgent(LLM(), FrameStore(tmp_path), lambda: session)
    [p async for p in agent.run(JOB, "abra https://loja.test/")]
    assert len(session.clicks) == 3


def test_a_store_named_in_the_request_goes_to_the_browser_and_opens_directly():
    for text in ("Pesquise na loja da Shein três camisetas oversized e me traga a lista delas", "procure na loja da Zara uma jaqueta", "pesquise no site da Amazon um fone"):
        assert HeuristicGate().classify(text).route is Route.BROWSER
    assert start_url("Pesquise na loja da Shein três camisetas") == "https://br.shein.com/"
    assert HeuristicGate().classify("pesquise a capital da Austrália").route is Route.RESEARCH   # a question is still a search


async def test_a_browser_that_dies_is_reported_in_a_sentence(tmp_path):
    class Dies(Session):
        async def snapshot(self): raise RuntimeError("Page.evaluate: Target page, context or browser has been closed")
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: Dies([CLEAN])).run(JOB, "abra https://loja.test/")]
    assert len(out) == 1 and out[0].startswith("Não consegui continuar") and "Page.evaluate" not in out[0]


# ------------------------------------------------------------------------------------------------ a human check: the person passes it, the Chakmati does not
from liteagent.browser.agent import BLOCKED, DECLINED, needs_human, still_blocked

CHALLENGE = Snapshot("https://br.shein.com/risk/challenge?captcha_type=909&redirection=x", "", "", [])
SHOP = Snapshot("https://br.shein.com/", "Shein", "Camisetas oversized R$ 59,90", [el(1, "Pesquisar", tag="input")])


def test_a_challenge_page_is_recognised_by_its_address_or_by_what_it_says():
    assert needs_human(CHALLENGE)
    assert needs_human(Snapshot("https://x.test/", "Just a moment", "Verify you are a human by completing the action below", []))
    assert needs_human(Snapshot("https://x.test/", "x", "tráfego incomum na sua rede", []))
    assert not needs_human(SHOP)


class Visible(Session):
    def __init__(self, pages, passes=True):
        super().__init__(pages)
        self.visible, self.reopened, self.passes = False, 0, passes

    async def reopen_visible(self):
        self.visible, self.reopened = True, self.reopened + 1
        self.i += 0

    async def snapshot(self):
        # the challenge stays until the window was opened and the person passed it (modelled as: visible and passes)
        return SHOP if (self.visible and self.passes) else self.pages[0]


async def test_a_human_check_opens_the_window_asks_the_person_and_goes_on(tmp_path):
    asked, session, llm = [], Visible([CHALLENGE]), LLM()

    async def ask(job_id, key, question, secret=False, confirm=False):
        asked.append((key, secret, confirm, session.visible))
        return "ok"
    out = [p async for p in BrowserAgent(llm, FrameStore(tmp_path), lambda: session, ask=ask).run(JOB, "abra https://br.shein.com/")]
    assert out == ["pronto"] and session.reopened == 1
    assert asked == [("verificacao", False, True, True)]                       # asked only after the window is there, with the confirm button
    assert "Camisetas oversized" in llm.prompts[0]                              # the model only works on the page after the person passed the check
    notes = [f["note"] for f in FrameStore(tmp_path).list(JOB)]
    assert "Esperando você resolver a verificação" in notes and "Continuando" in notes


async def test_a_check_that_is_still_there_after_the_person_was_asked_stops(tmp_path):
    async def ask(*args, **kw): return "ok"
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: Visible([CHALLENGE], passes=False), ask=ask, check_wait=0).run(JOB, "abra https://br.shein.com/")]
    assert out == [BLOCKED]


async def test_without_anyone_to_ask_a_human_check_stops_and_says_so(tmp_path):
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: Visible([CHALLENGE])).run(JOB, "abra https://br.shein.com/")]
    assert out == [BLOCKED]


async def test_the_second_check_in_a_visible_window_is_not_asked_again(tmp_path):
    asked = []

    async def ask(*a, **kw):
        asked.append(1)
        return "ok"
    session = Visible([CHALLENGE], passes=False)
    session.visible = True                    # already a visible window
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: session, ask=ask).run(JOB, "abra https://br.shein.com/")]
    assert out == [BLOCKED] and asked == []


async def test_nao_consegui_stops_at_once_with_its_own_message(tmp_path):
    asked = []

    async def ask(job_id, key, question, secret=False, confirm=False):
        asked.append(question)
        return "nao"
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: Visible([CHALLENGE], passes=False), ask=ask, check_wait=0).run(JOB, "abra https://br.shein.com/")]
    assert out == [DECLINED] and len(asked) == 1


async def test_a_check_still_there_is_asked_again_and_then_passes(tmp_path):
    session, answers = Visible([CHALLENGE], passes=False), []

    async def ask(job_id, key, question, secret=False, confirm=False):
        answers.append(question)
        if len(answers) == 2:
            session.passes = True      # the person finished on the second try
        return "ok"
    out = [p async for p in BrowserAgent(LLM(), FrameStore(tmp_path), lambda: session, ask=ask, check_wait=0).run(JOB, "abra https://br.shein.com/")]
    assert out == ["pronto"] and len(answers) == 2 and "Ainda vejo" in answers[1]


def test_a_real_page_that_only_mentions_captcha_in_its_fine_print_is_let_through():
    many = [{"id": i, "tag": "a", "type": "", "label": f"item {i}"} for i in range(20)]
    assert not still_blocked(Snapshot("https://br.shein.com/women", "Roupas", "texto protegido por captcha", many))
    assert still_blocked(Snapshot("https://br.shein.com/risk/challenge?x=1", "Roupas", "ok", many))
    assert still_blocked(CHALLENGE)


def test_the_plan_ends_with_the_goal_before_the_warning():
    plan = BrowserAgent(LLM(), None, None).plan("pesquise na loja da Shein três camisetas oversized e adicione ao carrinho")
    assert plan[-3:] == ["Adicionar ao carrinho (sem pagar).", "Informar que foi adicionado ao carrinho (ou o que impediu).", plan[-1]]
    assert plan[-1].startswith("Atenção") and not any(p.startswith("Responder no idioma") for p in plan)


def test_a_plan_without_a_goal_still_ends_by_answering():
    plan = BrowserAgent(LLM(), None, None).plan("pesquise o protocolo MCP")
    assert plan[-2] == "Responder no idioma do pedido, com o que está na página."


def test_other_goals_get_their_own_steps_and_paying_is_left_to_the_person():
    from liteagent.browser.agent import goal_steps
    assert "pagar é com você" in goal_steps("compre esse tênis no site")[0]
    assert goal_steps("baixe o pdf da fatura")[0].startswith("Baixar")
    assert goal_steps("pesquise sobre gatos") == []


def test_shopping_on_a_site_goes_to_the_browser_even_when_the_store_is_not_known_by_name():
    for text in ("pesquise três camisetas oversized na Renner e adicione ao carrinho",
                 "procure um tênis no site da Vivara e coloque na sacola",
                 "adicione esse produto ao carrinho",
                 "busque camisetas na Riachuelo"):
        assert HeuristicGate().classify(text).route is Route.BROWSER, text
    assert HeuristicGate().classify("qual a capital da França?").route is not Route.BROWSER


def test_more_stores_open_straight_at_their_site():
    assert start_url("acesse a Renner e veja camisetas") == "https://www.lojasrenner.com.br/"
