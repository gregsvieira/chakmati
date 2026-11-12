import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "set_download_links", Path(__file__).resolve().parents[2] / "scripts" / "set_download_links.py"
)
links = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(links)

LATEST = "https://github.com/gregsvieira/chakmati/releases/latest"
PAGE = f"""
<a class="dl-os" data-dl="mac-arm64" href="{LATEST}">Mac</a>
<a class="dl-os" data-dl="win-x64" href="{LATEST}">Windows</a>
<a class="dl-os" data-dl="linux-x64" href="{LATEST}">Ubuntu</a>
<a data-dl="mac-x64" href="{LATEST}">Intel</a>
<a href="{LATEST}">not a download button</a>
"""


def test_every_marked_button_points_at_that_versions_file():
    out = links.apply(PAGE, "v0.2.2")
    base = "https://github.com/gregsvieira/chakmati/releases/download/v0.2.2/"
    assert f'data-dl="mac-arm64" href="{base}Chakmati-0.2.2-mac-arm64.pkg"' in out
    assert f'data-dl="mac-x64" href="{base}Chakmati-0.2.2-mac-x64.pkg"' in out
    assert f'data-dl="win-x64" href="{base}Chakmati-0.2.2-win-x64.exe"' in out
    assert f'data-dl="linux-x64" href="{base}Chakmati-0.2.2-linux-amd64.deb"' in out


def test_links_without_the_marker_are_left_alone():
    assert f'<a href="{LATEST}">not a download button</a>' in links.apply(PAGE, "v0.2.2")


def test_running_twice_with_the_same_tag_changes_nothing():
    once = links.apply(PAGE, "v0.2.2")
    assert links.apply(once, "v0.2.2") == once


def test_a_newer_tag_replaces_the_older_one():
    out = links.apply(links.apply(PAGE, "v0.2.2"), "v0.3.0")
    assert "v0.2.2" not in out and "Chakmati-0.3.0-mac-arm64.pkg" in out


@pytest.mark.parametrize("tag", ["0.2.2", "v0.2", "latest", "v0.2.2-rc1", ""])
def test_a_tag_that_is_not_a_version_is_refused(tag):
    with pytest.raises(ValueError):
        links.apply(PAGE, tag)


def test_an_unknown_key_is_an_error_not_a_silent_skip():
    with pytest.raises(ValueError):
        links.apply(f'<a data-dl="amiga" href="{LATEST}">x</a>', "v0.2.2")


def test_the_real_page_has_all_four_buttons_marked():
    page = (links.PAGE).read_text(encoding="utf-8")
    for key in links.FILES:
        assert f'data-dl="{key}"' in page
