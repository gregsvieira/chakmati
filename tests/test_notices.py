import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from liteagent.agenda.models import CalendarEvent
from liteagent.approvals import Action
from liteagent.notices import (
    ApprovalWatcher,
    CalendarWatcher,
    NoticeBoard,
    Notifier,
    WhatsAppWatcher,
)
from liteagent.whatsapp.models import Chat
from liteagent.whatsapp.openwa import WhatsAppError

TS = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- the board
def test_board_assigns_increasing_ids_and_returns_what_is_newer():
    board = NoticeBoard()
    a = board.add("system", "um", "mascarado")
    b = board.add("whatsapp", "dois", "mascarado 2")
    assert (a.id, b.id) == (1, 2) and board.last_id == 2
    assert [n.text for n in board.since(0)] == ["um", "dois"] and [n.text for n in board.since(1)] == ["dois"]
    assert board.since(2) == []


def test_board_keeps_only_the_most_recent_notices():
    board = NoticeBoard(max_items=3)
    for i in range(5):
        board.add("system", f"n{i}", "m")
    assert [n.text for n in board.since(0)] == ["n2", "n3", "n4"]


async def test_wait_for_returns_immediately_when_there_is_a_backlog():
    board = NoticeBoard()
    board.add("system", "x", "m")
    assert [n.text for n in await board.wait_for(0, timeout=1)] == ["x"]


async def test_wait_for_wakes_up_when_a_notice_arrives_and_times_out_otherwise():
    board = NoticeBoard()
    waiter = asyncio.create_task(board.wait_for(0, timeout=2))
    await asyncio.sleep(0.05)
    board.add("system", "chegou", "m")
    assert [n.text for n in await waiter] == ["chegou"]
    assert await board.wait_for(board.last_id, timeout=0.05) == []


# ----------------------------------------------------------------------------- whatsapp watcher
def chat(i, name, unread=0, group=False, archived=False, muted=False):
    return Chat(f"{i}@{'g.us' if group else 'lid'}", name, group, unread, TS, None, archived, muted)


class FakeWhatsApp:
    def __init__(self, chats=()):
        self.chats_now, self.error = list(chats), None

    async def chats(self, unread_only=False, limit=50):
        if self.error:
            raise self.error
        return list(self.chats_now)


async def test_first_poll_is_a_baseline_with_one_summary_not_a_notice_per_chat():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "Maria", 2), chat(2, "João", 1), chat(3, "Ana", 0)])
    await WhatsAppWatcher(wa, board).poll_once()
    (n,) = board.since(0)
    assert n.kind == "whatsapp" and n.text == "Você tem 2 conversas com mensagens não lidas" and "Maria" not in n.masked


async def test_first_poll_with_nothing_unread_says_nothing():
    board = NoticeBoard()
    await WhatsAppWatcher(FakeWhatsApp([chat(1, "Maria", 0)]), board).poll_once()
    assert board.since(0) == []


async def test_a_new_message_announces_the_sender_and_has_a_name_free_masked_version():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "Maria Victoria", 0)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    wa.chats_now = [chat(1, "Maria Victoria", 1)]
    await w.poll_once()
    (n,) = board.since(0)
    assert n.text == "Você recebeu uma nova mensagem de Maria Victoria"
    assert n.masked == "Você recebeu uma nova mensagem no WhatsApp" and "Maria" not in n.masked
    assert n.key == "1@lid"


async def test_several_messages_groups_and_unchanged_state():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "Maria", 1), chat(2, "Família", 0, group=True)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    board_start = board.last_id
    wa.chats_now = [chat(1, "Maria", 4), chat(2, "Família", 1, group=True)]
    await w.poll_once()
    texts = sorted(n.text for n in board.since(board_start))
    assert texts == ["Nova mensagem no grupo Família", "Você recebeu 3 novas mensagens de Maria"]
    mark = board.last_id
    await w.poll_once()  # nothing changed
    assert board.since(mark) == []


async def test_reading_on_the_phone_lowers_the_baseline_so_the_next_message_is_announced():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "Maria", 3)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    mark = board.last_id
    wa.chats_now = [chat(1, "Maria", 0)]  # read elsewhere
    await w.poll_once()
    assert board.since(mark) == []
    wa.chats_now = [chat(1, "Maria", 1)]
    await w.poll_once()
    assert [n.text for n in board.since(mark)] == ["Você recebeu uma nova mensagem de Maria"]


async def test_muted_and_archived_chats_are_never_announced():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "A", 0, muted=True), chat(2, "B", 0, archived=True)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    wa.chats_now = [chat(1, "A", 5, muted=True), chat(2, "B", 5, archived=True)]
    await w.poll_once()
    assert board.since(0) == []


async def test_many_chats_at_once_collapse_into_one_notice():
    board = NoticeBoard()
    wa = FakeWhatsApp([chat(i, f"Pessoa {i}", 0) for i in range(6)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    wa.chats_now = [chat(i, f"Pessoa {i}", 1) for i in range(6)]
    await w.poll_once()
    (n,) = board.since(0)
    assert n.text.startswith("Você recebeu novas mensagens de ") and "e mais 3" in n.text
    assert n.masked == "Você recebeu 6 novas mensagens no WhatsApp"


async def test_losing_and_regaining_the_connection_is_reported_once_each():
    board, wa = NoticeBoard(), FakeWhatsApp([chat(1, "Maria", 0)])
    w = WhatsAppWatcher(wa, board)
    await w.poll_once()
    wa.error = WhatsAppError("OpenWA unreachable")
    await w.poll_once()
    await w.poll_once()
    assert [n.kind for n in board.since(0)] == ["system"] and "desconect" in board.since(0)[0].text.lower()
    wa.error = None
    await w.poll_once()
    assert "voltou" in board.since(0)[-1].text.lower() and len(board.since(0)) == 2


# ----------------------------------------------------------------------------- calendar watcher
class FakeCalendar:
    def __init__(self, events=()):
        self.events_now = list(events)

    def events(self, start, end):
        return [e for e in self.events_now if e.start < end and e.end > start]


def ev(i, title, start, minutes=60, all_day=False):
    return CalendarEvent(f"e{i}", title, start, start + timedelta(minutes=minutes), all_day)


async def test_an_event_starting_soon_is_announced_once():
    now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    board = NoticeBoard()
    cal = FakeCalendar([ev(1, "Reunião", now + timedelta(minutes=7)), ev(2, "Depois", now + timedelta(minutes=45)),
                        ev(3, "Feriado", now.replace(hour=0), 1440, all_day=True), ev(4, "Já começou", now - timedelta(minutes=5))])
    w = CalendarWatcher(cal, board, lead_minutes=10, now=lambda: now)
    await w.poll_once()
    (n,) = board.since(0)
    assert n.kind == "calendar" and n.text == "Em 7 min: Reunião" and n.masked == "Você tem um compromisso em breve"
    await w.poll_once()
    assert len(board.since(0)) == 1


async def test_an_event_that_is_already_starting_says_so():
    now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    board = NoticeBoard()
    await CalendarWatcher(FakeCalendar([ev(1, "Dentista", now + timedelta(seconds=20))]), board, now=lambda: now).poll_once()
    assert board.since(0)[0].text == "Agora: Dentista"


# ----------------------------------------------------------------------------- approval watcher
class FakeApprovals:
    def __init__(self):
        self.items = []

    def pending(self):
        return list(self.items)


def action(i, summary):
    return Action(f"a{i}", "whatsapp.send", summary, "pending", {}, None, None, 9e9)


async def test_new_pending_actions_are_announced_once():
    board, svc = NoticeBoard(), FakeApprovals()
    w = ApprovalWatcher([svc], board)
    await w.poll_once()
    assert board.since(0) == []
    svc.items = [action(1, "Enviar WhatsApp para Greg:\nteste")]
    await w.poll_once()
    (n,) = board.since(0)
    assert n.kind == "approval" and n.text == "Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Greg:"
    assert n.masked == "Há uma ação aguardando a sua aprovação"
    await w.poll_once()
    assert len(board.since(0)) == 1
    svc.items += [action(2, "Criar evento: x"), action(3, "Criar evento: y")]
    await w.poll_once()
    assert board.since(0)[-1].text == "Há 2 ações aguardando a sua aprovação"


# ----------------------------------------------------------------------------- notifier
async def test_notifier_polls_every_watcher_on_its_own_interval_and_survives_errors():
    calls = {"a": 0, "b": 0}

    class Good:
        interval = 0.01

        async def poll_once(self):
            calls["a"] += 1

    class Bad:
        interval = 0.01

        async def poll_once(self):
            calls["b"] += 1
            raise RuntimeError("boom")

    n = Notifier([Good(), Bad()])
    n.start()
    await asyncio.sleep(0.15)
    await n.stop()
    assert calls["a"] >= 3 and calls["b"] >= 3  # the failing watcher keeps being retried
    before = dict(calls)
    await asyncio.sleep(0.05)
    assert calls == before  # stopped


async def test_notifier_runs_background_listeners_and_cancels_them_on_stop():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def listener():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    notifier = Notifier([], background=[listener])
    notifier.start()
    await asyncio.wait_for(started.wait(), 1)
    await notifier.stop()
    assert cancelled.is_set()


async def test_whatsapp_watcher_can_stay_silent_about_the_connection():
    class Down:
        async def chats(self, limit=500):
            raise WhatsAppError("down")

    board = NoticeBoard()
    watcher = WhatsAppWatcher(Down(), board, announce_connection=False)
    await watcher.poll_once()
    assert board.since(0) == []
