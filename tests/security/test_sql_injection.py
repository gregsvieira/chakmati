"""SQL injection: every stored value and every id reaches SQLite as a bound parameter. Tried through each store with the payloads in
payloads.py, and a static scan makes sure nobody adds a query built from text."""

import ast
import sqlite3
from pathlib import Path

import pytest

from chakmati.features.automations.models import MAX_NAME, SpecError, parse_spec
from chakmati.features.automations.store import AutomationStore
from chakmati.features.computer.safety import ComputerError
from chakmati.features.computer.service import ComputerService
from chakmati.shared.approvals import ActionStore
from chakmati.shared.jobs import JobStore

from .payloads import SQL_PAYLOADS

TABLES = {"automations", "automation_runs", "actions", "jobs", "computer_plans", "computer_edits"}


def tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.mark.parametrize("payload", SQL_PAYLOADS, ids=range(len(SQL_PAYLOADS)))
def test_the_automation_store_keeps_hostile_text_as_text(tmp_path, payload):
    store = AutomationStore(str(tmp_path / "a.db"))
    text = payload[:500]
    if "\x00" in payload:                                                  # a control character never gets as far as the database
        with pytest.raises(SpecError):
            parse_spec({"name": "x", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": text}})
        return
    spec = parse_spec({"name": payload[:MAX_NAME], "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": text}})
    created = store.create(spec, 1.0)
    assert store.get(created.id).spec.action["text"] == spec.action["text"]   # stored and read back exactly, never run
    assert store.get(created.id).spec.name == spec.name
    assert store.get(payload) is None                                     # a hostile id finds nothing
    assert store.set_enabled(payload, False) is False and store.delete(payload) is False
    store.record_run(created.id, payload, payload, 2.0)
    assert store.last_run(created.id, payload) is None                    # outcome is not 'ok': the key was written, not executed
    assert store.recent_runs(payload) == [] and store.recent_runs(created.id)[0]["key"] == payload
    assert len(store.list()) == 1 and {"automations", "automation_runs"} <= tables(store._db)


@pytest.mark.parametrize("payload", SQL_PAYLOADS, ids=range(len(SQL_PAYLOADS)))
def test_the_action_log_keeps_hostile_text_as_text(payload):
    actions = ActionStore(":memory:")
    action = actions.add("whatsapp.send", payload, {"text": payload, "chat_name": payload}, 1.0, 9999.0)
    assert actions.get(action.id).summary == payload
    assert actions.get(payload) is None
    assert actions.transition(payload, "pending", "approved") is False
    actions.finish(payload, "executed", payload, payload)                 # an unknown id: nothing changes, nothing breaks
    assert [a.id for a in actions.pending(2.0)] == [action.id]
    assert "actions" in tables(actions._db) and actions._db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1


@pytest.mark.parametrize("payload", SQL_PAYLOADS, ids=range(len(SQL_PAYLOADS)))
def test_the_job_store_keeps_hostile_prompts_as_text(payload):
    store = JobStore(":memory:")
    job_id = store.create(payload[:40], payload)
    assert store.get(job_id).prompt == payload
    assert store.get(payload) is None
    assert "jobs" in tables(store._db)


@pytest.mark.parametrize("payload", SQL_PAYLOADS[:8], ids=range(8))
def test_file_names_with_quotes_reach_the_edit_log_as_data(tmp_path, payload):
    work = tmp_path / "work"
    work.mkdir()
    service = ComputerService(str(work), ActionStore(":memory:"), home=str(tmp_path))
    name = "o'brien \"x\" .txt"                                            # quotes in a real file name
    (work / name).write_text("antes\n", encoding="utf-8")
    if "\x00" in payload:
        with pytest.raises(ComputerError):
            service.propose_edit(name, f"depois {payload}\n")
        return
    action = service.propose_edit(name, f"depois {payload}\n")
    service.approve(action.id)
    row = service._db.execute("SELECT original FROM computer_edits").fetchone()
    assert row["original"].endswith(name)
    assert {"computer_edits", "computer_plans", "actions"} <= tables(service._db)
    assert service.propose_revert(name) is not None


@pytest.mark.parametrize("payload", SQL_PAYLOADS[:6], ids=range(6))
def test_a_hostile_plan_id_finds_nothing(tmp_path, payload):
    service = ComputerService(str(tmp_path), ActionStore(":memory:"), home=str(tmp_path))
    assert service._plan_row(payload) is None
    assert "computer_plans" in tables(service._db)


# ------------------------------------------------------------------------------------------------ the guard that stays
SRC = Path(__file__).resolve().parents[2] / "src" / "chakmati"
METHODS = {"execute", "executemany", "executescript"}


def _static(node: ast.AST) -> bool:
    """A query written in the source: a string literal, literals joined with +, or a choice between literals."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _static(node.left) and _static(node.right)
    if isinstance(node, ast.IfExp):
        return _static(node.body) and _static(node.orelse)
    return False


def test_no_query_is_built_from_text():
    """`execute(f"... {x}")`, `"..." % x`, `"..." + x` or `.format()` put data inside the SQL. Values go in the second argument."""
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in METHODS and node.args:
                if not _static(node.args[0]):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == [], f"queries built from text (use ? placeholders): {offenders}"


def test_the_scan_really_catches_a_built_query():
    bad = ast.parse('db.execute(f"SELECT * FROM t WHERE id = {x}")').body[0].value
    also = ast.parse('db.execute("SELECT * FROM t WHERE id = " + x)').body[0].value
    ok = ast.parse('db.execute("SELECT * FROM t WHERE id = ?" + (" LIMIT 1" if y else ""), (x,))').body[0].value
    assert not _static(bad.args[0]) and not _static(also.args[0]) and _static(ok.args[0])
