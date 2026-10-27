"""What every HTTP router of the engine shares: the Server-Sent Events framing and the "only the app's own window" guard."""

import json

from fastapi import Header, HTTPException

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def ui_only(x_liteagent_ui: str | None = Header(default=None)) -> None:
    # Writes are decided by the user's own UI. A custom header cannot be sent by a web page on another
    # origin without a CORS preflight, which this server never grants, so a random site cannot approve.
    if x_liteagent_ui != "1":
        raise HTTPException(status_code=403, detail="approval must come from the user interface (X-LiteAgent-UI: 1)")
