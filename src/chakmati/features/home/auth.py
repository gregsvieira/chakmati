"""How the Chakmati proves who it is to Home Assistant, and where Home Assistant is.

Two shapes of credentials, so nothing that worked before breaks:
  * the connect flow (Ajustes > Integrações) writes a small JSON file with the address, a refresh token and the current access token. The access
    token lives 30 minutes, so it is renewed here whenever it is about to expire; the person never copies a token.
  * the older way: a long-lived token pasted into a text file (CHAKMATI_HOME_TOKEN_FILE) and the address in CHAKMATI_HOME_URL.
The file is read each time it changes, so connecting works at once, with no restart of the engine."""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from chakmati.features.home.models import HomeError

NOT_CONNECTED = "o Home Assistant ainda não está conectado: conecte em Ajustes > Integrações"
RENEW_BEFORE_SECONDS = 60.0


class HomeAuth:
    def __init__(self, oauth_file: str, legacy_token_file: str = "", legacy_url: str = "", clock=time.time):
        self._file = Path(oauth_file)
        self._legacy_token_file = legacy_token_file
        self._legacy_url = legacy_url.rstrip("/")
        self._clock = clock
        self._lock = asyncio.Lock()

    # --- what is stored ------------------------------------------------------------------------------------------------------------
    def _oauth(self) -> dict | None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("url") and data.get("refresh_token") else None

    def _legacy(self) -> dict | None:
        try:
            token = Path(self._legacy_token_file).read_text(encoding="utf-8").strip() if self._legacy_token_file else ""
        except OSError:
            token = ""
        return {"url": self._legacy_url, "token": token} if token and self._legacy_url else None

    @property
    def configured(self) -> bool:
        return self._oauth() is not None or self._legacy() is not None

    @property
    def oauth(self) -> bool:
        return self._oauth() is not None

    @property
    def base_url(self) -> str | None:
        creds = self._oauth() or self._legacy()
        return creds["url"].rstrip("/") if creds else None

    def save(self, url: str, access_token: str, refresh_token: str, expires_in: float, client_id: str) -> None:
        """Writes the credentials for the next requests (only the person's own user can read the file)."""
        data = {"url": url.rstrip("/"), "client_id": client_id, "access_token": access_token, "refresh_token": refresh_token,
                "expires_at": self._clock() + float(expires_in)}
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_name(self._file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self._file)

    def forget(self) -> None:
        """Disconnects: the connect flow's credentials are deleted (a token pasted by hand is not touched)."""
        self._file.unlink(missing_ok=True)

    # --- using it --------------------------------------------------------------------------------------------------------------------
    async def bearer(self, http: httpx.AsyncClient, force_renew: bool = False) -> str:
        async with self._lock:
            creds = self._oauth()
            if creds is None:
                legacy = self._legacy()
                if legacy is None:
                    raise HomeError(NOT_CONNECTED)
                return legacy["token"]
            if not force_renew and self._clock() < float(creds.get("expires_at", 0)) - RENEW_BEFORE_SECONDS and creds.get("access_token"):
                return creds["access_token"]
            return await self._renew(http, creds)

    async def _renew(self, http: httpx.AsyncClient, creds: dict) -> str:
        try:
            response = await http.post(f"{creds['url'].rstrip('/')}/auth/token", data={
                "grant_type": "refresh_token", "refresh_token": creds["refresh_token"], "client_id": creds.get("client_id", "")})
        except httpx.HTTPError as exc:
            raise HomeError(f"Home Assistant inacessível em {creds['url']}: {exc}") from exc
        if response.status_code >= 400:
            raise HomeError("o acesso ao Home Assistant expirou ou foi cancelado: conecte de novo em Ajustes > Integrações")
        data = response.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise HomeError("o Home Assistant não devolveu um acesso novo: conecte de novo")
        self.save(creds["url"], token, str(data.get("refresh_token") or creds["refresh_token"]), data.get("expires_in", 1800), creds.get("client_id", ""))
        return token
