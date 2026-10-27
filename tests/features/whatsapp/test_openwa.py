import json
from datetime import datetime

import httpx
import pytest

from chakmati.features.whatsapp.models import Chat, Message
from chakmati.features.whatsapp.openwa import (
    OpenWAClient,
    WhatsAppAuthError,
    WhatsAppError,
    parse_chat,
    parse_message,
)

T = 1792780000  # unix seconds
LOCAL = lambda ts: datetime.fromtimestamp(ts).astimezone()  # noqa: E731


# ----------------------------------------------------------------------------- parsing chats (shapes seen on a real session)
def test_parse_chat_uses_formatted_title_and_keeps_the_phone_of_lid_chats():
    raw = {"id": "205123456789012@lid", "formattedTitle": "Maria Silva", "unreadCount": 2, "t": T,
           "contact": {"phoneNumber": "5511999990000@c.us", "pushname": "Mari", "formattedName": "Maria S."}}
    assert parse_chat(raw) == Chat("205123456789012@lid", "Maria Silva", False, 2, LOCAL(T), "5511999990000")


def test_name_falls_back_through_name_contact_fields_and_finally_the_id():
    assert parse_chat({"id": "1@lid", "name": "Fulano"}).name == "Fulano"
    assert parse_chat({"id": "1@lid", "contact": {"name": "Beltrano", "pushname": "x"}}).name == "Beltrano"
    assert parse_chat({"id": "1@lid", "contact": {"pushname": "Sicrano"}}).name == "Sicrano"
    assert parse_chat({"id": "5511@c.us"}).name == "5511"


def test_groups_are_detected_from_the_id_or_the_flag():
    assert parse_chat({"id": "120363@g.us", "formattedTitle": "Família"}).is_group is True
    assert parse_chat({"id": "1@lid", "formattedTitle": "x", "isGroup": True}).is_group is True
    assert parse_chat({"id": "1@lid", "formattedTitle": "x"}).is_group is False


def test_phone_is_only_taken_from_a_c_us_number():
    assert parse_chat({"id": "5511@c.us", "formattedTitle": "x"}).phone == "5511"           # the id itself is the number
    assert parse_chat({"id": "1@lid", "formattedTitle": "x", "contact": {"phoneNumber": "5511@c.us"}}).phone == "5511"
    assert parse_chat({"id": "1@lid", "formattedTitle": "x", "contact": {"phoneNumber": None}}).phone is None
    assert parse_chat({"id": "120363@g.us", "formattedTitle": "g"}).phone is None


@pytest.mark.parametrize("bad", [{}, {"id": ""}, {"id": None}, "text", None, 5,
                                 {"id": "867051314767696@bot", "formattedTitle": "Meta AI"},
                                 {"id": "120363@newsletter", "formattedTitle": "Canal"},
                                 {"id": "status@broadcast", "formattedTitle": "Status"}])
def test_parse_chat_rejects_unusable_or_system_chats(bad):
    assert parse_chat(bad) is None


# ----------------------------------------------------------------------------- parsing messages
def test_parse_message_text_message():
    m = parse_message(
        {"id": "false_205123@lid_ABC", "body": "oi, tudo bem?", "t": T, "from": "205123@lid", "to": "me@c.us",
         "fromMe": False, "type": "chat", "notifyName": "Maria", "chatId": "205123@lid"}
    )
    assert m == Message("false_205123@lid_ABC", "205123@lid", "Maria", "oi, tudo bem?", LOCAL(T), False, "chat")


def test_non_text_messages_never_expose_their_body():
    blob = "/9j/4AAQSkZJRgABAQ" + "A" * 5000  # base64 of an image
    img = parse_message({"id": "i", "body": blob, "t": T, "type": "image", "caption": "olha isso", "chatId": "1@lid", "from": "1@lid"})
    assert img.text == "olha isso" and img.kind == "image" and blob not in img.display() and "[image]" in img.display()
    ptt = parse_message({"id": "p", "body": blob, "t": T, "type": "ptt", "chatId": "1@lid", "from": "1@lid"})
    assert ptt.text == "" and ptt.display().endswith("[ptt]")
    call = parse_message({"id": "c", "body": "", "t": T, "type": "call_log", "chatId": "1@lid", "from": "1@lid"})
    assert call.display().endswith("[call_log]")


def test_own_messages_and_millisecond_timestamps():
    m = parse_message({"id": "true_1@lid_X", "body": "feito", "t": T * 1000, "fromMe": True, "type": "chat", "chatId": "1@lid"})
    assert m.ts == LOCAL(T) and m.from_me is True and m.sender == "eu"


def test_group_message_sender_comes_from_notify_name_or_author():
    named = parse_message({"id": "a", "body": "x", "t": T, "type": "chat", "chatId": "1@g.us", "from": "1@g.us",
                           "author": "5511@lid", "notifyName": "João"})
    assert named.sender == "João"
    anon = parse_message({"id": "b", "body": "x", "t": T, "type": "chat", "chatId": "1@g.us", "from": "1@g.us", "author": "5511@lid"})
    assert anon.sender == "5511"


def test_chat_id_falls_back_to_from_or_to():
    inbound = parse_message({"id": "a", "body": "x", "t": T, "type": "chat", "from": "5511@lid", "to": "me@c.us", "fromMe": False})
    outbound = parse_message({"id": "b", "body": "x", "t": T, "type": "chat", "from": "me@c.us", "to": "5511@lid", "fromMe": True})
    assert inbound.chat_id == "5511@lid" and outbound.chat_id == "5511@lid"


@pytest.mark.parametrize("bad", [{}, {"body": "no id"}, None, "x", {"id": "z", "t": "not-a-number", "body": "x", "type": "chat"}])
def test_parse_message_rejects_unusable_entries(bad):
    assert parse_message(bad) is None


# ----------------------------------------------------------------------------- the HTTP client
class Server:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(server, key="secret"):
    return OpenWAClient("http://127.0.0.1:8081", key, transport=httpx.MockTransport(server))


def ok(data):
    return httpx.Response(200, json={"success": True, "data": data})


async def test_status_reads_the_public_health_endpoint_without_the_key():
    server = Server(httpx.Response(200, json={"status": "ok", "connected": True, "session": {"state": "READY", "ready": True}}))
    s = await client(server).status()
    assert (s.connected, s.state) == (True, "READY")
    req = server.requests[0]
    assert req.url.path == "/health" and "x-api-key" not in req.headers


async def test_status_when_not_linked():
    server = Server(httpx.Response(200, json={"connected": False, "session": {"state": "AUTHENTICATING", "ready": False}}))
    s = await client(server).status()
    assert (s.connected, s.state) == (False, "AUTHENTICATING")


async def test_list_chats_sends_no_query_params_and_filters_unread_on_our_side():
    server = Server(ok([{"id": "1@lid", "formattedTitle": "Maria", "unreadCount": 3, "t": T},
                        {"id": "2@lid", "formattedTitle": "João", "unreadCount": 0, "t": T + 5}, {"junk": 1}]))
    chats = await client(server).list_chats(unread_only=True)
    assert [c.name for c in chats] == ["Maria"]
    req = server.requests[0]
    assert req.method == "GET" and req.url.path == "/api/chats/getAll" and dict(req.url.params) == {}
    assert req.headers["x-api-key"] == "secret"


async def test_chats_are_sorted_by_most_recent_first_and_limited():
    raw = [{"id": "a@lid", "formattedTitle": "A", "t": T}, {"id": "b@lid", "formattedTitle": "B", "t": T + 100},
           {"id": "c@lid", "formattedTitle": "C"}]
    assert [c.name for c in await client(Server(ok(raw))).list_chats()] == ["B", "A", "C"]
    assert [c.name for c in await client(Server(ok(raw))).list_chats(limit=1)] == ["B"]


async def test_get_messages_uses_only_chat_id_and_returns_the_last_n_oldest_first():
    raw = [{"id": f"m{i}", "body": f"msg {i}", "t": T + i, "type": "chat", "from": "5511@lid", "chatId": "5511@lid"} for i in (3, 1, 2)]
    server = Server(ok(raw))
    msgs = await client(server).get_messages("5511@lid", last=2)
    assert [m.text for m in msgs] == ["msg 2", "msg 3"]
    req = server.requests[0]
    assert req.url.path == "/api/messages/getAll" and dict(req.url.params) == {"chatId": "5511@lid"}


async def test_send_text_posts_the_documented_body_and_returns_the_opaque_result():
    server = Server(ok("true_5511@c.us_ABC"))
    assert await client(server).send_text("5511@c.us", "Olá!") == "true_5511@c.us_ABC"
    req = server.requests[0]
    assert req.method == "POST" and req.url.path == "/api/messages/sendText"
    assert json.loads(req.content) == {"to": "5511@c.us", "content": "Olá!", "options": {}}
    assert req.headers["x-api-key"] == "secret" and req.headers["content-type"] == "application/json"


async def test_errors_are_translated():
    with pytest.raises(WhatsAppAuthError):
        await client(Server(httpx.Response(401, json={"error": "bad key"}))).list_chats()
    with pytest.raises(WhatsAppError, match="boom"):
        await client(Server(httpx.Response(200, json={"success": False, "error": "boom"}))).list_chats()
    with pytest.raises(WhatsAppError, match="unreachable"):
        await client(Server(httpx.ConnectError("refused"))).list_chats()
    with pytest.raises(WhatsAppError, match="500"):
        await client(Server(httpx.Response(500, text="oops"))).send_text("5511@c.us", "x")
    with pytest.raises(WhatsAppError, match="Validation Error"):
        await client(Server(httpx.Response(400, json={"error": "Validation Error", "details": []}))).get_messages("1@lid")


# ----------------------------------------------------------------------------- archived / muted (used by the notifier)
def test_archived_and_muted_flags_are_read_from_the_chat():
    base = {"id": "1@lid", "formattedTitle": "x"}
    assert parse_chat(base).archived is False and parse_chat(base).muted is False
    assert parse_chat({**base, "archive": True}).archived is True
    assert parse_chat({**base, "muteExpiration": -1}).muted is True            # muted "forever"
    assert parse_chat({**base, "muteExpiration": 0}).muted is False
    future = int(__import__("time").time()) + 3600
    assert parse_chat({**base, "muteExpiration": future}).muted is True
    assert parse_chat({**base, "muteExpiration": 1000}).muted is False         # an expired mute
    assert parse_chat({**base, "muteExpiration": "oops", "archive": "yes"}).muted is False
