from datetime import datetime, timezone

import pytest

from chakmati.shared.approvals import ActionNotPending, ActionStore
from chakmati.features.whatsapp.models import Chat, Message
from chakmati.features.whatsapp.service import RateLimited, WhatsAppService

TS = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
MARIA = Chat("205123@lid", "Maria Silva", False, 0, TS, "5511999990000")
FAMILIA = Chat("120363@g.us", "Família", True, 0, TS)


class FakeProvider:
    def __init__(self):
        self.sent, self.fail = [], False

    async def send_text(self, chat_id, text):
        if self.fail:
            raise RuntimeError("whatsapp is down")
        self.sent.append((chat_id, text))
        return f"true_{chat_id}_X{len(self.sent)}"

    async def list_chats(self, unread_only=False, limit=50):
        return [MARIA, FAMILIA]

    async def get_messages(self, chat_id, last=20):
        return [Message("m", chat_id, "Maria", "oi", TS, False)]


class Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


@pytest.fixture
def parts():
    provider, clock, slept = FakeProvider(), Clock(), []

    async def fake_sleep(seconds):
        slept.append(round(seconds, 3))

    svc = WhatsAppService(provider, ActionStore(":memory:"), 3600, clock, max_sends_per_hour=2, min_interval=3.0, sleep=fake_sleep)
    return svc, provider, clock, slept


def test_proposing_sends_nothing_and_shows_recipient_and_exact_text(parts):
    svc, provider, _, _ = parts
    a = svc.propose_send(MARIA, "Chego em 10 minutos 🚗\nme espera")
    assert a.status == "pending" and a.kind == "whatsapp.send"
    assert "Maria Silva" in a.summary and "+5511999990000" in a.summary and "Chego em 10 minutos 🚗\nme espera" in a.summary
    assert provider.sent == [] and [x.id for x in svc.pending()] == [a.id]


def test_group_recipients_are_marked_in_the_summary(parts):
    svc, *_ = parts
    assert "(grupo)" in svc.propose_send(FAMILIA, "oi pessoal").summary


@pytest.mark.parametrize("chat,text", [(MARIA, ""), (MARIA, "x" * 5000), (MARIA, "bad\x1b[0m"),
                                       (Chat("x@bot", "Meta AI", False, 0, None), "oi")])
def test_invalid_proposals_are_refused_before_anything_is_stored(parts, chat, text):
    svc, *_ = parts
    with pytest.raises(ValueError):
        svc.propose_send(chat, text)
    assert svc.pending() == []


def test_an_identical_pending_proposal_is_not_duplicated(parts):
    svc, *_ = parts
    a = svc.propose_send(MARIA, "oi")
    assert svc.propose_send(MARIA, "oi").id == a.id
    assert svc.propose_send(MARIA, "oi!").id != a.id and len(svc.pending()) == 2


async def test_approve_sends_exactly_the_proposed_text_once(parts):
    svc, provider, _, _ = parts
    a = svc.propose_send(MARIA, "Olá, Maria!")
    done = await svc.aapprove(a.id)
    assert done.status == "executed" and "Maria Silva" in done.result and "X1" in done.result
    assert provider.sent == [("205123@lid", "Olá, Maria!")]
    with pytest.raises(ActionNotPending):
        await svc.aapprove(a.id)
    assert len(provider.sent) == 1


async def test_reject_never_sends(parts):
    svc, provider, _, _ = parts
    a = svc.propose_send(MARIA, "oi")
    assert svc.reject(a.id).status == "rejected"
    assert provider.sent == []


async def test_provider_failure_is_recorded_and_not_retried(parts):
    svc, provider, _, _ = parts
    provider.fail = True
    done = await svc.aapprove(svc.propose_send(MARIA, "oi").id)
    assert done.status == "failed" and "whatsapp is down" in done.error and provider.sent == []


async def test_hourly_limit_refuses_but_keeps_the_proposal_pending(parts):
    svc, provider, clock, _ = parts
    for text in ("um", "dois"):
        await svc.aapprove(svc.propose_send(MARIA, text).id)
    third = svc.propose_send(MARIA, "três")
    with pytest.raises(RateLimited):
        await svc.aapprove(third.id)
    assert svc._actions.get(third.id).status == "pending" and len(provider.sent) == 2
    clock.t += 3601  # an hour later the window has moved on
    assert (await svc.aapprove(svc.propose_send(MARIA, "quatro").id)).status == "executed"


async def test_a_minimum_interval_is_enforced_between_sends(parts):
    svc, provider, clock, slept = parts
    await svc.aapprove(svc.propose_send(MARIA, "um").id)
    clock.t += 1.0
    await svc.aapprove(svc.propose_send(MARIA, "dois").id)
    assert slept == [2.0]  # 3 s minimum minus the 1 s that already passed; nothing for the first send


async def test_reading_passes_through_to_the_provider(parts):
    svc, *_ = parts
    assert [c.name for c in await svc.chats()] == ["Maria Silva", "Família"]
    assert (await svc.messages(MARIA.id))[0].text == "oi"
