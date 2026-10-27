import asyncio

import httpx
import pytest

from chakmati.shared.notices import NoticeBoard
from chakmati.features.whatsapp.events import WhatsAppEvents, parse_sse_lines


def _ev(event, payload=None, ts_ms=2_000_000):
    return {"id": "1", "event": event, "payload": payload or {}, "ts": ts_ms}


def make(now=2_000.0):
    board = NoticeBoard(now=lambda: now)
    return WhatsAppEvents("http://x", "key", board, now=lambda: now), board


def test_parse_sse_lines_yields_named_json_events_and_skips_noise():
    lines = [
        "retry: 3000", "", ":keepalive", "",
        "id: 5", "event: session.state.changed", 'data: {"event":"session.state.changed","payload":{"nextState":"READY"}}', "",
        "event: broken", "data: {not json", "",
        "data: no event name", "",
    ]
    out = list(parse_sse_lines(lines))
    assert out == [("session.state.changed", {"event": "session.state.changed", "payload": {"nextState": "READY"}})]


def test_disconnect_and_reconnect_become_notices_once_each():
    ev, board = make()
    ev.handle(_ev("session.state.changed", {"nextState": "DISCONNECTED"}))
    ev.handle(_ev("session.state.changed", {"nextState": "DISCONNECTED"}))  # repeated: ignored
    ev.handle(_ev("session.state.changed", {"nextState": "READY"}))
    texts = [n.text for n in board.since(0)]
    assert texts == ["O WhatsApp foi desconectado.", "O WhatsApp está conectado."]
    assert {n.kind for n in board.since(0)} == {"system"}


def test_intermediate_states_are_silent():
    ev, board = make()
    for state in ("STARTING", "AUTHENTICATING", "OPENING"):
        ev.handle(_ev("session.state.changed", {"nextState": state}))
    assert board.since(0) == []


def test_qr_request_asks_for_a_scan_and_keeps_the_latest_qr_for_the_app():
    ev, board = make()
    ev.handle(_ev("launch.auth.qr.requested"))
    ev.handle(_ev("launch.auth.qr.generated", {"qr": "2@abc"}))
    ev.handle(_ev("launch.auth.qr.generated", {"qr": "2@def"}))
    assert [n.text for n in board.since(0)] == ["O WhatsApp pede para escanear o QR no OpenWA."]  # one notice, not one per QR
    assert ev.qr == "2@def"
    ev.handle(_ev("launch.auth.qr.scanned"))
    assert ev.qr is None


def test_qr_given_as_plain_string_payload():
    ev, _ = make()
    ev.handle(_ev("launch.auth.qr.generated", "2@plain"))
    assert ev.qr == "2@plain"


def test_auth_timeout_tells_the_person_to_reconnect():
    ev, board = make()
    ev.handle(_ev("launch.auth.timeout"))
    assert [n.text for n in board.since(0)] == ["O OpenWA parou de esperar o login. Conecte de novo pelo Ajustes."]


def test_history_replayed_on_connect_is_ignored():
    ev, board = make(now=2_000.0)  # events older than ~10 s before now are history
    ev.handle(_ev("session.state.changed", {"nextState": "DISCONNECTED"}, ts_ms=1_000_000))
    assert board.since(0) == []
    ev.handle(_ev("session.state.changed", {"nextState": "DISCONNECTED"}, ts_ms=1_995_000))
    assert len(board.since(0)) == 1


def test_masked_text_has_no_extra_details():
    ev, board = make()
    ev.handle(_ev("session.state.changed", {"nextState": "DISCONNECTED"}))
    n = board.since(0)[0]
    assert n.masked == n.text


@pytest.mark.asyncio
async def test_run_streams_from_the_events_url_with_the_key_and_stops_on_cancel():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["accept"] = request.headers.get("accept")
        body = 'event: session.state.changed\ndata: {"event":"session.state.changed","payload":{"nextState":"DISCONNECTED"},"ts":2000000}\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    board = NoticeBoard()
    ev = WhatsAppEvents("http://owa", "k3y", board, now=lambda: 2_000.0, retry_seconds=0.01,
                        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    task = asyncio.create_task(ev.run())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if board.since(0):
            break
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert seen["url"].startswith("http://owa/api/events?") and "topics=%2A" in seen["url"] and "api_key=k3y" in seen["url"]
    assert seen["accept"] == "text/event-stream"
    assert board.since(0)[0].text == "O WhatsApp foi desconectado."
