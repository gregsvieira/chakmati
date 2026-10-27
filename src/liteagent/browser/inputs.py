"""Questions the browser agent has for the person ("qual é o seu usuário?", "e a senha?") and the answers.

The agent never makes up a user name, a password or any personal detail: it asks. The question reaches the person's screen as an input in the
conversation (a masked one for a password); the answer comes back through the engine's API and goes to the agent, which types it into the page.
An answer is held in memory only until the agent takes it, is never written to the database, a log or a screenshot caption, and is never given
to the language model: the model only learns that the answer arrived."""

import asyncio
import uuid
from dataclasses import dataclass, field

ASK_SECONDS = 300.0
MAX_ANSWER = 500


@dataclass
class Request:
    id: str
    job_id: str
    key: str
    prompt: str
    secret: bool
    future: asyncio.Future = field(repr=False)


class InputBroker:
    def __init__(self, timeout: float = ASK_SECONDS):
        self._timeout = timeout
        self._pending: dict[str, Request] = {}  # by job id: a job asks one thing at a time

    async def ask(self, job_id: str, key: str, prompt: str, secret: bool = False) -> str | None:
        """The person's answer, or None if none came in time (or the job was cancelled)."""
        request = Request(uuid.uuid4().hex, job_id, key, prompt[:300], bool(secret), asyncio.get_running_loop().create_future())
        self._pending[job_id] = request
        try:
            return await asyncio.wait_for(request.future, self._timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None
        finally:
            if self._pending.get(job_id) is request:
                del self._pending[job_id]

    def pending(self, job_id: str) -> Request | None:
        return self._pending.get(job_id)

    def answer(self, job_id: str, request_id: str, value: str) -> bool:
        request = self._pending.get(job_id)
        if request is None or request.id != request_id or request.future.done():
            return False
        request.future.set_result(str(value)[:MAX_ANSWER])
        return True
