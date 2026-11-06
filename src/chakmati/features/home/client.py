"""Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/). Home Assistant is the bridge to the house,
including Alexa-compatible devices, which have no public API of their own for controlling them from outside."""

import httpx

from chakmati.features.home.models import ALLOWED_DOMAINS, Entity, HomeError, valid_entity_id


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout, headers={"Authorization": f"Bearer {token}"})

    async def _request(self, method: str, path: str, body: dict | None = None):
        try:
            response = await self._http.request(method, self._base + path, json=body)
        except httpx.HTTPError as exc:
            raise HomeError(f"Home Assistant inacessível em {self._base}: {exc}") from exc
        if response.status_code == 401:
            raise HomeError("o Home Assistant recusou o token de acesso")
        if response.status_code >= 400:
            raise HomeError(f"o Home Assistant respondeu {response.status_code}: {response.text[:150]}")
        return response.json()

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
