import base64
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from chakmati.whatsapp.openwa import OpenWAClient, WhatsAppError
from chakmati.whatsapp.webvoice import SCRIPT, WebVoiceSender


class Runner:
    def __init__(self, code=0, out=b'{"ok": true, "id": "true_111@lid_ABC"}'):
        self.code, self.out, self.calls = code, out, []

    async def __call__(self, argv, stdin):
        self.calls.append((argv, stdin))
        return self.code, self.out


def home(tmp_path, with_port=True):
    if with_port:
        port = tmp_path / "run" / "_IGNORE_lite-agent" / "DevToolsActivePort"
        port.parent.mkdir(parents=True)
        port.write_text("1234\n/devtools/browser/x")
    return str(tmp_path)


async def test_send_passes_the_audio_and_chat_to_the_node_script(tmp_path):
    runner = Runner()
    sender = WebVoiceSender(home(tmp_path), node="node", run=runner)
    assert await sender.send("111@lid", b"OggS-bytes", "audio/ogg") == "true_111@lid_ABC"
    argv, stdin = runner.calls[0]
    assert argv[0] == "node" and argv[1].endswith("wa_voice.js") and argv[2:] == [str(tmp_path), "send"]
    body = json.loads(stdin)
    assert body["chatId"] == "111@lid" and base64.b64decode(body["b64"]) == b"OggS-bytes"


async def test_failures_say_why_and_bad_input_never_reaches_the_script(tmp_path):
    runner = Runner(1, b'{"ok": false, "error": "chat not found"}')
    sender = WebVoiceSender(home(tmp_path), node="node", run=runner)
    with pytest.raises(WhatsAppError, match="chat not found"):
        await sender.send("111@lid", b"x", "audio/ogg")
    with pytest.raises(WhatsAppError):
        await WebVoiceSender(home(tmp_path / "b"), node="node", run=Runner(0, b"garbage")).send("111@lid", b"x", "audio/ogg")
    runner.calls.clear()
    for chat, mime in [("not an id", "audio/ogg"), ("111@lid", "text/html")]:
        with pytest.raises(ValueError):
            await sender.send(chat, b"x", mime)
    assert runner.calls == []


async def test_available_needs_the_browser_and_a_ready_page(tmp_path):
    assert await WebVoiceSender(home(tmp_path / "a", with_port=False), node="node", run=Runner()).available() is None
    assert await WebVoiceSender(home(tmp_path / "b"), node="node", run=Runner(0, b'{"ok": true}')).available() is True
    assert await WebVoiceSender(home(tmp_path / "c"), node="node", run=Runner(1, b'{"ok": false, "error": "not ready"}')).available() is None


async def test_the_openwa_client_prefers_the_page_over_its_missing_file_sending(tmp_path):
    runner = Runner()
    sender = WebVoiceSender(home(tmp_path), node="node", run=runner)
    unreachable = httpx.MockTransport(lambda r: pytest.fail("OpenWA's own HTTP file sending must not be used"))
    client = OpenWAClient("http://127.0.0.1:8081", "k", transport=unreachable, voice=sender)
    assert await client.send_voice("111@lid", b"OggS", "audio/ogg") == "true_111@lid_ABC"
    assert await client.supports_media() is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_is_valid_javascript_and_refuses_to_run_without_a_browser(tmp_path):
    assert subprocess.run(["node", "--check", str(SCRIPT)]).returncode == 0
    result = subprocess.run(["node", str(SCRIPT), str(tmp_path), "check"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and json.loads(result.stdout)["ok"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
async def test_a_large_payload_reaches_the_script_through_a_real_pipe(tmp_path):
    # regression: reading stdin with readFileSync(0) failed with EAGAIN on the engine's pipe ("voice note not sent: EAGAIN")
    from chakmati.whatsapp.webvoice import _run

    body = json.dumps({"chatId": "111@lid", "b64": "A" * 1_500_000}).encode()
    code, out = await _run(["node", str(SCRIPT), str(tmp_path), "echo"], body)
    assert code == 0 and json.loads(out) == {"ok": True, "length": len(body)}
