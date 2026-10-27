"""Creating an automation is an approved action like any other: the assistant only PROPOSES it, and nothing exists (or
runs) until the person confirms, in the app or by saying yes. For a voice reply the recording is made at proposal time, so the
person can listen to it before confirming, and the very same file is what gets sent later.
"""

import time
from collections.abc import Callable
from pathlib import Path

from chakmati.approvals import Action, ActionStore, ApprovalService
from chakmati.tts import VoiceError
from chakmati.automations.audio import wav_to_ogg_opus
from chakmati.automations.models import Spec, describe, parse_spec
from chakmati.automations.store import AutomationStore


class AutomationError(Exception):
    pass


class AutomationService(ApprovalService):
    prefix = "automation."
    MAX_AUTOMATIONS = 20

    def __init__(self, store: AutomationStore, actions: ActionStore, voice, voice_dir: str | Path,
                 ttl_seconds: float = 3600.0, now: Callable[[], float] = time.time, media_check=None):
        super().__init__(actions, ttl_seconds, now)
        self._store = store
        self.store = store
        self._voice = voice  # a VoiceSynth, or None when the enhanced voice does not exist
        self._dir = Path(voice_dir)
        self._media_check = media_check  # async: can WhatsApp send audio at all?

    NO_AUDIO = "O OpenWA instalado não consegue enviar áudio (falta a função de enviar arquivos). Por enquanto só dá para responder em texto."

    async def ensure_audio_possible(self) -> None:
        if self._media_check is not None and await self._media_check() is False:
            raise AutomationError(self.NO_AUDIO)

    # ---- files
    def _proposal_file(self, action_id: str) -> Path:
        return self._dir / "proposals" / f"{action_id}.ogg"

    def recording_path(self, auto_id: str) -> Path:
        return self._dir / f"{auto_id}.ogg"

    def preview(self, action_id: str) -> bytes | None:
        """The recording of a pending voice automation, to listen to before confirming."""
        path = self._proposal_file(action_id)
        return path.read_bytes() if path.is_file() else None

    # ---- proposing
    def propose_create(self, spec: Spec, recording: bytes | None = None) -> Action:
        """`recording` is a ready Ogg/Opus voice note (the person's own voice); without it a voice reply is synthesized."""
        if len(self._store.list()) >= self.MAX_AUTOMATIONS:
            raise AutomationError(f"limite de {self.MAX_AUTOMATIONS} automações atingido; apague alguma antes de criar outra")
        voice = spec.action["type"] == "whatsapp_voice"
        if voice and recording is None:
            if self._voice is None or not self._voice.store.installed():
                raise AutomationError("Para responder em áudio é preciso ligar e baixar a Voz melhorada em Ajustes.")
            try:
                recording = wav_to_ogg_opus(self._voice.synthesize(spec.action["text"], "normal"))
            except (VoiceError, ValueError) as exc:
                raise AutomationError(f"Não consegui gravar a resposta em áudio: {exc}") from None
        body = {"name": spec.name, "trigger": spec.trigger, "action": spec.action}
        action = self._propose("automation.create", describe(spec), {"spec": body, "voice": voice, "own": bool(spec.action.get("own_voice"))})
        if recording is not None:
            path = self._proposal_file(action.id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(recording)
        return action

    def pending_confirmation(self) -> Action | None:
        """The newest creation still waiting: what a spoken "sim" or "não" is about."""
        waiting = [a for a in self.pending() if a.kind == "automation.create"]
        return waiting[-1] if waiting else None

    # ---- executing (only after the person confirmed)
    def _execute(self, action: Action) -> str:
        if action.kind != "automation.create":
            raise ValueError(f"unknown action kind {action.kind}")
        spec = parse_spec(action.payload["spec"])
        automation = self._store.create(spec, self._now())
        proposal = self._proposal_file(action.id)
        if action.payload.get("voice"):
            if not proposal.is_file():
                self._store.delete(automation.id)
                raise AutomationError("a gravação desta automação se perdeu; peça de novo")
            self._dir.mkdir(parents=True, exist_ok=True)
            proposal.replace(self._dir / f"{automation.id}.ogg")
        return f"Automação criada: {spec.name}"

    def reject(self, action_id: str) -> Action:
        action = super().reject(action_id)
        self._proposal_file(action_id).unlink(missing_ok=True)
        return action
