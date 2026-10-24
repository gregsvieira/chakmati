import httpx
import pytest

from liteagent.approvals import ActionStore
from liteagent.whatsapp.openwa import OpenWAClient, WhatsAppError
from liteagent.whatsapp.service import RateLimited, WhatsAppService


class FakeProvider:
    def __init__(self):
        self.texts, self.voices = [], []

    async def send_text(self, chat_id, text):
        self.texts.append((chat_id, text))
        return f"text-{len(self.texts)}"

    async def send_voice(self, chat_id, audio, mime):
        self.voices.append((chat_id, audio, mime))
        return f"voice-{len(self.voices)}"


def make(max_per_hour=20, gap=3.0):
    clock = [1000.0]
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    actions = ActionStore(":memory:")
    service = WhatsAppService(FakeProvider(), actions, max_sends_per_hour=max_per_hour, min_interval=gap, now=lambda: clock[0], sleep=sleep)
    return service, actions, clock, slept


async def test_an_automated_text_is_sent_and_written_to_the_audit_trail():
    service, actions, _, _ = make()
    result = await service.send_automated("111@lid", "Maria", text="Estou ocupado", source="automation:abc")
    assert result == "text-1" and service._provider.texts == [("111@lid", "Estou ocupado")]
    row = actions._db.execute("SELECT kind, status, summary, payload FROM actions").fetchone()
    assert row["kind"] == "whatsapp.auto" and row["status"] == "executed"
    assert "Maria" in row["summary"] and "automation:abc" in row["payload"]
    assert actions.pending(2000.0) == []  # the audit row is never an open proposal


async def test_an_automated_voice_note_is_sent_as_audio():
    service, _, _, _ = make()
    assert await service.send_automated("111@lid", "Maria", audio=b"OggS-data", mime="audio/ogg") == "voice-1"
    assert service._provider.voices == [("111@lid", b"OggS-data", "audio/ogg")]


async def test_automated_sends_share_the_hourly_limit_and_keep_a_gap():
    service, _, clock, slept = make(max_per_hour=2, gap=3.0)
    await service.send_automated("1@lid", "A", text="oi")
    await service.send_automated("2@lid", "B", text="oi")
    assert slept and slept[0] > 0  # the second one waited for the gap
    with pytest.raises(RateLimited):
        await service.send_automated("3@lid", "C", text="oi")
    clock[0] += 3601
    assert await service.send_automated("3@lid", "C", text="oi")  # an hour later it is allowed again


async def test_bad_recipients_text_or_audio_are_refused_before_anything_is_sent():
    service, _, _, _ = make()
    with pytest.raises(ValueError):
        await service.send_automated("not an id", "x", text="oi")
    with pytest.raises(ValueError):
        await service.send_automated("1@lid", "x", text="bom\x00dia")
    with pytest.raises(ValueError):
        await service.send_automated("1@lid", "x")  # neither text nor audio
    with pytest.raises(ValueError):
        await service.send_automated("1@lid", "x", audio=b"x" * (6 * 1024 * 1024), mime="audio/ogg")
    with pytest.raises(ValueError):
        await service.send_automated("1@lid", "x", audio=b"abc", mime="text/html")
    assert service._provider.texts == [] and service._provider.voices == []


# ----------------------------------------------------------------------------- OpenWA's voice-note call
async def test_send_voice_posts_a_data_url_to_send_ptt():
    seen = {}

    def server(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"], seen["key"] = str(request.url), request.read(), request.headers.get("x-api-key")
        return httpx.Response(200, json={"success": True, "data": "true_111@lid_VOICE"})

    client = OpenWAClient("http://127.0.0.1:8081", "secret", transport=httpx.MockTransport(server))
    assert await client.send_voice("111@lid", b"OggS-bytes", "audio/ogg") == "true_111@lid_VOICE"
    import base64, json

    body = json.loads(seen["body"])
    assert seen["url"].endswith("/api/messages/sendPtt") and seen["key"] == "secret"
    assert body["to"] == "111@lid" and body["file"] == "data:audio/ogg;base64," + base64.b64encode(b"OggS-bytes").decode()


async def test_send_voice_validates_the_recipient():
    client = OpenWAClient("http://127.0.0.1:8081", "secret", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"success": True, "data": "x"})))
    with pytest.raises(ValueError):
        await client.send_voice("nope", b"x", "audio/ogg")
