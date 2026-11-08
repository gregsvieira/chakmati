"""Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/). Home Assistant is the bridge to the house,
including Alexa-compatible devices, which have no public API of their own for controlling them from outside."""

import re

import httpx

from chakmati.features.home.auth import NOT_CONNECTED, HomeAuth
from chakmati.features.home.models import ALLOWED_DOMAINS, Entity, HomeError, valid_entity_id


# Home Assistant's own bit flags of a media player (MediaPlayerEntityFeature)
FEATURE_PAUSE, FEATURE_VOLUME_SET, FEATURE_PREVIOUS, FEATURE_NEXT, FEATURE_VOLUME_STEP, FEATURE_STOP, FEATURE_PLAY = 1, 4, 16, 32, 1024, 4096, 16384


class HomeAssistantClient:
    """Either a fixed address and token, or a HomeAuth (the connect flow's credentials, renewed when they expire and picked up without a restart)."""

    def __init__(self, base_url: str = "", token: str = "", transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0, auth: HomeAuth | None = None):
        self._base = base_url.rstrip("/")
        self._token = token
        self._auth = auth
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def _request(self, method: str, path: str, body: dict | None = None, raw: bool = False):
        base = (self._auth.base_url if self._auth else self._base) or ""
        if not base:
            raise HomeError(NOT_CONNECTED)
        response = await self._send(method, base, path, body, force_renew=False)
        if response.status_code == 401 and self._auth is not None and self._auth.oauth:
            response = await self._send(method, base, path, body, force_renew=True)  # the access token may just have expired: renew it once
        if response.status_code == 401:
            raise HomeError("o Home Assistant recusou o acesso: conecte de novo em Ajustes > Integrações" if self._auth is not None else "o Home Assistant recusou o token de acesso")
        if response.status_code >= 400:
            raise HomeError(f"o Home Assistant respondeu {response.status_code}: {response.text[:150]}")
        return response.text if raw else response.json()

    async def _send(self, method: str, base: str, path: str, body: dict | None, force_renew: bool) -> httpx.Response:
        token = await self._auth.bearer(self._http, force_renew=force_renew) if self._auth is not None else self._token
        try:
            return await self._http.request(method, base + path, json=body, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise HomeError(f"Home Assistant inacessível em {base}: {exc}") from exc

    async def entities(self) -> list[Entity]:
        out = []
        for item in await self._request("GET", "/api/states"):
            entity_id = str(item.get("entity_id", ""))
            if not valid_entity_id(entity_id):
                continue
            attrs = item.get("attributes") or {}
            playing = " - ".join(str(attrs[k]) for k in ("media_artist", "media_title") if attrs.get(k)) if entity_id.startswith("media_player.") else ""
            out.append(Entity(entity_id, str(attrs.get("friendly_name") or entity_id), entity_id.split(".")[0], str(item.get("state", "")),
                              str(attrs.get("device_class") or ""), str(attrs.get("unit_of_measurement") or ""), playing[:120]))
        return [e for e in out if e.domain in ALLOWED_DOMAINS]

    async def players(self) -> list[dict]:
        """The music players with what the panel shows: what is playing, the volume, and which buttons make sense for each one right now."""
        out = []
        for item in await self._request("GET", "/api/states"):
            entity_id = str(item.get("entity_id", ""))
            if not entity_id.startswith("media_player.") or not valid_entity_id(entity_id):
                continue
            a = item.get("attributes") or {}
            features = a.get("supported_features") if isinstance(a.get("supported_features"), int) else 0
            level = a.get("volume_level")
            out.append({
                "id": entity_id, "name": str(a.get("friendly_name") or entity_id), "state": str(item.get("state", "")),
                "title": str(a.get("media_title") or "")[:120], "artist": str(a.get("media_artist") or "")[:120], "album": str(a.get("media_album_name") or "")[:120],
                "volume": round(level * 100) if isinstance(level, (int, float)) and not isinstance(level, bool) else None,
                "can": {"pause": bool(features & FEATURE_PAUSE), "play": bool(features & FEATURE_PLAY), "next": bool(features & FEATURE_NEXT), "previous": bool(features & FEATURE_PREVIOUS),
                        "volume": bool(features & (FEATURE_VOLUME_SET | FEATURE_VOLUME_STEP)), "stop": bool(features & FEATURE_STOP)},
            })
        return out

    async def send_text_command(self, entity_id: str, text: str) -> None:
        """Says `text` to an Echo as if it had been spoken to it ("toque Raul Seixas"): Alexa picks the music service itself. The action takes the device's
        id in Home Assistant, not the entity's, which a template gives."""
        if not valid_entity_id(entity_id) or not entity_id.startswith("media_player."):
            raise HomeError("aparelho não permitido")
        device = (await self._request("POST", "/api/template", {"template": "{{ device_id('" + entity_id + "') }}"}, raw=True)).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", device):
            raise HomeError("não achei esse aparelho da Alexa no Home Assistant")
        await self._request("POST", "/api/services/alexa_devices/send_text_command", {"device_id": device, "text_command": text})

    async def call(self, domain: str, service: str, data: dict) -> None:
        if domain not in ALLOWED_DOMAINS or not service.replace("_", "").isalpha():
            raise HomeError("chamada não permitida")
        await self._request("POST", f"/api/services/{domain}/{service}", data)

    async def aclose(self) -> None:
        await self._http.aclose()
