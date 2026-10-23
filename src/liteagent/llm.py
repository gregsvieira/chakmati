from typing import Protocol

import httpx


class ChatClient(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> str: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        think: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 300.0,
    ):
        self._model = model
        self._think = think
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        response = await self._http.post(
            "/api/chat",
            json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "think": self._think,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    async def aclose(self) -> None:
        await self._http.aclose()
