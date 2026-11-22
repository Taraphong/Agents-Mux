"""The in-memory and on-disk diagnostic event log.

The rolling window keeps long-running servers off the heap, and every record is
redacted before it is stored. The redactor is installed by app.py, so this
module never imports the application.
"""

import json
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any, Callable

from core.config import LOG_FILE
from core.env import env_int

APP_LOGS: deque[dict[str, Any]] = deque(maxlen=env_int("AI_WEB_LOG_MAX_ENTRIES", 1000, 50))
APP_LOG_LOCK = threading.Lock()
LOGGER = logging.getLogger("ai-web")

# Replaced by app.py through set_redactor(); identity until then.
_REDACT: Callable[[str], str] = lambda text: text


def set_redactor(redact: Callable[[str], str]) -> None:
    """Install the application's secret redactor for log records."""
    global _REDACT
    _REDACT = redact


# The in-memory log is a rolling window: a server that runs for weeks on Termux
# must not keep every event in RAM, so only the newest entries are retained.
APP_LOGS: deque[dict[str, Any]] = deque(maxlen=env_int("AI_WEB_LOG_MAX_ENTRIES", 1000, 50))
APP_LOG_LOCK = threading.Lock()
LOGGER = logging.getLogger("ai-web")


def load_persisted_logs() -> None:
    """Restore the append-only diagnostic trail after a server restart."""
    if not LOG_FILE.exists():
        return
    try:
        with LOG_FILE.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    APP_LOGS.append(record)
    except OSError as exc:
        LOGGER.warning("Could not read the persisted log file: %s", exc)


def log_event(event: str, message: str, **details: Any) -> None:
    """Append a UI-readable diagnostic record without storing secrets."""
    safe_details = {}
    for key, value in details.items():
        if key.lower() in {"api_key", "authorization", "token", "content"}:
            continue
        safe_details[key] = _REDACT(str(value))[:500]
    record = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": str(event)[:60],
        "message": _REDACT(str(message))[:500],
        "details": safe_details,
    }
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with APP_LOG_LOCK:
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(serialized)
            APP_LOGS.append(record)
    except OSError as exc:
        LOGGER.warning("Could not write the persisted log: %s", exc)
        with APP_LOG_LOCK:
            APP_LOGS.append(record)
    # Only the event name reaches the plain-text console log. The message and its
    # details stay in APP_LOGS/log file below, where the redactor has run, so a
    # credential can never be written here as clear text.
    LOGGER.info("%s", event)
