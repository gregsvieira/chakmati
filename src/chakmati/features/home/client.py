"""Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/). Home Assistant is the bridge to the house,
including Alexa-compatible devices, which have no public API of their own for controlling them from outside."""

import httpx

from chakmati.features.home.auth import NOT_CONNECTED, HomeAuth
from chakmati.features.home.models import ALLOWED_DOMAINS, Entity, HomeError, valid_entity_id


class HomeAssistantClient:
    """Either a fixed address and token, or a HomeAuth (the connect flow's credentials, renewed when they expire and picked up without a restart)."""

    def __init__(self, base_url: str = "", token: str = "", transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0, auth: HomeAuth | None = None):
        self._base = base_url.rstrip("/")
        self._token = token
        self._auth = auth
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def _request(self, method: str, path: str, body: dict | None = None):
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
        return response.json()

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

    async def call(self, domain: str, service: str, data: dict) -> None:
        if domain not in ALLOWED_DOMAINS or not service.replace("_", "").isalpha():
            raise HomeError("chamada não permitida")
        await self._request("POST", f"/api/services/{domain}/{service}", data)

    async def aclose(self) -> None:
        await self._http.aclose()
