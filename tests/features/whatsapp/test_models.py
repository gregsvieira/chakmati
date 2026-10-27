from datetime import datetime, timezone

import pytest

from chakmati.features.whatsapp.models import MAX_TEXT, Message, Outgoing

TS = datetime(2026, 10, 23, 10, 32, tzinfo=timezone.utc)


def test_outgoing_accepts_a_normal_message_and_strips_the_edges():
    o = Outgoing("5511@c.us", "  Olá, tudo bem?\nAté já.  ")
    assert o.text == "Olá, tudo bem?\nAté já."


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_TEXT + 1), "oi\x00mundo", "oi\x1b[31mmundo"])
def test_outgoing_rejects_empty_oversized_or_control_characters(text):
    with pytest.raises(ValueError):
        Outgoing("5511@c.us", text)


@pytest.mark.parametrize("to", ["", "5511", "5511@bot", "status@broadcast", "x@newsletter", "a b@c.us"])
def test_outgoing_only_accepts_person_or_group_ids(to):
    with pytest.raises(ValueError, match="recipient"):
        Outgoing(to, "oi")


@pytest.mark.parametrize("to", ["5511999990000@c.us", "205123456789012@lid", "120363000000@g.us"])
def test_outgoing_accepts_the_three_id_kinds(to):
    assert Outgoing(to, "oi").to == to


def test_message_display_is_one_line_per_message_with_time_and_sender():
    m = Message("i", "1@lid", "Maria", "oi\nsegunda linha", TS, False, "chat")
    line = m.display()
    assert "\n" not in line and "Maria" in line and "oi" in line and "segunda linha" in line and "10:32" in line
