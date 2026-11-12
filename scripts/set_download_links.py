"""Point the download buttons of the site at the installers of one release.

    python scripts/set_download_links.py v0.2.2 [docs/site/index.html]

Every element of the page marked with `data-dl="<key>"` gets the direct link to that release's file
(https://github.com/<repo>/releases/download/<tag>/<file>), so a button downloads the exact version instead of opening the releases page.
The file names are the ones electron-builder produces (`artifactName` in desktop/electron-builder.yml).
Run by the release workflow after the release is published; running it twice with the same tag changes nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = "gregsvieira/chakmati"
PAGE = Path(__file__).resolve().parent.parent / "docs" / "site" / "index.html"

# data-dl key -> installer file name, given the version without the "v".
FILES = {
    "mac-arm64": "Chakmati-{v}-mac-arm64.pkg",
    "mac-x64": "Chakmati-{v}-mac-x64.pkg",
    "win-x64": "Chakmati-{v}-win-x64.exe",
    "linux-x64": "Chakmati-{v}-linux-amd64.deb",
}

_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_LINK = re.compile(r'(data-dl="(?P<key>[a-z0-9-]+)"\s+href=")[^"]*(")')


def link(tag: str, key: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/{FILES[key].format(v=tag[1:])}"


def apply(html: str, tag: str) -> str:
    """The page with every `data-dl` link pointing at `tag`. An unknown key is an error, not a silent skip."""
    if not _TAG.match(tag):
        raise ValueError(f"not a release tag like v1.2.3: {tag!r}")

    def swap(m: re.Match[str]) -> str:
        key = m.group("key")
        if key not in FILES:
            raise ValueError(f"unknown data-dl key: {key!r}")
        return f"{m.group(1)}{link(tag, key)}{m.group(3)}"

    return _LINK.sub(swap, html)


def main(argv: list[str]) -> int:
    if not 1 <= len(argv) <= 2:
        print(__doc__)
        return 2
    page = Path(argv[1]) if len(argv) == 2 else PAGE
    before = page.read_text(encoding="utf-8")
    after = apply(before, argv[0])
    if after == before:
        print("links already point at", argv[0])
        return 0
    page.write_text(after, encoding="utf-8")
    print("links now point at", argv[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
