"""Voice notes: download the encrypted file from WhatsApp's CDN and decrypt it here.

OpenWA's own /api/media/decrypt failed on real voice notes ("wrong final block length"), so the standard WhatsApp media
scheme is done locally: HKDF-SHA256 of the media key (info "WhatsApp Audio Keys") gives the IV, the AES-256-CBC key and
the MAC key; the file is ciphertext + a 10-byte HMAC-SHA256 tag. Everything that arrives is untrusted: the URL must be an
https WhatsApp CDN host, the size is capped, and the file hash and the MAC are verified before anything is returned.
Nothing here ever sends the OpenWA API key to the CDN.
"""

import base64
import binascii
import hashlib
import hmac
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from chakmati.whatsapp.models import MediaRef

MAX_AUDIO_BYTES = 16 * 1024 * 1024
_MAC_BYTES = 10


class MediaError(Exception):
    pass


def check_media_url(url: str) -> None:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise MediaError("media URL must be plain https")
    if not (host == "whatsapp.net" or host.endswith(".whatsapp.net")):
        raise MediaError("media URL is not a WhatsApp CDN address")


def _hkdf(ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(b"\x00" * 32, ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def decrypt_audio(blob: bytes, key_b64: str) -> bytes:
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (binascii.Error, ValueError):
        raise MediaError("media key is not valid base64") from None
    if len(key) != 32 or len(blob) <= _MAC_BYTES + 16:
        raise MediaError("media key or file has the wrong size")
    keys = _hkdf(key, b"WhatsApp Audio Keys", 112)
    iv, cipher_key, mac_key = keys[:16], keys[16:48], keys[48:80]
    data, tag = blob[:-_MAC_BYTES], blob[-_MAC_BYTES:]
    if not hmac.compare_digest(hmac.new(mac_key, iv + data, hashlib.sha256).digest()[:_MAC_BYTES], tag):
        raise MediaError("audio is not authentic (MAC mismatch)")
    if len(data) % 16:
        raise MediaError("audio has the wrong size")
    try:
        plain = Cipher(algorithms.AES(cipher_key), modes.CBC(iv)).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        padded = plain.update(data) + plain.finalize()
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        raise MediaError("audio could not be decrypted") from None


async def fetch_audio(ref: MediaRef, client: httpx.AsyncClient) -> tuple[bytes, str]:
    """(decrypted audio bytes, mime type without parameters)."""
    mime = ref.mime.split(";")[0].strip().lower()
    if not mime.startswith("audio/"):
        raise MediaError("this is not an audio file")
    check_media_url(ref.url)
    try:
        async with client.stream("GET", ref.url, headers={"User-Agent": "Mozilla/5.0"}) as response:
            if response.status_code != 200:
                raise MediaError(f"WhatsApp CDN answered {response.status_code}")
            blob = b""
            async for chunk in response.aiter_bytes():
                blob += chunk
                if len(blob) > MAX_AUDIO_BYTES:
                    raise MediaError("audio is too large")
    except httpx.HTTPError as exc:
        raise MediaError(f"could not download the audio: {exc}") from None
    if ref.enc_hash and base64.b64encode(hashlib.sha256(blob).digest()).decode() != ref.enc_hash:
        raise MediaError("downloaded file does not match its hash")
    return decrypt_audio(blob, ref.key), mime
