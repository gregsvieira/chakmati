"""The data folder was called ~/.lite-agent; it is ~/.chakmati-agent now. On the first start after the change the old folder is MOVED (not copied), so nothing a
person already has is lost: the keys and tokens, the WhatsApp login (the browser profile of the OpenWA session is renamed with the session), the Home Assistant settings."""

import logging
import os

log = logging.getLogger(__name__)

LEGACY_DATA_DIR = "~/.lite-agent"
DATA_DIR = "~/.chakmati-agent"
LEGACY_SESSION = "_IGNORE_lite-agent"   # the Chrome profile OpenWA keeps for its session, named after the session
SESSION = "_IGNORE_chakmati-agent"


def data_dir() -> str:
    """The folder the Chakmati keeps its data in: the new one, or the old one only while it has not been moved (so a move that could not be done never hides the data)."""
    new, old = os.path.expanduser(DATA_DIR), os.path.expanduser(LEGACY_DATA_DIR)
    return old if os.path.isdir(old) and not os.path.lexists(new) else new


def _rename_session(base: str) -> None:
    old, new = os.path.join(base, LEGACY_SESSION), os.path.join(base, SESSION)
    if os.path.isdir(old) and not os.path.lexists(new):
        os.rename(old, new)


def migrate_data_dir(old: str | None = None, new: str | None = None) -> bool:
    """Moves the old data folder to the new name. True when it moved. Never raises: when it cannot, the old folder keeps being used (see `data_dir`)."""
    old = old or os.path.expanduser(LEGACY_DATA_DIR)
    new = new or os.path.expanduser(DATA_DIR)
    if not os.path.isdir(old) or os.path.lexists(new):
        return False
    try:
        os.rename(old, new)
    except OSError:
        log.exception("could not move %s to %s: the old folder stays in use", old, new)
        return False
    openwa = os.path.join(new, "openwa")
    try:
        _rename_session(os.path.join(openwa, "run"))
        if os.path.isdir(openwa):
            for name in os.listdir(openwa):
                if name.startswith("session-backup-"):
                    _rename_session(os.path.join(openwa, name))
    except OSError:
        log.exception("could not rename the WhatsApp session folder")
    return True
