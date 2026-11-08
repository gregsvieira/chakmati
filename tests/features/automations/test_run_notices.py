"""Every run of an automation becomes a notice in "Avisos recentes": it ran, it ran late, it ran only in part, or it failed."""

from datetime import datetime, timedelta, timezone

import pytest

from chakmati.features.automations.models import parse_spec
from chakmati.features.automations.runner import CATCHUP_MINUTES, PREFIX, AutomationRunner
from chakmati.features.automations.store import AutomationStore
from chakmati.features.whatsapp.models import Chat
from chakmati.shared.notices import NoticeBoard

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
CHAT = {"chat_id": "111@lid", "name": "Maria"}
MARIA = Chat("111@lid", "Maria", False, 1, NOW, "5511111")


class WhatsApp:
    def __init__(self):
        self.sent, self.error = [], None

    async def send_automated(self, chat_id, chat_name, text=None, audio=None, mime=None, source=""):
        if self.error:
            raise self.error
        self.sent.append(text)
        return "id"


def build(tmp_path, created=None, **spec):
    store, wa, board = AutomationStore(":memory:"), WhatsApp(), NoticeBoard()
    runner = AutomationRunner(store, wa, voice_dir=tmp_path, now=lambda: NOW.timestamp(), notices=board)
    base = {"name": "Bom dia", "trigger": {"type": "schedule", "cron": "0 9 * * *"}, "action": {"type": "whatsapp_text", "to": CHAT, "text": "Bom dia!"}}
    auto = store.create(parse_spec({**base, **spec}), created if created is not None else (NOW - timedelta(days=3)).timestamp())
    return runner, wa, board, auto


def texts(board):
    return [(n.kind, n.text, n.masked) for n in board.since(0)]


async def test_a_run_on_time_is_a_notice(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    await runner.tick(NOW + timedelta(seconds=20))
    assert wa.sent == [PREFIX + "Bom dia!"]
    assert texts(board) == [("automation", "A automação “Bom dia” rodou para Maria.", "Uma automação rodou.")]


async def test_a_run_a_minute_late_is_still_on_time(tmp_path):
    runner, _, board, _ = build(tmp_path)
    await runner.tick(NOW + timedelta(seconds=90))
    assert "atraso" not in board.since(0)[0].text


async def test_a_missed_schedule_runs_late_and_says_so(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    await runner.tick(NOW + timedelta(minutes=12, seconds=5))   # the computer woke up at 09:12
    assert len(wa.sent) == 1
    assert board.since(0)[0].text == "A automação “Bom dia” rodou com atraso de 12 min (era para as 09:00) para Maria."
    assert board.since(0)[0].masked == "Uma automação rodou com atraso."


async def test_a_late_run_happens_once_even_if_the_ticker_keeps_looking(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    for seconds in (0, 20, 40, 60):
        await runner.tick(NOW + timedelta(minutes=12, seconds=seconds))
    assert len(wa.sent) == 1 and len(board.since(0)) == 1


async def test_a_schedule_missed_for_longer_than_the_window_is_not_run_at_all(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    await runner.tick(NOW + timedelta(minutes=CATCHUP_MINUTES + 1))
    assert wa.sent == [] and board.since(0) == []


async def test_an_automation_made_after_the_missed_minute_does_not_catch_up(tmp_path):
    runner, wa, board, _ = build(tmp_path, created=(NOW + timedelta(minutes=5)).timestamp())
    await runner.tick(NOW + timedelta(minutes=10))
    assert wa.sent == [] and board.since(0) == []


async def test_only_the_latest_missed_minute_runs(tmp_path):
    runner, wa, _, _ = build(tmp_path, trigger={"type": "schedule", "cron": "0,10,20 9 * * *"})
    await runner.tick(NOW + timedelta(minutes=25))      # 09:00, 09:10 and 09:20 are all behind: one run, for 09:20
    assert len(wa.sent) == 1


async def test_a_failure_is_a_notice_with_the_reason(tmp_path):
    runner, wa, board, auto = build(tmp_path)
    wa.error = RuntimeError("o WhatsApp não está conectado")
    await runner.tick(NOW)
    assert texts(board) == [("automation", "A automação “Bom dia” falhou: o WhatsApp não está conectado", "Uma automação falhou.")]
    assert runner._store.recent_runs(auto.id)[0]["outcome"].startswith("falhou")


async def test_a_late_failure_says_both(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    wa.error = RuntimeError("limite de envios")
    await runner.tick(NOW + timedelta(minutes=45 - 15))
    assert board.since(0)[0].text == "A automação “Bom dia” falhou com atraso de 30 min (era para as 09:00): limite de envios"


async def test_an_automatic_reply_to_a_message_is_a_notice_too(tmp_path):
    runner, wa, board, _ = build(tmp_path, trigger={"type": "whatsapp_message"}, action={"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"})
    await runner.on_whatsapp_messages([(MARIA, 1)])
    assert texts(board) == [("automation", "A automação “Bom dia” rodou para Maria.", "Uma automação rodou.")]


async def test_the_discreet_text_has_no_name_of_the_automation_nor_of_the_person(tmp_path):
    runner, wa, board, _ = build(tmp_path)
    wa.error = RuntimeError("falha com Maria")
    await runner.tick(NOW)
    assert "Bom dia" not in board.since(0)[0].masked and "Maria" not in board.since(0)[0].masked


async def test_without_a_board_nothing_changes(tmp_path):
    store, wa = AutomationStore(":memory:"), WhatsApp()
    runner = AutomationRunner(store, wa, voice_dir=tmp_path, now=lambda: NOW.timestamp())
    store.create(parse_spec({"trigger": {"type": "schedule", "cron": "0 9 * * *"}, "action": {"type": "whatsapp_text", "to": CHAT, "text": "oi"}}), 0.0)
    await runner.tick(NOW)
    assert len(wa.sent) == 1
