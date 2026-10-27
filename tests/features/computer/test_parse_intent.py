import json

import pytest

from chakmati.features.computer.assistant import parse_intent

OTHER = {"action": "other"}


def old_parse_intent(reply: str) -> dict:
    """The strict parser as it was before the tolerant fallback: what a well-behaved model must keep getting."""
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return {"action": "other"}
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return {"action": "other"}
    if not isinstance(data, dict):
        return {"action": "other"}
    action = data.get("action")
    if action is None and isinstance(data.get("steps"), list):
        action = "steps"
    if action not in {"steps", "open_app", "open_url", "open_path", "edit", "revert", "trash"}:
        return {"action": "other"}
    out: dict = {"action": action}
    for key in ("app", "url", "path", "instruction", "goal"):
        if isinstance(data.get(key), str):
            out[key] = data[key].strip()
    steps = data.get("steps")
    if isinstance(steps, list):
        out["steps"] = [s for s in steps if isinstance(s, dict) and s.get("type") in ("command", "create_file")][:12]
    return out


# What the 9B model really answered in the benchmark, plus the other shapes the strict parser accepts.
WELL_FORMED = [
    '{"action":"steps","steps":[{"type":"command","command":"mkdir -p teste-agente/docs"}]}',
    '{\n  "action": "steps",\n  "steps": [\n    {"type": "create_file", "path": "lista.txt", "content": "leite\\npão\\novos"}\n  ]\n}',
    '{"action":"open_app","app":"Spotify"}',
    '{"action":"open_url","url":"https://github.com"}',
    '{"action":"edit","path":"lista.txt","instruction":"trocar leite por café"}',
    '{"action":"trash","path":"rascunho.txt"}',
    '{"action":"revert","path":"lista.txt"}',
    '{"action":"open_path","path":"Documents"}',
    '{"steps":[{"type":"command","command":"ls -la"}]}',  # no action word, steps present: already accepted
    'Claro! {"action":"steps","steps":[{"type":"command","command":"pwd"}]} pronto.',
    '{"action":"other"}',
    '{"action":"format_disk"}',
    "sem json",
    "[1, 2, 3]",
    '{"action":"steps"',
    "",
]


@pytest.mark.parametrize("reply", WELL_FORMED)
def test_replies_the_strict_parser_already_understood_are_unchanged(reply):
    assert parse_intent(reply) == old_parse_intent(reply)


@pytest.mark.parametrize(
    "reply",
    [
        '{"type":"other","command":"echo piada"}',  # a model that says "other" is not a command, even with a command inside
        '{"type":"other","command":"open_url","url":"https://google.com"}',
        '{"action":"other","steps":[{"type":"command","command":"ls"}]}',
        '{"action":"other","command":"ls"}',
    ],
)
def test_an_explicit_other_is_never_turned_into_an_action(reply):
    assert parse_intent(reply) == OTHER


# ----------------------------------------------------------------------------- the slips small models make
@pytest.mark.parametrize(
    "reply, expected",
    [
        ('{"type":"open_url","url":"https://github.com"}', {"action": "open_url", "url": "https://github.com"}),
        ('{"type":"edit","path":"lista.txt","instruction":"Trocando leite por café"}', {"action": "edit", "path": "lista.txt", "instruction": "Trocando leite por café"}),
        ('{"type":"open_app","app":"Spotify"}', {"action": "open_app", "app": "Spotify"}),
        ('{"type":"trash","path":"rascunho.txt"}', {"action": "trash", "path": "rascunho.txt"}),
    ],
)
def test_type_in_place_of_action(reply, expected):
    assert parse_intent(reply) == expected


def test_a_lone_command_step_without_steps():
    assert parse_intent('{"type":"command","command":"ls -la"}') == {
        "action": "steps",
        "steps": [{"type": "command", "command": "ls -la"}],
    }


def test_a_lone_create_file_step_without_steps():
    got = parse_intent('{"type":"create_file","path":"lista.txt","content":"leite\\npão\\novos"}')
    assert got == {"action": "steps", "steps": [{"type": "create_file", "path": "lista.txt", "content": "leite\npão\novos"}]}


def test_a_bare_command_without_any_type():
    assert parse_intent('{"command":"pwd"}') == {"action": "steps", "steps": [{"type": "command", "command": "pwd"}]}


def test_a_bare_path_and_content_is_a_new_file():
    got = parse_intent('{"path":"lista.txt","content":"leite"}')
    assert got == {"action": "steps", "steps": [{"type": "create_file", "path": "lista.txt", "content": "leite"}]}


def test_steps_without_a_type_get_one_from_their_fields():
    got = parse_intent('{"steps":[{"command":"cp \\"a.txt\\" \\"b.txt\\"","instruction":"copy"},{"path":"x.txt","content":"oi"}]}')
    assert got["action"] == "steps"
    assert got["steps"] == [
        {"type": "command", "command": 'cp "a.txt" "b.txt"', "instruction": "copy"},
        {"type": "create_file", "path": "x.txt", "content": "oi"},
    ]


def test_an_unknown_step_type_with_a_command_is_a_command():
    got = parse_intent('{"action":"steps","steps":[{"type":"cat","command":"ls -la"}]}')
    assert got["steps"] == [{"type": "command", "command": "ls -la"}]


def test_a_create_file_step_without_content_is_left_as_it_was():
    reply = '{"action":"steps","steps":[{"type":"create_file","path":"vazio.txt"}]}'
    assert parse_intent(reply) == old_parse_intent(reply)  # the assistant already defaults the content to ""


def test_a_single_action_dressed_as_a_step_is_promoted():
    got = parse_intent('{"steps":[{"type":"open_url","url":"https://github.com"}]}')
    assert got == {"action": "open_url", "url": "https://github.com"}


def test_several_actions_dressed_as_steps_are_not_guessed_at():
    # a small model answering "me conta uma piada" with two programs to open: do nothing rather than pick one
    reply = '{"action":"steps","steps":[{"type":"open_app","app":"Safari"},{"type":"open_url","url":"https://x.org"}]}'
    got = parse_intent(reply)
    assert got["action"] != "open_app" and not got.get("steps")


# ----------------------------------------------------------------------------- limits that must hold
def test_the_steps_cap_and_non_dict_steps_still_apply():
    steps = [{"type": "command", "command": "pwd"}] * 20 + ["texto", 3]
    got = parse_intent(json.dumps({"action": "steps", "steps": steps}))
    assert len(got["steps"]) == 12


def test_unrelated_json_is_still_other():
    assert parse_intent('{"name":"x","value":3}') == OTHER
    assert parse_intent('{"type":"format_disk"}') == OTHER
    assert parse_intent('{"action":"rm","path":"/"}') == OTHER


def test_repairing_the_shape_never_lets_a_forbidden_command_through():
    # the parser only fixes the shape; policy.check still judges every command before anything runs
    from chakmati.features.computer.policy import PolicyError, Roots, check

    got = parse_intent('{"type":"command","command":"rm -rf /"}')
    assert got["steps"] == [{"type": "command", "command": "rm -rf /"}]
    with pytest.raises(PolicyError):
        check(got["steps"][0]["command"], Roots.make("."))
