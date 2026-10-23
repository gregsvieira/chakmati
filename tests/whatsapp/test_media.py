import base64
import hashlib
import hmac
import os

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from liteagent.whatsapp.media import MAX_AUDIO_BYTES, MediaError, check_media_url, decrypt_audio, fetch_audio
from liteagent.whatsapp.models import MediaRef
from liteagent.whatsapp.openwa import parse_message


def _hkdf(ikm: bytes, info: bytes, n: int) -> bytes:
    prk = hmac.new(b"\x00" * 32, ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:n]


def encrypt_audio(plain: bytes, key: bytes) -> bytes:
    """The WhatsApp media scheme, written independently of the code under test."""
    k = _hkdf(key, b"WhatsApp Audio Keys", 112)
    iv, cipher_key, mac_key = k[:16], k[16:48], k[48:80]
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(cipher_key), modes.CBC(iv)).encryptor()
    ct = enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()
    return ct + hmac.new(mac_key, iv + ct, hashlib.sha256).digest()[:10]


KEY = os.urandom(32)
PLAIN = b"OggS" + os.urandom(300)


def test_decrypt_round_trip():
    assert decrypt_audio(encrypt_audio(PLAIN, KEY), base64.b64encode(KEY).decode()) == PLAIN


def test_tampered_audio_is_rejected_by_the_mac():
    blob = bytearray(encrypt_audio(PLAIN, KEY))
    blob[20] ^= 0xFF
    with pytest.raises(MediaError, match="authentic"):
        decrypt_audio(bytes(blob), base64.b64encode(KEY).decode())


def test_wrong_key_and_garbage_are_rejected():
    with pytest.raises(MediaError):
        decrypt_audio(encrypt_audio(PLAIN, KEY), base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(MediaError):
        decrypt_audio(b"short", base64.b64encode(KEY).decode())
    with pytest.raises(MediaError):
        decrypt_audio(encrypt_audio(PLAIN, KEY), "not base64 !!!")


@pytest.mark.parametrize("url", [
    "https://mmg.whatsapp.net/v/t62.7117-24/abc?x=1",
    "https://media-gru1-1.cdn.whatsapp.net/v/abc",
])
def test_only_whatsapp_cdn_https_urls_are_allowed(url):
    check_media_url(url)


@pytest.mark.parametrize("url", [
    "http://mmg.whatsapp.net/x",            # not https
    "https://evil.example.com/x",            # not whatsapp
    "https://whatsapp.net.evil.com/x",       # suffix trick
    "https://user:pw@mmg.whatsapp.net/x",    # credentials
    "https://127.0.0.1/x",                   # local address
    "file:///etc/passwd",
    "",
])
def test_other_urls_are_refused(url):
    with pytest.raises(MediaError):
        check_media_url(url)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_audio_downloads_checks_the_hash_and_decrypts():
    blob = encrypt_audio(PLAIN, KEY)
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("x-api-key")
        return httpx.Response(200, content=blob)

    ref = MediaRef("https://mmg.whatsapp.net/v/x", base64.b64encode(KEY).decode(),
                   base64.b64encode(hashlib.sha256(blob).digest()).decode(), "audio/ogg; codecs=opus")
    async with _client(handler) as client:
        audio, mime = await fetch_audio(ref, client)
    assert audio == PLAIN and mime == "audio/ogg"
    assert seen["auth"] is None  # the OpenWA key must never reach the CDN


@pytest.mark.asyncio
async def test_fetch_audio_refuses_wrong_hash_oversize_and_failed_downloads():
    blob = encrypt_audio(PLAIN, KEY)
    key = base64.b64encode(KEY).decode()
    async with _client(lambda r: httpx.Response(200, content=blob)) as client:
        with pytest.raises(MediaError, match="hash"):
            await fetch_audio(MediaRef("https://mmg.whatsapp.net/x", key, base64.b64encode(b"x" * 32).decode(), "audio/ogg"), client)
    async with _client(lambda r: httpx.Response(404)) as client:
        with pytest.raises(MediaError, match="404"):
            await fetch_audio(MediaRef("https://mmg.whatsapp.net/x", key, None, "audio/ogg"), client)
    async with _client(lambda r: httpx.Response(200, content=b"x" * (MAX_AUDIO_BYTES + 100))) as client:
        with pytest.raises(MediaError, match="large"):
            await fetch_audio(MediaRef("https://mmg.whatsapp.net/x", key, None, "audio/ogg"), client)
    async with _client(lambda r: httpx.Response(200, content=blob)) as client:
        with pytest.raises(MediaError, match="audio"):
            await fetch_audio(MediaRef("https://mmg.whatsapp.net/x", key, None, "text/html"), client)


def test_parse_message_keeps_what_is_needed_to_play_a_voice_note():
    m = parse_message({
        "id": "false_1@lid_AB", "t": 1792792330, "type": "ptt", "body": "AAAAbase64blob", "chatId": "1@lid", "from": "1@lid",
        "mimetype": "audio/ogg; codecs=opus", "duration": "25", "clientUrl": "https://mmg.whatsapp.net/v/x",
        "mediaKey": "KEY=", "encFilehash": "HASH=",
    })
    assert m.kind == "ptt" and m.text == "" and m.duration == 25
    assert m.media == MediaRef("https://mmg.whatsapp.net/v/x", "KEY=", "HASH=", "audio/ogg; codecs=opus")


def test_parse_message_without_media_details_has_no_media_and_text_messages_none():
    assert parse_message({"id": "a", "t": 1792792330, "type": "ptt", "chatId": "1@lid", "from": "1@lid"}).media is None
    assert parse_message({"id": "a", "t": 1792792330, "type": "chat", "body": "oi", "chatId": "1@lid", "from": "1@lid"}).media is None
