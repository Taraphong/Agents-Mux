"""Conversation history storage.

Records are one JSON file per conversation under the history folder, written
atomically under a per-process lock and a cross-process file lock.
"""

import fcntl
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import HISTORY_LOCK_FILE, HISTORY_ROOT, HISTORY_ROOT_TEXT
from core.log import LOGGER, log_event
from core.paths import normalized_path_under

HISTORY_LOCK = threading.Lock()


def find_history_file(conversation_id: str) -> Path | None:
    """Find the history file that stores one conversation id.

    The same conversation can exist more than once when an older build wrote a
    relative path under ``history/history``. The newest copy holds the latest
    writes, so pick that one instead of relying on directory order.
    """
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    matches = list(HISTORY_ROOT.rglob(f"*_{conversation_id}.json"))
    if len(matches) <= 1:
        return matches[0] if matches else None

    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(matches, key=modified)
class HistoryConflict(Exception):
    """Raised when an append targets a conversation record that was replaced."""
class HistoryLocked(Exception):
    """Raised when a write tries to replace a locked conversation record."""
@contextmanager
def history_mutation_lock():
    """Serialize history mutations in this process and across processes.

    HISTORY_LOCK keeps threads in this process apart; the file lock extends the
    same guarantee to other worker processes that share HISTORY_ROOT.
    """
    with HISTORY_LOCK:
        HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(HISTORY_LOCK_FILE, "a+", encoding="utf-8")
        except OSError as exc:
            # Without the cross-process lock a mutation could race another
            # writer, so fail the request instead of proceeding unlocked.
            log_event("history.error", "Could not open the history lock file", error=str(exc))
            raise
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
def history_generation(record: dict[str, Any]) -> str | None:
    """Return the identity token callers use to bind appends to a record."""
    value = record.get("generation") or record.get("created_at")
    return value if isinstance(value, str) and value else None
def save_history(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a conversation history file and return its record."""
    with history_mutation_lock():
        return _save_history_unlocked(payload)
def history_record_path(path: Path) -> Path:
    """Return *path* normalized and confirmed inside the history folder.

    The path is made absolute first: a path read back from disk by
    ``find_history_file`` is relative (``history/<date>/<file>.json``), and
    ``normalized_path_under`` joins its input to the root, so passing it as is
    would write ``history/history/<date>/<file>.json`` and leave every read
    looking at a stale copy.
    """
    return normalized_path_under(os.path.abspath(str(path)), HISTORY_ROOT, "Invalid history path")
def _write_history_record(path: Path, record: dict[str, Any]) -> None:
    """Write one history record atomically so readers never see a partial file."""
    path = history_record_path(path)
    record_text = os.path.normpath(str(path))
    if not record_text.startswith(HISTORY_ROOT_TEXT + os.sep):
        raise ValueError("Invalid history path")
    path = Path(record_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
def _save_history_unlocked(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or replace a history record while HISTORY_LOCK is held."""
    conversation_id = payload.get("id") or ""
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        conversation_id = str(uuid.uuid4())
    now = datetime.now().astimezone()
    existing = find_history_file(conversation_id)
    existing_record = {}
    if existing and existing.exists():
        try:
            parsed = json.loads(existing.read_text(encoding="utf-8"))
            existing_record = parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError):
            existing_record = {}
    if existing_record.get("locked"):
        # The lock must protect the stored messages too, not only rename/delete.
        raise HistoryLocked("This conversation is locked; unlock it before saving over it")
    messages = list(payload.get("messages") or [])
    existing_messages = existing_record.get("messages") if isinstance(existing_record.get("messages"), list) else []
    base_count = payload.get("base_message_count")
    if isinstance(base_count, int) and not isinstance(base_count, bool) and 0 <= base_count <= len(existing_messages):
        # The caller built its snapshot from the first base_count messages. Keep any
        # messages appended or saved after that snapshot instead of overwriting them.
        if len(messages) <= len(existing_messages) and all(
            left == right for left, right in zip(messages, existing_messages)
        ):
            # A retry of an already-merged snapshot must not append the tail twice.
            messages = list(existing_messages)
        else:
            known_ids = {
                message.get("message_id")
                for message in messages
                if isinstance(message, dict) and message.get("message_id")
            }
            for message in existing_messages[base_count:]:
                message_id = message.get("message_id") if isinstance(message, dict) else None
                if message_id and message_id in known_ids:
                    continue
                if message in messages:
                    continue
                messages.append(message)
                if message_id:
                    known_ids.add(message_id)
    created_at = (
        payload.get("created_at")
        or existing_record.get("created_at")
        or now.isoformat(timespec="seconds")
    )
    # New records (no existing file) get a generation; legacy records keep theirs.
    if not existing_record:
        record_generation = str(uuid.uuid4())
    else:
        # Preserve the existing generation so appends that were started against
        # the old record still validate against it.
        record_generation = existing_record.get("generation")
    path = existing or HISTORY_ROOT / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_{conversation_id}.json"
    path = history_record_path(path)
    raw_title = payload.get("title")
    existing_title = (
        existing_record.get("title") if isinstance(existing_record.get("title"), str) else ""
    )
    title = (
        raw_title.strip()[:100]
        if isinstance(raw_title, str) and raw_title.strip()
        else existing_title.strip()[:100] or "New conversation"
    )
    record = {
        "id": conversation_id,
        "title": title,
        "created_at": created_at,
        "updated_at": now.isoformat(timespec="seconds"),
        "locked": bool(existing_record.get("locked", False)),
        "pinned": bool(existing_record.get("pinned", False)),
        "messages": messages,
        "generation": record_generation,
    }
    _write_history_record(path, record)
    return record
def append_history_messages(conversation_id: str, new_messages: list[dict[str, Any]], generation: str | None = None) -> dict[str, Any] | None:
    """Append messages to an existing conversation, or return None if it is gone.

    The read-modify-write happens under HISTORY_LOCK, so an append can never
    recreate a conversation deleted at the same time. Messages carrying a
    message_id are appended idempotently. The optional *generation* parameter
    must match the generation stored in the record; otherwise HistoryConflict
    is raised so the caller can retry or stop instead of appending to stale data.
    """
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if path is None or not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        if record.get("locked"):
            # Locked conversations reject edits and deletes; appending must not
            # become a way around that protection.
            raise HistoryLocked("This conversation is locked")
        record_generation = history_generation(record)
        if generation is not None and record_generation != generation:
            raise HistoryConflict(
                f"Record generation {record_generation!r} does not match append generation {generation!r}"
            )
        record_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        known_ids = {
            message.get("message_id")
            for message in record_messages
            if isinstance(message, dict) and message.get("message_id")
        }
        added = False
        for message in new_messages:
            if not isinstance(message, dict):
                continue
            message_id = message.get("message_id")
            if message_id and message_id in known_ids:
                continue
            record_messages.append(message)
            if message_id:
                known_ids.add(message_id)
            added = True
        if added:
            record["messages"] = record_messages
            record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _write_history_record(path, record)
        return record
def save_discord_turn(conversation_id: str, title: str, context_messages: list[dict[str, Any]]) -> None:
    """Persist only the newest Discord exchange so earlier history survives.

    The Discord context is a bounded deque, so saving the whole deque would
    truncate the conversation record on every reply.
    """
    turn = [
        message for message in context_messages[-2:]
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
    ]
    if not turn:
        return
    if load_history_record(conversation_id):
        try:
            append_history_messages(conversation_id, turn)
        except HistoryLocked:
            # A locked conversation must not be written by an automated turn.
            log_event("discord.locked", "Skipped a turn for a locked conversation", conversation=conversation_id)
        return
    save_history({"id": conversation_id, "title": title, "messages": list(context_messages)})
def load_history_record(conversation_id: str) -> dict[str, Any]:
    """Read one conversation history record, or an empty dict if missing."""
    path = find_history_file(conversation_id)
    if path is None or not path.exists():
        return {}
    return read_history_file(path) or {}
def read_history_file(path: Path) -> dict[str, Any] | None:
    """Read one history file, or None when it is unreadable or malformed."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        # Only the file name is logged: conversation content must stay private.
        LOGGER.warning("Could not read a history file (%s): %s", path.name, exc)
        return None
    return record if isinstance(record, dict) else None
def find_schedule_conversation_id(job_id: str) -> str:
    """Find the newest history conversation that a scheduled job already wrote."""
    if not job_id or not HISTORY_ROOT.exists():
        return ""
    best: tuple[str, str] | None = None
    for path in HISTORY_ROOT.rglob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("messages"), list):
            continue
        if not any(isinstance(message, dict) and message.get("schedule_id") == job_id for message in record["messages"]):
            continue
        conversation_id = record.get("id")
        if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
            continue
        updated_at = str(record.get("updated_at") or "")
        if best is None or updated_at > best[1]:
            best = (conversation_id, updated_at)
    return best[0] if best else ""
