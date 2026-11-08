"""Controlling the house. Ordinary things (lights, plugs, scenes, thermostat, closing a blind) happen right away and are
reported; anything that opens the house (unlocking, opening a garage / door / gate) is only PROPOSED and waits for the
person's approval like any other risky action. Calls are rate limited."""

import time
from collections import deque
from collections.abc import Callable

from chakmati.shared.approvals import Action, ActionStore, ApprovalService
from chakmati.features.home.models import Command, Entity, HomeError, plan, plain


MAX_QUERY = 100


def music_request(query: str) -> str:
    """The sentence said to the Echo for a search: always "toque ...", never anything else, one line, short. HomeError when there is nothing to ask for."""
    text = " ".join("".join(c for c in str(query) if c.isprintable()).split())[:MAX_QUERY].strip(" ,.;:!?")
    if not text:
        raise HomeError("diga o que tocar, por exemplo \"Raul Seixas\"")
    return f"toque {text}"


class HomeService(ApprovalService):
    prefix = "home."
    cancel_text = "Certo, não fiz nada na casa."
    MAX_CALLS_PER_MINUTE = 30

    def __init__(self, client, actions: ActionStore, ttl_seconds: float = 300.0, now: Callable[[], float] = time.time):
        super().__init__(actions, ttl_seconds, now)
        self._client = client
        self._calls: deque[float] = deque()

    async def entities(self) -> list[Entity]:
        return await self._client.entities()

    def find(self, entities: list[Entity], query: str) -> tuple[Entity | None, list[Entity]]:
        """The device the words point at: (match, []) when clear, (None, candidates) when several fit, (None, []) when none."""
        words = set(plain(query).split()) - {"a", "o", "as", "os", "da", "do", "das", "dos", "de", "na", "no", "luz", "luzes"} or set(plain(query).split())
        scored = []
        for e in entities:
            name = set(plain(e.name).split())
            score = len(words & name)
            if score and words <= name | {"luz", "luzes"}:
                scored.append((score + (1 if plain(e.name) == plain(query) else 0), e))
            elif score:
                scored.append((score - 0.5, e))
        if not scored:
            return None, []
        scored.sort(key=lambda p: -p[0])
        best = [e for s, e in scored if s == scored[0][0]]
        return (best[0], []) if len(best) == 1 else (None, best[:5])

    @staticmethod
    def default_player(entities: list[Entity]) -> tuple[Entity | None, list[Entity]]:
        """The music player a request without a device means: the only one playing, or the only one there is. (None, candidates) when it is not clear."""
        players = [e for e in entities if e.domain == "media_player"]
        playing = [e for e in players if e.state == "playing"]
        if len(playing) == 1:
            return playing[0], []
        if not playing and len(players) == 1:
            return players[0], []
        return None, (playing or players)[:5]

    def _rate(self) -> None:
        cutoff = self._now() - 60
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        if len(self._calls) >= self.MAX_CALLS_PER_MINUTE:
            raise HomeError("muitos comandos seguidos para a casa; espere um minuto")
        self._calls.append(self._now())

    async def _run(self, command: Command) -> None:
        self._rate()
        await self._client.call(command.domain, command.service, command.data)

    async def do(self, action: str, entity: Entity, value=None) -> tuple[str, Action | None]:
        """(text for the person, the pending proposal if approval is needed)."""
        command = plan(action, entity, value)
        if command.sensitive:
            proposal = self._propose("home.call", f"{command.text} (isso abre a casa)", {"entity": entity.id, "domain": command.domain, "service": command.service, "data": command.data, "text": command.text})
            return command.text, proposal
        await self._run(command)
        return command.text, None

    async def run_step(self, step: dict) -> str:
        """One step of an automation (already validated when it was created, and checked again here): a device command or a music request. Nothing that opens the
        house ever runs this way: it needs the person's approval at that moment. -> what was done, in words."""
        entity = step["entity"]
        target = Entity(entity["id"], entity["name"], entity["id"].split(".")[0], "", entity.get("device_class", ""))
        if step["kind"] == "music":
            return await self.play_search(target, step["query"])
        command = plan(step["action"], target, step.get("value"))
        if command.sensitive:
            raise HomeError(f"\"{command.text}\" abre a casa e precisa da sua aprovação: não roda sozinho")
        await self._run(command)
        return command.text

    async def play_search(self, entity: Entity, query: str) -> str:
        """Asks the Echo for music by saying it the request: "toque <query>". The text is only ever a music request: it always starts with "toque"."""
        phrase = music_request(query)
        self._rate()
        await self._client.send_text_command(entity.id, phrase)
        return f"Pedi à {entity.name}: {phrase}"

    def pending_confirmation(self) -> Action | None:
        waiting = self.pending()
        return waiting[-1] if waiting else None

    async def _aexecute(self, action: Action) -> str:
        p = action.payload
        from chakmati.features.home.models import valid_entity_id

        if action.kind != "home.call" or not valid_entity_id(p.get("entity", "")) or p.get("data", {}).get("entity_id") != p["entity"]:
            raise HomeError("pedido inválido")
        self._rate()
        await self._client.call(p["domain"], p["service"], p["data"])
        return f"Feito: {p['text']}."
