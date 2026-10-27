"""Manual check of the macOS backend against the real Calendar.app (asks for permission on first run).

    uv run python -m liteagent.agenda.mac_check

It prints only counts, creates one clearly named test event for tomorrow at 03:00 and deletes it again.
"""

from datetime import datetime, timedelta

from .mac import MacEventKitProvider
from .models import NewEvent

TITLE = "Chakmati TESTE (pode apagar)"


def main() -> None:
    print("requesting Calendar access (answer the macOS dialog if it appears)...", flush=True)
    provider = MacEventKitProvider()
    now = datetime.now().astimezone()
    print(f"access OK; writable calendars: {len(provider.list_calendars())}")
    print(f"events in the next 7 days: {len(provider.list_events(now, now + timedelta(days=7)))}")

    start = (now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    created = provider.create_event(NewEvent(TITLE, start, start + timedelta(minutes=15), location="teste", notes="criado pelo Chakmati"))
    try:
        found = [e for e in provider.list_events(start - timedelta(minutes=1), start + timedelta(minutes=20)) if e.id == created.id]
        print(f"created and found again: {bool(found)} (title ok: {found[0].title == TITLE if found else False})")
    finally:
        provider.delete_event(created.id)
    left = [e for e in provider.list_events(start - timedelta(minutes=1), start + timedelta(minutes=20)) if e.title == TITLE]
    print(f"deleted; test events left over: {len(left)}")


if __name__ == "__main__":
    main()
