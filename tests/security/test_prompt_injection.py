"""Prompt injection through every road third-party text takes into the assistant: WhatsApp, text read from scans (OCR), text files, web
search and web pages. Each road is attacked with every string in payloads.py. What must hold, whatever the model does:
  * hostile text cannot close the block it sits in, cannot carry the app's own `[[action:...]]` buttons or chat-template tokens;
  * the model is told the block is data;
  * nothing is sent, deleted, opened or created because of it;
  * what comes back to the person has no `[[action:...]]` marker, even if the model echoes one."""

import json
import re
import unicodedata
from datetime import datetime, timezone

import httpx
import pytest

from chakmati.features.browser.agent import BrowserAgent
from chakmati.features.browser.frames import FrameStore
from chakmati.features.browser.session import Snapshot
from chakmati.features.computer import documents, grading
from chakmati.features.computer.assistant import ComputerAssistant
from chakmati.features.computer.safety import ComputerError
from chakmati.features.computer.service import ComputerService
from chakmati.features.research.fetch import PageFetcher
from chakmati.features.research.search import SearchResult
from chakmati.features.research.tool import ResearchTool
from chakmati.features.whatsapp.assistant import Intent, WhatsAppAssistant
from chakmati.features.whatsapp.models import Chat, Message, Status
from chakmati.features.whatsapp.service import WhatsAppService
from chakmati.shared.approvals import ActionStore
from chakmati.shared.guard import UNTRUSTED_RULE, fence, neutralize, strip_markers

from .payloads import LOCAL_ADDRESSES, PROMPT_PAYLOADS

TS = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
IDS = range(len(PROMPT_PAYLOADS))
_MARKER = re.compile(r"\[\[\s*action", re.IGNORECASE)
_ROLE = re.compile(r"<\|[^>]*\|>|\[/?INST\]|<</?SYS>>|<(?:start|end)_of_turn>|^#{2,}\s*(?:System|Assistant|User)\s*:", re.IGNORECASE | re.MULTILINE)


def plain(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def assert_no_marker(text: str):
    assert not _MARKER.search(plain(text)), f"an action marker got through: {text[:200]!r}"


def assert_no_role_tokens(text: str):
    assert not _ROLE.search(plain(text)), f"a chat-template token got through: {text[:200]!r}"


def data_part(prompt: str, open_tag: str, close_tag: str) -> str:
    """What sits between the real opening and closing fence of a prompt."""
    assert prompt.count(close_tag) == 1, f"the data closed its own block: {prompt.count(close_tag)} closing tags"
    return prompt.split(open_tag, 1)[1].split(close_tag, 1)[0]


# ================================================================================================================= WhatsApp
class Provider:
    def __init__(self, payload):
        self.sent, self.payload = [], payload

    async def status(self):
        return Status(True, "READY")

    async def list_chats(self, unread_only=False, limit=50):
        return [Chat("111@lid", "Maria", False, 1, TS), Chat("222@lid", self.payload[:60], False, 1, TS), Chat("333@lid", self.payload[:60], False, 1, TS)]

    async def get_messages(self, chat_id, last=20):
        return [Message(f"m{i}", chat_id, self.payload[:80], self.payload, TS, False) for i in range(1, 4)]   # three: enough for a summary to go through the model

    async def send_text(self, chat_id, text):
        self.sent.append((chat_id, text))
        return "x"


class LLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def chat(self, messages):
        self.prompts.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    async def stream_chat(self, messages):
        self.prompts.append(messages)
        yield self.replies[0]


def whatsapp(payload, *replies):
    provider = Provider(payload)
    service = WhatsAppService(provider, ActionStore(":memory:"))
    llm = LLM(*replies)
    return WhatsAppAssistant(llm, service), service, provider, llm


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_whatsapp_reading_a_hostile_message_is_only_text(payload):
    assistant, service, provider, _ = whatsapp(payload, '{"action":"read","contact":"Maria"}')
    out = await assistant.handle("o que a Maria disse?")
    assert_no_marker(out)
    assert service.pending() == [] and provider.sent == []


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_whatsapp_summary_prompt_keeps_the_data_inside_its_block(payload):
    assistant, service, provider, llm = whatsapp(payload, '{"action":"summarize","contact":"Maria"}', f"Resumo. {payload}")
    out = await assistant.handle("resuma a conversa com a Maria")
    system, user = llm.prompts[1][0]["content"], llm.prompts[1][1]["content"]
    assert UNTRUSTED_RULE.strip() in system
    block = data_part(user, "<<<MESSAGES", "MESSAGES>>>")
    assert "<untrusted" not in plain(block).lower() and "</untrusted" not in plain(block).lower()
    assert_no_marker(block)
    assert_no_role_tokens(block)
    assert_no_marker(out)                                  # the model echoed the payload: it still cannot reach the person as a button
    assert service.pending() == [] and provider.sent == []


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_whatsapp_a_short_hostile_conversation_is_shown_as_text_and_never_reaches_the_model(payload):
    """Fewer than three messages are not summarised: they are shown as they are, cleaned like any other message."""
    assistant, service, provider, llm = whatsapp(payload, '{"action":"summarize","contact":"Maria"}')
    provider.get_messages = lambda chat_id, last=20: _one(chat_id, payload)
    out = await assistant.handle("resuma a conversa com a Maria")
    assert len(llm.prompts) == 1                     # only the call that understood the request
    assert_no_marker(out)
    assert_no_role_tokens(out)
    assert service.pending() == [] and provider.sent == []


async def _one(chat_id, payload):
    return [Message("m1", chat_id, payload[:80], payload, TS, False)]


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_whatsapp_a_hostile_chat_name_is_not_trusted_either(payload):
    """Group and contact names are written by other people too: they appear in the prompt and in the 'which one?' question."""
    assistant, service, provider, llm = whatsapp(payload, "ok")
    # two chats carry the same hostile name: the assistant lists them back to the person
    reply = await assistant._summarize(Intent("summarize", payload[:60], None, None))
    assert_no_marker(reply)
    assert_no_role_tokens(reply)
    for call in llm.prompts:
        assert_no_marker(call[-1]["content"])
        assert_no_role_tokens(call[-1]["content"])
    assert service.pending() == [] and provider.sent == []


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS[-3:], ids=range(3))
async def test_whatsapp_a_model_that_obeys_a_hostile_message_still_cannot_send(payload):
    assistant, service, provider, _ = whatsapp(payload, '{"action":"summarize","contact":"Maria"}', payload)
    out = await assistant.handle("resuma a conversa com a Maria")
    assert "Resumo da conversa" in out and service.pending() == [] and provider.sent == []


# ===================================================================================================================== OCR
class Question:
    def __init__(self, stem, options):
        self.stem, self.options = stem, options


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_ocr_text_of_an_exam_is_fenced_and_cannot_close_its_block(payload):
    llm = LLM(payload)
    assistant = ComputerAssistant(llm, service=None)
    question = Question(payload, {"A": payload, "B": payload})
    await assistant._solve(question, "A", llm)
    await assistant._explain(question, "solução", "B", "A")
    for system_user in llm.prompts:
        system, user = system_user[0]["content"], system_user[1]["content"]
        assert UNTRUSTED_RULE.strip() in system
        assert user.count("</untrusted>") == 1, "OCR text closed its own block"
        assert_no_marker(user)
        assert_no_role_tokens(user)
    # (the options the teacher's key points at are OCR text too: they are inside the block, not beside it)
    outputs = [await assistant._solve(question, "A", llm), await assistant._explain(question, "solução", "B", "A")]
    for out in outputs:
        assert_no_marker(out)


@pytest.mark.parametrize("payload", ["=HYPERLINK(\"http://evil.example\",\"x\")", "=cmd|' /C calc'!A0", "+SUM(A1:A9)", "-2+3", "@SUM(A1)", "\t=1+1", "=IMPORTXML(\"http://evil.example\",\"//a\")"], ids=range(7))
def test_ocr_text_cannot_become_a_spreadsheet_formula(payload):
    """The student's name and the notes are read from a scan; a cell that starts with = + - @ is a formula to Excel and Numbers."""
    exam = grading.Exam("p.pdf", payload, {1: "A"}, (payload,))
    spec, _ = grading.grade([exam], {1: "A"}, 1)
    checked = documents.check_spec("xlsx", spec)               # must not raise, and must not carry the formula
    cells = [c for sheet in checked.data["sheets"] for row in sheet["rows"] for c in row if isinstance(c, str)]
    assert not any(c.lstrip().startswith(("=HYPERLINK", "=cmd", "=IMPORT", "+SUM", "@SUM")) for c in cells)
    row = checked.data["sheets"][0]["rows"][2]
    assert not str(row[0]).startswith(("=", "+", "-", "@", "\t")) and not str(row[-1]).startswith(("=", "+", "-", "@", "\t"))


# ============================================================================================================== text file
@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_a_hostile_text_file_is_fenced_and_cannot_make_the_edit_do_anything_else(tmp_path, payload):
    work = tmp_path / "work"
    work.mkdir()
    service = ComputerService(str(work), ActionStore(":memory:"), home=str(tmp_path))
    victim = work / "importante.txt"
    victim.write_text("não apague\n", encoding="utf-8")
    note = work / "nota.txt"
    note.write_text(f"lista\n{payload}\n", encoding="utf-8")
    llm = LLM(f"lista\n{payload}\nfim\n")                      # the model repeats the hostile text as the new file
    assistant = ComputerAssistant(llm, service)
    try:
        out = await assistant._act({"action": "edit", "path": "nota.txt", "instruction": "acrescente fim"}, "acrescente fim em nota.txt")
    except ComputerError:   # a file that looks like it holds secrets is refused before any model sees it: also fine
        assert llm.prompts == [] and service.pending() == []
        return
    prompt = llm.prompts[0]
    assert UNTRUSTED_RULE.strip() in prompt[0]["content"]
    block = data_part(prompt[1]["content"], '<untrusted source="file">', "</untrusted>")
    assert_no_marker(block)
    assert_no_role_tokens(block)
    proposed = service.pending()
    assert [a.kind for a in proposed] == ["computer.edit"], "the hostile file may only lead to the edit the person asked for"
    assert_no_marker(proposed[0].payload.get("content", "") if isinstance(proposed[0].payload, dict) else "")
    assert victim.exists() and victim.read_text(encoding="utf-8") == "não apague\n" and note.read_text(encoding="utf-8").startswith("lista")  # nothing changed yet: the edit waits for a yes
    assert out.count("[[action:") == 1                         # only the app's own button, made after the edit was proposed


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
def test_text_read_for_a_document_source_is_neutralized(payload):
    block = fence(payload, "file")
    assert block.count("</untrusted>") == 1 and block.count("<untrusted") == 1
    assert_no_marker(block)
    assert_no_role_tokens(block)


# ============================================================================================================== web search
PAGE = "<html><body><article><p>{text}</p><p>Mais detalhes importantes sobre o assunto aparecem neste segundo parágrafo, com informação suficiente.</p></article></body></html>"


class Search:
    def __init__(self, results):
        self.results = results

    async def search(self, query, limit=10):
        return self.results


class Scorer:
    def score(self, question, parts):
        return [min(len(p) / 1000, 1.0) for p in parts]


def tool_with(payload, llm):
    url = "https://a.test/1"
    handler = lambda request: httpx.Response(200, text=PAGE.format(text=payload), headers={"content-type": "text/html"})  # noqa: E731
    fetcher = PageFetcher(transport=httpx.MockTransport(handler))
    return ResearchTool(Search([SearchResult(payload[:80], url, payload)]), fetcher, llm, Scorer(), result_cutoff=0.0)


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_web_search_passages_stay_inside_their_block_and_answers_are_scrubbed(payload):
    llm = LLM(f"Resposta. {payload}")
    out = await tool_with(payload, llm).answer("assunto importante")
    messages = llm.prompts[0]
    assert UNTRUSTED_RULE.strip() in messages[0]["content"]
    block = data_part(messages[1]["content"], '<untrusted source="web">', "</untrusted>")
    assert_no_marker(block)
    assert_no_role_tokens(block)
    assert_no_marker(out.answer)
    assert_no_marker(out.render())


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_web_search_streamed_answers_are_scrubbed_too(payload):
    llm = LLM(f"Resposta. {payload}")
    pieces = [p async for p in tool_with(payload, llm).stream_answer("assunto importante")]
    assert_no_marker("".join(pieces))


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_web_text_gathered_for_a_document_is_neutralized(payload):
    text, _ = await tool_with(payload, LLM("x")).gather("assunto importante")
    assert_no_marker(text)
    assert_no_role_tokens(text)
    assert "</untrusted" not in plain(text).lower()


# ================================================================================================================= web pages
JOB = "a" * 32


class Session:
    def __init__(self, text, title, label):
        self.calls, self.url, self._snap = [], "about:blank", (text, title, label)

    async def start(self): ...
    async def close(self): ...
    async def goto(self, url): self.url = url; self.calls.append(("goto", url))
    async def back(self): ...
    async def click(self, ident): self.calls.append(("click", ident))
    async def type(self, ident, text, submit, secret=False): self.calls.append(("type", ident, text))
    async def scroll(self, down): ...
    async def screenshot(self): return b"\xff\xd8jpeg"

    async def snapshot(self):
        text, title, label = self._snap
        return Snapshot(self.url, title, text, [{"id": 1, "tag": "a", "type": "", "label": label}])


class Scripted:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def chat(self, messages):
        self.prompts.append(messages)
        return self.replies.pop(0)


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_a_hostile_page_is_fenced_and_its_answer_is_scrubbed(tmp_path, payload):
    session = Session(payload, payload[:80], payload[:80])
    llm = Scripted(json.dumps({"action": "done", "answer": "Achei: " + payload}))
    out = [p async for p in BrowserAgent(llm, FrameStore(tmp_path), lambda: session).run(JOB, "diga o título")]
    system, user = llm.prompts[0][0]["content"], llm.prompts[0][1]["content"]
    assert UNTRUSTED_RULE.strip() in system
    assert user.count("</untrusted>") == 1, "the page closed its own block"
    assert_no_marker(user)
    assert_no_role_tokens(user)
    assert_no_marker("".join(out))
    assert not [c for c in session.calls if c[0] in {"click", "type"}]


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
async def test_a_page_that_looks_like_orders_is_flagged_to_the_person(tmp_path, payload):
    from chakmati.shared.guard import looks_like_order, NOTE
    session = Session(payload, "t", "l")
    llm = Scripted('{"action":"done","answer":"resposta"}')
    out = "".join([p async for p in BrowserAgent(llm, FrameStore(tmp_path), lambda: session).run(JOB, "diga o título")])
    if looks_like_order(payload):
        assert NOTE.strip() in out


@pytest.mark.parametrize("address", LOCAL_ADDRESSES, ids=range(len(LOCAL_ADDRESSES)))
def test_a_page_cannot_send_the_browser_to_the_local_machine_or_the_house_network(address):
    from chakmati.features.browser.session import BrowserError, check_navigable
    with pytest.raises(BrowserError):
        check_navigable(address)


@pytest.mark.parametrize("address", ["https://example.org/", "http://1.1.1.1/", "https://[2606:4700:4700::1111]/", "https://sub.example.co.uk/a?b=c", "example.org"], ids=range(5))
def test_public_addresses_still_open(address):
    from chakmati.features.browser.session import check_navigable
    assert check_navigable(address).startswith("http")


# ============================================================================================================== the guard itself
@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
def test_neutralize_removes_what_could_break_out_or_fake_the_apps_own_markers(payload):
    out = neutralize(payload)
    assert_no_marker(out)
    assert_no_role_tokens(out)
    assert "untrusted" not in plain(out).lower()
    assert "MESSAGES>>>" not in out and "<<<MESSAGES" not in out
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]", out)


@pytest.mark.parametrize("payload", PROMPT_PAYLOADS, ids=IDS)
def test_strip_markers_cleans_whatever_the_model_echoes(payload):
    assert_no_marker(strip_markers(plain(payload)))
    assert_no_marker(strip_markers(payload))
