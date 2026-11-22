"""Per-client rate limits for the JSON API.

Each bucket keeps its own budget and window, so a chat turn cannot spend the
tools or test allowance and a burst is refused with a localized 429.
"""

import threading
import time

from flask import jsonify, request

from core.auth import current_auth_session
from core.log import log_event
from core.messages import request_language, status_message

API_RATE_LIMITS: dict[str, list[float]] = {}


API_RATE_LOCK = threading.Lock()
def api_rate_limited(bucket: str, client: str, limit: int, window: float = 60.0) -> bool:
    """Return True when *client* already used its budget for *bucket*."""
    now = time.time()
    key = f"{bucket}|{client}"
    with API_RATE_LOCK:
        if len(API_RATE_LIMITS) > 2000:
            API_RATE_LIMITS.clear()
        stamps = [stamp for stamp in API_RATE_LIMITS.get(key, []) if now - stamp < window]
        if len(stamps) >= limit:
            API_RATE_LIMITS[key] = stamps
            return True
        stamps.append(now)
        API_RATE_LIMITS[key] = stamps
    return False
# Per-minute budgets for the endpoints that cost money or touch the machine.
API_RATE_BUDGETS = {"chat": 30, "tools": 60, "test": 10}
def rate_limit_response(bucket: str):
    """Answer 429 when the caller exceeded the budget for *bucket*.

    A paired device is identified by its session id, so a spoofed
    X-Forwarded-For cannot hand one caller a fresh budget on every request.
    """
    session = current_auth_session() or {}
    client = str(session.get("id") or request.remote_addr or "unknown")
    if not api_rate_limited(bucket, client, API_RATE_BUDGETS[bucket]):
        return None
    log_event("security.rate_limited", "Rejected a request over the rate budget", bucket=bucket)
    return jsonify({"ok": False, "error": status_message(request_language(), "rate_limited")}), 429
