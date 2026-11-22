"""Pairing keys and device sessions.

Only a hash of every pairing key and session token is stored, and the store is
written atomically with owner-only permissions. The Flask request is read for
the session cookies; nothing here knows about the application object.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from flask import request

from core.config import (
    AUTH_ENABLED,
    AUTH_FILE,
    AUTH_KEY_ALPHABET,
    AUTH_KEY_LENGTH,
    AUTH_PAIRING_FAILURE_WINDOW,
    AUTH_PAIRING_MAX_FAILURES,
    AUTH_PAIRING_TTL_MINUTES,
    AUTH_SESSION_COOKIE_NAMES,
    AUTH_SESSION_DAYS,
)


AUTH_LOCK = threading.Lock()
AUTH_PAIRING_FAILURES: dict[str, list[float]] = {}


def empty_auth_state() -> dict[str, Any]:
    """Return the empty shape of the pairing/session store."""
    return {"version": 1, "pairing_keys": [], "sessions": []}


def load_auth_state() -> dict[str, Any]:
    """Load the pairing/session store, tolerating a missing or broken file."""
    if not AUTH_FILE.exists():
        return empty_auth_state()
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_auth_state()
    state = empty_auth_state()
    if not isinstance(data, dict):
        return state
    for field in ("pairing_keys", "sessions"):
        raw = data.get(field)
        if isinstance(raw, list):
            state[field] = [item for item in raw if isinstance(item, dict)]
    return state


def save_auth_state(state: dict[str, Any]) -> None:
    """Persist the pairing/session store atomically with owner-only permissions."""
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = AUTH_FILE.with_suffix(".tmp")
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(temp_path, AUTH_FILE)


def hash_auth_token(value: str) -> str:
    """Hash a pairing key or session token before it is stored on disk."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def no_store(response):
    """Mark an identity-dependent response so proxies and browsers never cache it."""
    response.headers["Cache-Control"] = "no-store"
    return response


def auth_now() -> datetime:
    """Return the current local time used for pairing/session timestamps."""
    return datetime.now().astimezone()


def auth_timestamp(moment: datetime) -> str:
    """Serialize a timestamp in the same ISO shape used elsewhere in the app."""
    return moment.isoformat(timespec="seconds")


def auth_expired(record: dict[str, Any], now: datetime) -> bool:
    """Report whether a stored key or session record has passed its expiry."""
    try:
        return datetime.fromisoformat(str(record.get("expires_at") or "")) <= now
    except (TypeError, ValueError):
        return True


def prune_auth_state(state: dict[str, Any], now: datetime) -> None:
    """Drop expired keys and sessions so the store does not grow forever."""
    state["pairing_keys"] = [item for item in state["pairing_keys"] if not auth_expired(item, now)]
    state["sessions"] = [item for item in state["sessions"] if not auth_expired(item, now)]


def normalize_pairing_key(raw_key: Any) -> str:
    """Normalize a client-supplied key by stripping separators and case."""
    cleaned = re.sub(r"[^0-9A-Za-z]", "", str(raw_key or "")).upper()
    return cleaned if len(cleaned) == AUTH_KEY_LENGTH else ""


def format_pairing_key(key: str) -> str:
    """Group a pairing key into readable blocks, e.g. ABCD-EFGH-JKLM."""
    return "-".join(key[index:index + 4] for index in range(0, len(key), 4))


def generate_pairing_key(label: str = "") -> dict[str, Any]:
    """Create a single-use pairing key; only its hash is written to disk."""
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        while True:
            key = "".join(secrets.choice(AUTH_KEY_ALPHABET) for _ in range(AUTH_KEY_LENGTH))
            digest = hash_auth_token(key)
            if not any(hmac.compare_digest(str(item.get("hash") or ""), digest) for item in state["pairing_keys"]):
                break
        record = {
            "id": secrets.token_hex(8),
            "hash": digest,
            "label": str(label or "").strip()[:60],
            "created_at": auth_timestamp(now),
            "expires_at": auth_timestamp(now + timedelta(minutes=AUTH_PAIRING_TTL_MINUTES)),
        }
        state["pairing_keys"].append(record)
        save_auth_state(state)
    return {"key": format_pairing_key(key), "id": record["id"], "expires_at": record["expires_at"], "ttl_minutes": AUTH_PAIRING_TTL_MINUTES}


def consume_pairing_key(raw_key: Any) -> bool:
    """Validate and burn one pairing key so it cannot be reused."""
    key = normalize_pairing_key(raw_key)
    if not key:
        return False
    digest = hash_auth_token(key)
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        matched = False
        remaining = []
        for item in state["pairing_keys"]:
            if not matched and hmac.compare_digest(str(item.get("hash") or ""), digest):
                matched = True
                continue
            remaining.append(item)
        state["pairing_keys"] = remaining
        save_auth_state(state)
    return matched


def pairing_attempt_allowed(client_ip: str) -> bool:
    """Rate-limit pairing attempts per client address."""
    now = time.time()
    with AUTH_LOCK:
        recent = [stamp for stamp in AUTH_PAIRING_FAILURES.get(client_ip, []) if now - stamp < AUTH_PAIRING_FAILURE_WINDOW]
        AUTH_PAIRING_FAILURES[client_ip] = recent
        return len(recent) < AUTH_PAIRING_MAX_FAILURES


def record_pairing_failure(client_ip: str) -> None:
    """Remember a failed pairing attempt for rate limiting."""
    with AUTH_LOCK:
        AUTH_PAIRING_FAILURES.setdefault(client_ip, []).append(time.time())
        if len(AUTH_PAIRING_FAILURES) > 500:
            for stale_ip in [ip for ip, stamps in AUTH_PAIRING_FAILURES.items() if not stamps]:
                AUTH_PAIRING_FAILURES.pop(stale_ip, None)


def create_auth_session(label: str = "", user_agent: str = "", client_ip: str = "") -> str:
    """Create a paired-device session and return its raw cookie token once."""
    token = secrets.token_urlsafe(32)
    now = auth_now()
    record = {
        "id": secrets.token_hex(8),
        "token_hash": hash_auth_token(token),
        "label": str(label or "").strip()[:60] or "Connected device",
        "user_agent": str(user_agent or "")[:200],
        "ip": str(client_ip or "")[:80],
        "created_at": auth_timestamp(now),
        "last_seen_at": auth_timestamp(now),
        "expires_at": auth_timestamp(now + timedelta(days=AUTH_SESSION_DAYS)),
    }
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        state["sessions"].append(record)
        save_auth_state(state)
    return token


def auth_session_tokens() -> list[str]:
    """Return the session tokens this request carries, one per cookie name."""
    return [
        token
        for name in AUTH_SESSION_COOKIE_NAMES
        if (token := request.cookies.get(name, ""))
    ]


def current_auth_session() -> dict[str, Any] | None:
    """Resolve one of the request cookies to a live paired-device session."""
    tokens = auth_session_tokens()
    if not tokens:
        return None
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        for token in tokens:
            digest = hash_auth_token(token)
            for item in state["sessions"]:
                if not hmac.compare_digest(str(item.get("token_hash") or ""), digest):
                    continue
                if auth_expired(item, now):
                    continue
                try:
                    recently_seen = (now - datetime.fromisoformat(str(item.get("last_seen_at") or ""))).total_seconds() <= 60
                except (TypeError, ValueError):
                    recently_seen = False
                if not recently_seen:
                    item["last_seen_at"] = auth_timestamp(now)
                    save_auth_state(state)
                return dict(item)
    return None


def revoke_auth_session(session_id: str) -> bool:
    """Revoke one paired device by its session id."""
    with AUTH_LOCK:
        state = load_auth_state()
        remaining = [item for item in state["sessions"] if item.get("id") != session_id]
        if len(remaining) == len(state["sessions"]):
            return False
        state["sessions"] = remaining
        save_auth_state(state)
    return True


def revoke_all_auth_sessions() -> int:
    """Revoke every paired device and return how many were removed."""
    with AUTH_LOCK:
        state = load_auth_state()
        count = len(state["sessions"])
        state["sessions"] = []
        save_auth_state(state)
    return count


def active_auth_session_count() -> int:
    """Count sessions that are still valid, pruning expired records."""
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        save_auth_state(state)
        return len(state["sessions"])


def bootstrap_pairing_key() -> dict[str, Any] | None:
    """Create the first-run key when no device has been paired yet."""
    if not AUTH_ENABLED or active_auth_session_count():
        return None
    return generate_pairing_key("server")


def print_pairing_banner(record: dict[str, Any] | None) -> None:
    """Print a pairing key to the server console, never to the app log file."""
    if not record:
        return
    print(
        "\n" + "=" * 62 + "\n"
        f"  Pairing Key: {record['key']}\n"
        f"  valid until {record['expires_at']} and single use\n"
        "  on the client, open /pair and enter this key\n"
        + "=" * 62 + "\n",
        flush=True,
    )
