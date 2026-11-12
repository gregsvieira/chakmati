import os

from chakmati.shared import migrate
from chakmati.shared.migrate import LEGACY_SESSION, SESSION, migrate_data_dir


def _make(tmp_path, with_new=False):
    old, new = tmp_path / ".lite-agent", tmp_path / ".chakmati-agent"
    (old / "openwa" / "run" / LEGACY_SESSION).mkdir(parents=True)
    (old / "openwa" / "session-backup-1" / LEGACY_SESSION).mkdir(parents=True)
    (old / "openwa" / "api_key.txt").write_text("secret")
    (old / "home_auth.json").write_text("{}")
    if with_new:
        new.mkdir()
    return old, new


def test_the_old_folder_is_moved_with_everything_in_it(tmp_path):
    old, new = _make(tmp_path)
    assert migrate_data_dir(str(old), str(new)) is True
    assert not old.exists()
    assert (new / "openwa" / "api_key.txt").read_text() == "secret"
    assert (new / "home_auth.json").exists()


def test_the_whatsapp_session_folder_is_renamed_with_the_session(tmp_path):
    old, new = _make(tmp_path)
    migrate_data_dir(str(old), str(new))
    assert (new / "openwa" / "run" / SESSION).is_dir() and not (new / "openwa" / "run" / LEGACY_SESSION).exists()
    assert (new / "openwa" / "session-backup-1" / SESSION).is_dir()


def test_nothing_is_touched_when_the_new_folder_already_exists(tmp_path):
    old, new = _make(tmp_path, with_new=True)
    assert migrate_data_dir(str(old), str(new)) is False
    assert (old / "home_auth.json").exists()   # the old one is left alone, never merged or deleted


def test_nothing_happens_when_there_is_no_old_folder(tmp_path):
    assert migrate_data_dir(str(tmp_path / "a"), str(tmp_path / "b")) is False


def test_a_move_that_fails_keeps_the_old_folder(tmp_path, monkeypatch):
    old, new = _make(tmp_path)
    monkeypatch.setattr(os, "rename", lambda *a: (_ for _ in ()).throw(PermissionError("no")))
    assert migrate_data_dir(str(old), str(new)) is False
    assert (old / "home_auth.json").exists()


def test_the_data_folder_is_the_old_one_only_until_it_is_moved(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(migrate.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path), 1))
    assert migrate.data_dir() == str(tmp_path / ".chakmati-agent")           # a fresh computer: the new name
    (tmp_path / ".lite-agent").mkdir()
    assert migrate.data_dir() == str(tmp_path / ".lite-agent")                # not moved yet: the data is still found
    (tmp_path / ".chakmati-agent").mkdir()
    assert migrate.data_dir() == str(tmp_path / ".chakmati-agent")            # moved
