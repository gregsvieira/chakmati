"""The first-run questions of a new Home Assistant (who owns it, where it is, whether to send statistics), answered for the person.

A brand-new Home Assistant shows a wizard in the browser before anything works. The Chakmati asks the person for a name and a password
once, creates the owner with them through Home Assistant's own onboarding API, finishes the other steps with the plain defaults (no statistics
are sent) and keeps the tokens it gets, so there is no sign-in to approve afterwards. The password is used for that one request and kept nowhere."""

import httpx

from chakmati.features.home.models import HomeError

MIN_PASSWORD = 8
USERNAME = "chakmati"


async def open_steps(http: httpx.AsyncClient, base: str) -> list[str]:
    """The onboarding steps still to do; empty when the Home Assistant already has an owner."""
    try:
        response = await http.get(f"{base}/api/onboarding", timeout=10.0)
    except httpx.HTTPError as exc:
        raise HomeError(f"não consegui falar com o Home Assistant em {base}: {exc}") from exc
    if response.status_code == 404:
        return []   # no onboarding at all: it was finished long ago
    data = response.json() if response.status_code == 200 else None
    if not isinstance(data, list):
        raise HomeError("o Home Assistant respondeu de um jeito que eu não conheço")
    return [str(s.get("step")) for s in data if isinstance(s, dict) and not s.get("done")]


async def create_owner(http: httpx.AsyncClient, base: str, client_id: str, name: str, password: str) -> dict:
    """Creates the owner and finishes the onboarding. Returns {"access_token", "refresh_token", "expires_in"}."""
    if len(password) < MIN_PASSWORD:
        raise HomeError(f"escolha uma senha com pelo menos {MIN_PASSWORD} caracteres")
    if "user" not in await open_steps(http, base):
        raise HomeError("este Home Assistant já tem um dono: use Conectar ao Home Assistant e entre com a sua conta")
    try:
        made = await http.post(f"{base}/api/onboarding/users", json={"client_id": client_id, "name": name.strip() or "Chakmati", "username": USERNAME, "password": password, "language": "pt-BR"})
        code = made.json().get("auth_code") if made.status_code == 200 else None
        if not code:
            raise HomeError("o Home Assistant não aceitou criar a conta")
        issued = await http.post(f"{base}/auth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id})
        tokens = issued.json() if issued.status_code == 200 else {}
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            raise HomeError("o Home Assistant não entregou o acesso")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        for step, body in (("core_config", {}), ("analytics", {}), ("integration", {"client_id": client_id, "redirect_uri": client_id + "home/callback"})):
            await http.post(f"{base}/api/onboarding/{step}", json=body, headers=headers)   # the plain defaults; a step already done is not an error
    except httpx.HTTPError as exc:
        raise HomeError(f"o Home Assistant parou de responder: {exc}") from exc
    return tokens
