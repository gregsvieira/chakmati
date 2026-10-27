from chakmati.loop.parts import compose_messages, draft_messages, parse_parts


def test_parse_json_array():
    assert parse_parts('["a", "b"]') == ["a", "b"]


def test_parse_json_inside_prose_and_fence():
    text = 'Claro!\n```json\n["um", "dois"]\n```\nPronto.'
    assert parse_parts(text) == ["um", "dois"]


def test_parse_bullets_fallback():
    assert parse_parts("- um\n* dois\n• três") == ["um", "dois", "três"]


def test_parse_numbered_fallback():
    assert parse_parts("1. um\n2) dois") == ["um", "dois"]


def test_parse_drops_blank_items_and_empty_text():
    assert parse_parts('["a", "  ", ""]') == ["a"]
    assert parse_parts("") == []


def test_parse_broken_json_falls_back_to_lines():
    assert parse_parts("[nao e json\n- item") == ["[nao e json", "item"]


def test_draft_messages_include_question_notes_and_k():
    msgs = draft_messages("Q?", ["nota 1"], k=3)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "at most 3" in msgs[0]["content"]
    assert "Q?" in msgs[1]["content"] and "- nota 1" in msgs[1]["content"]
    assert "(none yet)" in draft_messages("Q?", [])[1]["content"]


def test_compose_messages_use_only_kept_notes():
    msgs = compose_messages("Q?", ["a", "b"])
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "Q?" in msgs[1]["content"]
    assert "- a" in msgs[1]["content"] and "- b" in msgs[1]["content"]
    assert "ONLY the notes" in msgs[0]["content"]
