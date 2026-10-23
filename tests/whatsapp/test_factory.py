import pytest

from liteagent.config import Settings
from liteagent.whatsapp.factory import build_whatsapp
from liteagent.whatsapp.openwa import OpenWAClient


def test_off_builds_nothing():
    assert build_whatsapp(Settings(db_path=":memory:")) is None


def test_openwa_uses_the_api_key_from_the_setting(tmp_path):
    svc = build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="openwa", openwa_api_key="from-env",
                                  openwa_api_key_file=str(tmp_path / "missing.txt"), openwa_url="http://h:9"))
    assert isinstance(svc._provider, OpenWAClient) and svc._provider._key == "from-env" and svc._provider._base == "http://h:9"


def test_openwa_falls_back_to_the_key_file(tmp_path):
    f = tmp_path / "key.txt"
    f.write_text("from-file\n")
    svc = build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="openwa", openwa_api_key_file=str(f)))
    assert svc._provider._key == "from-file"


def test_the_environment_key_wins_over_the_file(tmp_path):
    f = tmp_path / "key.txt"
    f.write_text("from-file")
    svc = build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="openwa", openwa_api_key="env", openwa_api_key_file=str(f)))
    assert svc._provider._key == "env"


def test_no_key_anywhere_still_builds_with_an_empty_key(tmp_path):
    svc = build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="openwa", openwa_api_key_file=str(tmp_path / "none")))
    assert svc._provider._key == ""


def test_the_send_limit_comes_from_the_settings():
    svc = build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="openwa", whatsapp_max_sends_per_hour=3))
    assert svc._max == 3


def test_unknown_backend_is_an_error():
    with pytest.raises(ValueError, match="whatsapp_backend"):
        build_whatsapp(Settings(db_path=":memory:", whatsapp_backend="baileys"))


def test_events_listener_exists_only_when_whatsapp_is_on():
    from liteagent.config import Settings
    from liteagent.notices import NoticeBoard
    from liteagent.whatsapp.factory import build_whatsapp_events

    assert build_whatsapp_events(Settings(whatsapp_backend="off"), NoticeBoard()) is None
    assert build_whatsapp_events(Settings(whatsapp_backend="openwa", openwa_api_key="k"), NoticeBoard()) is not None
