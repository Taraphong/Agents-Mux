"""Background memory consolidation for the AI Web app.

The engine turns raw chat history into long-term memory in three phases:

* **Light Sleep** - ingest new chat history, remove exact and near duplicates,
  write the day's notes to ``memory/YYYY-MM-DD.md`` and stage candidates.
* **REM Sleep** - look back over the configured window, group repeated topics
  into clusters and label their themes.
* **Deep Sleep** - score every candidate, promote only the ones above the
  threshold into ``MEMORY.md`` and write a readable ``DREAMS.md`` entry.

Storage is deliberately two-tier: plain Markdown the user can open in Obsidian,
plus a local SQLite file that holds scores, vectors and the keyword index. No
database server is involved.

Everything that decides *what* is remembered (normalising text, de-duplicating,
scoring, thresholding) runs here in local code. Only the semantic summary - the
theme label and importance rating - is asked from the configured model, and the
whole LLM pass is optional so the feature still works offline.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
import unicodedata
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

def _location(name: str, default: str) -> Path:
    """Resolve a configured path relative to the project folder."""
    value = str(os.getenv(name, "") or "").strip()
    path = Path(value or default)
    return path if path.is_absolute() else Path(os.path.abspath(path))


MEMORY_DIR = _location("AI_WEB_MEMORY_DIR", "memory")
MEMORY_FILE = _location("AI_WEB_MEMORY_FILE", "MEMORY.md")
DREAMS_FILE = _location("AI_WEB_DREAMS_FILE", "DREAMS.md")
DATABASE_FILE = _location("AI_WEB_MEMORY_DB", ".app-memory.db")
HISTORY_ROOT = _location("AI_WEB_HISTORY_DIR", "history")
VEC_EXTENSION_FILE = _location("AI_WEB_MEMORY_VEC_EXT", "vendor/sqlite-vec/vec0.so")

EMBED_DIM = 256
MAX_MESSAGE_CHARS = 4_000
MAX_DAILY_MESSAGES = 40
MAX_CANDIDATES_PER_RUN = 400
MAX_LLM_ITEMS = 25
MAX_LLM_CALLS = 4
MEMORY_HEADING = "## Long-term memory"
DREAMS_HEADING = "## Dreams"
DREAMS_MAX_BYTES = 400_000

DEFAULT_MEMORY_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "schedule": "0 3 * * *",
    "lookback_days": 7,
    "threshold": 0.65,
    "idle_minutes": 15,
    "max_items": 25,
    "include_locked": False,
    "llm": True,
    "provider": "",
    "model": "",
    "base_url": "",
    "window_end": "06:00",
    "dedupe": 0.92,
}

# Words that carry no topic on their own. Both languages are listed because the
# conversation itself may be Thai, English or a mix of the two.
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "your", "our", "with",
    "this", "that", "these", "those", "from", "have", "has", "had", "was",
    "were", "will", "would", "can", "could", "should", "about", "into", "than",
    "then", "there", "here", "what", "when", "where", "which", "who", "how",
    "all", "any", "one", "two", "get", "got", "use", "used", "using", "just",
    "also", "very", "more", "most", "some", "such", "only", "like", "make",
    "made", "need", "want", "please", "thank", "thanks", "ok", "okay", "yes",
    "และ", "หรือ", "ที่", "ใน", "ของ", "ให้", "ได้", "ไป", "มา", "กับ", "ก็",
    "จะ", "ไม่", "เป็น", "มี", "ทำ", "ใช้", "ครับ", "ค่ะ", "นะ", "น่ะ", "ว่า",
    "แล้ว", "ยัง", "ต้อง", "อยาก", "ช่วย", "อัน", "นี้", "นั้น", "จาก", "แต่",
}

_EXPLICIT_RE = re.compile(
    r"(จำไว้|จำเอาไว้|อย่าลืม|ความจำ|remember (?:that|this)|note that|important[: ]|สำคัญ)",
    re.IGNORECASE,
)
_SLASH_RE = re.compile(r"^/[a-zก-๙][\w-]*(?:\s|$)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[0-9A-Za-z_]+|[\u0e00-\u0e7f]+")
_THAI_RE = re.compile(r"^[\u0e00-\u0e7f]+$")
_MEMORY_MARKER_RE = re.compile(
    r"<!-- mem:(?P<id>[0-9a-fA-F-]{36}) score=(?P<score>[0-9.]+) "
    r"date=(?P<date>[^ ]+) sources=(?P<sources>[^ ]*) -->\n"
    r"(?P<body>(?:(?!<!-- mem:).)*)",
    re.DOTALL,
)
_RUN_LOCK = threading.Lock()
_VEC_LOCK = threading.Lock()
_VEC_STATE: dict[str, Any] = {"checked": False, "ready": False, "error": ""}
_LAST_ACTIVITY = time.time()
_ACTIVITY_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def now_local() -> datetime:
    """Return the current local time with a timezone attached."""
    return datetime.now().astimezone()


def _iso(value: datetime | None = None) -> str:
    """Format a timestamp the way the rest of the app stores them."""
    return (value or now_local()).isoformat(timespec="seconds")


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp without letting a bad record break a run."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def touch_activity() -> None:
    """Record that the user is using the app, so the night run waits."""
    global _LAST_ACTIVITY
    with _ACTIVITY_LOCK:
        _LAST_ACTIVITY = time.time()


def idle_seconds() -> float:
    """Seconds since the last recorded user activity."""
    with _ACTIVITY_LOCK:
        return max(0.0, time.time() - _LAST_ACTIVITY)


def is_running() -> bool:
    """Whether a consolidation run holds the engine lock right now."""
    return _RUN_LOCK.locked()


def _log(event: str, message: str, **details: Any) -> None:
    """Write to the app log without importing app at module load time."""
    try:
        from app import log_event  # imported lazily: app imports this module

        log_event(event, message, **details)
    except Exception:
        pass


# Shapes that are almost certainly a credential even when the key is not one
# this installation knows about (a key pasted from another project, a token in
# a screenshot). Memory is long-lived, so it is better to lose the string.
_SECRET_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def _redact(text: str) -> str:
    """Strip credentials before text is stored, indexed or summarised."""
    value = str(text or "")
    try:
        from app import redact_secrets

        value = redact_secrets(value)
    except Exception:
        pass
    for pattern in _SECRET_SHAPES:
        value = pattern.sub("[redacted]", value)
    return value


def normalize_text(text: str) -> str:
    """Normalise text for storage and display, keeping URLs intact."""
    # NFC, never NFKC: compatibility normalisation splits Thai SARA AM into
    # NIKHAHIT + SARA AA, which corrupts every Thai sentence it touches.
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()[:MAX_MESSAGE_CHARS]


def compare_text(text: str) -> str:
    """Strip noise that changes per message but not meaning.

    A URL, a timestamp or a run of spaces makes two otherwise identical notes
    look different. Storage keeps the original text (a remembered link stays
    usable); hashing and embeddings use this version.
    """
    value = _URL_RE.sub(" ", normalize_text(text))
    return re.sub(r"\s+", " ", value).strip()[:MAX_MESSAGE_CHARS]


def message_text(message: Any) -> str:
    """Flatten a stored chat message (text or multimodal parts) to plain text."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _hash(text: str) -> str:
    """Stable content hash used to collapse repeated messages."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    """Split text into comparable tokens, expanding Thai runs into n-grams."""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(compare_text(text).lower()):
        token = match.group(0)
        if _THAI_RE.match(token):
            if len(token) <= 3:
                tokens.append(token)
            else:
                tokens.extend(token[i : i + 3] for i in range(0, len(token) - 2))
        elif len(token) > 2 and token not in STOPWORDS:
            tokens.append(token)
    return tokens


def embed(text: str) -> list[float]:
    """Build a deterministic local embedding with the hashing trick.

    This is intentionally dependency-free: it runs on a phone, never calls the
    network and always returns the same vector for the same text, which is all
    the de-duplication and clustering steps need. It is a lexical embedding,
    not a semantic one - that trade-off is what keeps the feature 100% local.
    """
    vector = [0.0] * EMBED_DIM
    counts = Counter(_tokens(text))
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % EMBED_DIM
        sign = 1.0 if (value >> 9) & 1 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(item * item for item in vector))
    if norm:
        return [item / norm for item in vector]
    return vector


def _pack(vector: Iterable[float]) -> bytes:
    """Pack a float vector for storage in a BLOB column."""
    values = list(vector)
    return struct.pack(f"<{len(values)}f", *values)


def _unpack(blob: Any) -> list[float]:
    """Read a packed vector back, tolerating NULL and short values."""
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return []
    size = len(blob) // 4
    return list(struct.unpack(f"<{size}f", blob[: size * 4]))


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    """Cosine similarity of two already-normalised vectors."""
    a = list(left)
    b = list(right)
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


def keywords(text: str, limit: int = 6) -> list[str]:
    """Return the most repeated meaningful tokens of a text."""
    counts = Counter(token for token in _tokens(text) if len(token) > 2)
    return [token for token, _count in counts.most_common(limit)]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def normalize_settings(raw: Any) -> dict[str, Any]:
    """Clamp a settings payload into the shape the engine expects."""
    result = dict(DEFAULT_MEMORY_SETTINGS)
    if isinstance(raw, dict):
        result.update({key: raw[key] for key in raw if key in DEFAULT_MEMORY_SETTINGS})

    def as_bool(key: str) -> None:
        value = result.get(key)
        if isinstance(value, str):
            result[key] = value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            result[key] = bool(value)

    def as_int(key: str, default: int, minimum: int, maximum: int) -> None:
        try:
            value = int(result.get(key))
        except (TypeError, ValueError):
            value = default
        result[key] = max(minimum, min(maximum, value))

    def as_float(key: str, default: float, minimum: float, maximum: float) -> None:
        try:
            value = float(result.get(key))
        except (TypeError, ValueError):
            value = default
        result[key] = round(max(minimum, min(maximum, value)), 2)

    for key in ("enabled", "include_locked", "llm"):
        as_bool(key)
    as_int("lookback_days", 7, 1, 90)
    as_int("idle_minutes", 15, 0, 720)
    as_int("max_items", 25, 1, 200)
    as_float("threshold", 0.65, 0.0, 1.0)
    as_float("dedupe", 0.92, 0.5, 1.0)

    schedule = str(result.get("schedule") or DEFAULT_MEMORY_SETTINGS["schedule"]).strip()
    try:
        from app import validate_cron

        schedule = validate_cron(schedule)
    except ValueError:
        raise ValueError("memory_schedule_invalid") from None
    except Exception:
        pass
    result["schedule"] = schedule

    window_end = str(result.get("window_end") or DEFAULT_MEMORY_SETTINGS["window_end"]).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", window_end):
        window_end = DEFAULT_MEMORY_SETTINGS["window_end"]
    hour, minute = (int(part) for part in window_end.split(":"))
    result["window_end"] = f"{min(hour, 23):02d}:{min(minute, 59):02d}"

    result["provider"] = str(result.get("provider") or "").strip().lower()[:40]
    result["model"] = str(result.get("model") or "").strip()[:200]
    # An endpoint just for memory lets the chat keep using a cloud provider
    # while summaries run on a local llama-server/Ollama on this machine.
    result["base_url"] = str(result.get("base_url") or "").strip()[:300]
    return result


def settings_from(app_settings: Any) -> dict[str, Any]:
    """Read the engine settings out of the app's settings dictionary."""
    if isinstance(app_settings, dict):
        return normalize_settings(app_settings.get("memory"))
    return dict(DEFAULT_MEMORY_SETTINGS)


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _connect() -> sqlite3.Connection:
    """Open the index database with the pragmas a small device needs."""
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DATABASE_FILE), timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        os.chmod(DATABASE_FILE, 0o600)
    except OSError:
        pass
    return connection


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """Open a connection that commits and closes itself.

    ``with sqlite3.connect(...)`` only commits - it never closes - so using it
    everywhere leaked one file descriptor per status read and scheduler tick,
    which on a phone that runs for weeks ends in ``too many open files``.
    """
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _vec_state(connection: sqlite3.Connection) -> dict[str, Any]:
    """Load sqlite-vec once and remember whether the index can use it."""
    with _VEC_LOCK:
        if _VEC_STATE["checked"]:
            return dict(_VEC_STATE)
        state = {"checked": True, "ready": False, "error": ""}
        if VEC_EXTENSION_FILE.exists():
            try:
                connection.enable_load_extension(True)
                connection.load_extension(str(VEC_EXTENSION_FILE))
                state["ready"] = True
            except Exception as exc:  # noqa: BLE001 - capability probe
                state["error"] = str(exc)[:200]
            finally:
                try:
                    connection.enable_load_extension(False)
                except Exception:
                    pass
        else:
            state["error"] = "vec0.so not installed"
        _VEC_STATE.update(state)
        return dict(_VEC_STATE)


def ensure_storage() -> None:
    """Create the Markdown vault and the SQLite index if they do not exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(MEMORY_DIR, 0o700)
    except OSError:
        pass
    with _session() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source (
                conversation_id TEXT PRIMARY KEY,
                title TEXT,
                path TEXT,
                updated_at TEXT,
                message_count INTEGER DEFAULT 0,
                ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS message (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                norm_hash TEXT NOT NULL,
                ts TEXT,
                embedding BLOB,
                UNIQUE(conversation_id, idx, norm_hash)
            );
            CREATE TABLE IF NOT EXISTS candidate (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                message_idx INTEGER,
                text TEXT NOT NULL,
                context TEXT,
                norm_hash TEXT NOT NULL UNIQUE,
                cluster_id TEXT,
                occurrences INTEGER DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT,
                state TEXT DEFAULT 'staged',
                score REAL,
                breakdown TEXT,
                memory_id TEXT,
                embedding BLOB
            );
            CREATE TABLE IF NOT EXISTS cluster (
                id TEXT PRIMARY KEY,
                label TEXT,
                theme TEXT,
                keywords TEXT,
                size INTEGER,
                window_start TEXT,
                window_end TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS run (
                id TEXT PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                trigger TEXT,
                status TEXT,
                stats TEXT,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_message_conv ON message(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_candidate_state ON candidate(state, last_seen);
            CREATE INDEX IF NOT EXISTS idx_candidate_cluster ON candidate(cluster_id);
            """
        )
        fts_ready = False
        try:
            connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(text)")
            fts_ready = True
        except sqlite3.DatabaseError:
            fts_ready = False
        _set_meta(connection, "fts5_ready", "1" if fts_ready else "0")
        if _vec_state(connection)["ready"]:
            try:
                connection.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS message_vec USING vec0(embedding float[{EMBED_DIM}])"
                )
            except sqlite3.DatabaseError as exc:
                _VEC_STATE["ready"] = False
                _VEC_STATE["error"] = str(exc)[:200]


def _get_meta(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    """Read one metadata value."""
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    """Persist one metadata value."""
    connection.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def capabilities() -> dict[str, Any]:
    """Report what this machine can actually do, so the UI never guesses."""
    ensure_storage()
    with _session() as connection:
        version = sqlite3.sqlite_version
        fts5 = _get_meta(connection, "fts5_ready", "0") == "1"
        vec = _vec_state(connection)
    return {
        "sqlite_version": version,
        "fts5": fts5,
        "vector": "sqlite-vec" if vec["ready"] else "python-blob",
        "vector_error": "" if vec["ready"] else vec["error"],
        "embedding": "local-hashing-256",
    }


def safe_capabilities() -> dict[str, Any]:
    """Capabilities for a response: never let a probe fail a finished run."""
    try:
        return capabilities()
    except Exception:  # noqa: BLE001 - a report must not mask a success
        return {
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": False,
            "vector": "unknown",
            "vector_error": "capability probe failed",
            "embedding": "local-hashing-256",
        }


# --------------------------------------------------------------------------- #
# Light Sleep: ingest, de-duplicate, stage, daily notes
# --------------------------------------------------------------------------- #


def _iter_history() -> Iterable[tuple[Path, dict[str, Any]]]:
    """Yield every readable conversation record under the history folder."""
    if not HISTORY_ROOT.exists():
        return
    for path in sorted(HISTORY_ROOT.rglob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(record, dict) and isinstance(record.get("messages"), list):
            yield path, record


def _conversation_id(record: dict[str, Any], path: Path) -> str:
    """Return the conversation id, falling back to the file name."""
    value = record.get("id")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        return value
    match = re.search(r"([0-9a-fA-F-]{36})\.json$", path.name)
    return match.group(1) if match else _hash(str(path))[:36]


def _find_candidate(connection: sqlite3.Connection, norm_hash: str) -> sqlite3.Row | None:
    """Find a staged candidate with the same normalised text."""
    return connection.execute(
        "SELECT * FROM candidate WHERE norm_hash = ?", (norm_hash,)
    ).fetchone()


def _merge_candidate(connection: sqlite3.Connection, row: sqlite3.Row, timestamp: str) -> None:
    """Record another sighting of an already known candidate.

    A promoted entry must stay promoted and a forgotten one must stay forgotten:
    setting every sighting back to ``staged`` made the same sentence get scored
    (and skipped by the marker check) on every run for ever.
    """
    connection.execute(
        "UPDATE candidate SET occurrences = occurrences + 1, last_seen = ?, "
        "state = CASE WHEN state IN ('promoted', 'forgotten') THEN state ELSE 'staged' END "
        "WHERE id = ?",
        (timestamp, row["id"]),
    )


def _near_duplicate(
    connection: sqlite3.Connection, vector: list[float], threshold: float
) -> sqlite3.Row | None:
    """Return the closest recent candidate if it is a near duplicate."""
    # Comparing against a bounded, recent window keeps a first run over a long
    # history linear instead of quadratic on a phone.
    rows = connection.execute(
        "SELECT id, text, embedding FROM candidate "
        "WHERE state IN ('staged', 'rejected') AND embedding IS NOT NULL "
        "AND last_seen >= ? ORDER BY last_seen DESC LIMIT 300",
        (_iso(now_local() - timedelta(days=14)),),
    ).fetchall()
    best: sqlite3.Row | None = None
    best_score = threshold
    for row in rows:
        score = cosine(vector, _unpack(row["embedding"]))
        if score >= best_score:
            best_score = score
            best = row
    return best


def _stage_candidate(
    connection: sqlite3.Connection,
    *,
    conversation_id: str,
    message_index: int,
    text: str,
    context: str,
    timestamp: str,
    dedupe: float,
) -> str:
    """Stage a memory candidate, merging exact and near duplicates.

    Returns ``"new"``, ``"merged"`` or ``"skipped"`` for the run statistics.
    """
    normalized = normalize_text(_redact(text))
    comparison = compare_text(normalized)
    if len(comparison) < 20:
        return "skipped"
    norm_hash = _hash(comparison.lower())
    existing = _find_candidate(connection, norm_hash)
    if existing is not None:
        _merge_candidate(connection, existing, timestamp)
        return "merged"
    vector = embed(comparison)
    near = _near_duplicate(connection, vector, dedupe)
    if near is not None:
        _merge_candidate(connection, near, timestamp)
        return "merged"
    connection.execute(
        "INSERT INTO candidate (id, conversation_id, message_idx, text, context, norm_hash, "
        "occurrences, first_seen, last_seen, state, embedding) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'staged', ?)",
        (
            str(uuid.uuid4()),
            conversation_id,
            message_index,
            normalized[:MAX_MESSAGE_CHARS],
            _redact(context)[:600],
            norm_hash,
            timestamp,
            timestamp,
            _pack(vector),
        ),
    )
    return "new"


def _is_slash_command(text: str) -> bool:
    """Slash commands are commands, not things worth remembering."""
    return bool(_SLASH_RE.match(text.strip()))


def _day_note_path(date_text: str | None) -> Path:
    """Return the daily note path for an ISO date."""
    stamp = date_text if date_text and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text) else now_local().strftime("%Y-%m-%d")
    return MEMORY_DIR / f"{stamp}.md"


def _append_daily_note(
    conversation_id: str,
    title: str,
    date_text: str,
    updates: list[tuple[str, str]],
) -> bool:
    """Append one conversation's block to its day note, once.

    The block is guarded by a marker so a second run - or a run after the user
    edited the file in Obsidian - never duplicates or rewrites it. This is why
    the notes are safe to keep in a normal Markdown vault.
    """
    if not updates:
        return False
    path = _day_note_path(date_text)
    marker = f"<!-- conv:{conversation_id} -->"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False
    if marker in existing:
        return False
    lines = [f"## {title[:80]}", marker]
    for role, text in updates[-MAX_DAILY_MESSAGES:]:
        snippet = normalize_text(text).replace("\n", " ")
        lines.append(f"- **{role}:** {snippet[:220]}")
    lines.append("")
    prefix = "" if existing else f"# Notes for {date_text}\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(("\n" if existing and not existing.endswith("\n") else "") + prefix + "\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def light_sleep(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    run_id: str,
    dry_run: bool,
) -> dict[str, int]:
    """Ingest new messages, de-duplicate them, stage candidates and note the day."""
    stats = {
        "conversations": 0,
        "messages": 0,
        "new_candidates": 0,
        "merged_candidates": 0,
        "notes_written": 0,
    }
    now = now_local()
    fts_ready = _get_meta(connection, "fts5_ready", "0") == "1"
    vec_ready = _vec_state(connection)["ready"]
    for path, record in _iter_history():
        conversation_id = _conversation_id(record, path)
        title = str(record.get("title") or "Conversation")
        updated = str(record.get("updated_at") or record.get("created_at") or _iso(now))
        if record.get("locked") and not config["include_locked"]:
            continue
        source = connection.execute(
            "SELECT message_count, updated_at FROM source WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        messages = record["messages"]
        if source is not None and str(source["updated_at"] or "") == updated and \
                int(source["message_count"] or 0) >= len(messages):
            continue
        stats["conversations"] += 1
        context_after: dict[int, str] = {}
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                context_after[index - 1] = message_text(message)[:600]
        notes: list[tuple[str, str]] = []
        note_texts: set[str] = set()
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            # A key pasted into a chat must never reach the index, the nightly
            # prompt or a Markdown file, so redaction happens before storage.
            text = _redact(normalize_text(message_text(message)))
            if len(text) < 8:
                continue
            if role == "user" and _is_slash_command(text):
                continue
            message_hash = _hash(f"{conversation_id}:{index}:{compare_text(text)}")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO message (conversation_id, idx, role, text, norm_hash, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, index, role, text[:MAX_MESSAGE_CHARS], message_hash, updated),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                stats["messages"] += 1
                vector = embed(compare_text(text))
                message_id = cursor.lastrowid
                connection.execute("UPDATE message SET embedding = ? WHERE id = ?", (_pack(vector), message_id))
                if fts_ready:
                    try:
                        connection.execute("INSERT INTO message_fts(rowid, text) VALUES (?, ?)", (message_id, text))
                    except sqlite3.DatabaseError:
                        pass
                if vec_ready:
                    try:
                        connection.execute(
                            "INSERT INTO message_vec(rowid, embedding) VALUES (?, ?)",
                            (message_id, json.dumps(vector[:EMBED_DIM])),
                        )
                    except sqlite3.DatabaseError:
                        pass
                if role == "user":
                    outcome = _stage_candidate(
                        connection,
                        conversation_id=conversation_id,
                        message_index=index,
                        text=text,
                        context=context_after.get(index, ""),
                        timestamp=updated,
                        dedupe=float(config["dedupe"]),
                    )
                    if outcome == "new":
                        stats["new_candidates"] += 1
                    elif outcome == "merged":
                        stats["merged_candidates"] += 1
            # The note keeps one bullet per distinct message: a repeated prompt
            # should not fill the day's note with copies of itself.
            if role == "user":
                if text not in note_texts:
                    note_texts.add(text)
                    notes.append(("You", text))
            elif notes and text not in note_texts:
                note_texts.add(text)
                notes.append(("Assistant", text[:300]))
        if not dry_run and _append_daily_note(
            conversation_id, title, updated[:10], notes[-MAX_DAILY_MESSAGES:]
        ):
            stats["notes_written"] += 1
        connection.execute(
            "INSERT INTO source (conversation_id, title, path, updated_at, message_count, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET "
            "title = excluded.title, path = excluded.path, updated_at = excluded.updated_at, "
            "message_count = excluded.message_count, ingested_at = excluded.ingested_at",
            (conversation_id, title[:120], str(path), updated, len(messages), _iso(now)),
        )
    _set_meta(connection, "last_ingest_at", _iso(now))
    return stats


# --------------------------------------------------------------------------- #
# REM Sleep: recurring topics and themes
# --------------------------------------------------------------------------- #


def _llm_settings(settings: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build the settings for the summarisation call.

    The user's configured provider is the default; a memory-specific provider
    and model can override it, which is how a local llama-server or Ollama is
    selected without touching the chat settings.
    """
    result = dict(settings or {})
    result.setdefault("provider", "openai")
    if config.get("provider"):
        result["provider"] = config["provider"]
    if config.get("model"):
        result["model"] = config["model"]
    if config.get("base_url"):
        result["base_url"] = config["base_url"]
    result["temperature"] = 0.2
    result["max_tokens"] = min(int(result.get("max_tokens") or 1200), 1200)
    result["thinking_level"] = "off"
    result["stream"] = False
    return result


def _parse_llm_json(answer: str) -> list[dict[str, Any]]:
    """Extract the JSON array from a model answer, tolerating fences and prose."""
    text = str(answer or "")
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _llm_available(settings: dict[str, Any], config: dict[str, Any]) -> bool:
    """Whether a summary model can actually be reached right now.

    Asking for a model with no key (or with no key and a remote endpoint) would
    mark every nightly run as degraded, so the engine simply runs offline in
    that case. A loopback endpoint such as llama-server or Ollama is usable
    without a key.
    """
    try:
        import app

        llm = _llm_settings(settings, config)
        provider = app.normalize_provider(llm.get("provider"))
        if app.key_is_configured(provider, llm):
            return True
        return app.endpoint_is_loopback(app.get_base_url(provider, llm))
    except Exception:
        return False


def _ask_model(
    settings: dict[str, Any],
    config: dict[str, Any],
    items: list[dict[str, Any]],
    language: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    """Ask the configured model for theme and importance per candidate.

    Returns the mapping keyed by candidate id plus an error string. Any failure
    is non-fatal: the engine falls back to its local heuristics.
    """
    if not items:
        return {}, ""
    try:
        import app  # lazy import: avoids a circular import at start-up

        language_name = "Thai" if language == "th" else "English"
        system = (
            "You consolidate long-term memory for one user. For each item decide how much it "
            "deserves to be remembered for months: 5 = durable preference, identity, project fact "
            "or decision; 1 = small talk. Give every item a short topic theme (2-4 words). "
            f"Write themes and summaries in {language_name}. "
            'Answer with a JSON array only: [{"id":"...","importance":1-5,"theme":"..."}]'
        )
        answer, _usage = app.call_provider(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
            ],
            _llm_settings(settings, config),
        )
        result: dict[str, dict[str, Any]] = {}
        for item in _parse_llm_json(answer):
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            try:
                importance = int(item.get("importance"))
            except (TypeError, ValueError):
                importance = 3
            result[item_id] = {
                "importance": max(1, min(5, importance)),
                "theme": str(item.get("theme") or "").strip()[:60],
            }
        return result, "" if result else "empty_model_answer"
    except Exception as exc:  # noqa: BLE001 - the run must survive a bad model
        return {}, _redact(str(exc))[:300]


def rem_sleep(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    settings: dict[str, Any],
    run_id: str,
    language: str,
    stats: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Group recurring candidates into themes and label them.

    Returns the clusters keyed by id and the model's per-candidate reply, which
    the scoring phase reuses so the run never calls the model twice.
    """
    now = now_local()
    window_start = now - timedelta(days=int(config["lookback_days"]))
    # Clusters are rebuilt every run, so old ones are only noise: keep the last
    # couple of windows for context and drop the rest.
    connection.execute(
        "DELETE FROM cluster WHERE created_at < ?",
        (_iso(now - timedelta(days=max(14, int(config["lookback_days"]) * 2))),),
    )
    rows = connection.execute(
        "SELECT * FROM candidate WHERE state IN ('staged', 'rejected') AND last_seen >= ? "
        "ORDER BY occurrences DESC, last_seen DESC LIMIT ?",
        (_iso(window_start), MAX_CANDIDATES_PER_RUN),
    ).fetchall()
    stats["candidates_in_window"] = len(rows)
    groups: list[dict[str, Any]] = []
    for row in rows:
        vector = _unpack(row["embedding"]) or embed(compare_text(row["text"]))
        placed = False
        for group in groups:
            if cosine(vector, group["centroid"]) >= 0.80:
                group["rows"].append((row, vector))
                size = len(group["rows"])
                group["centroid"] = [
                    (total * (size - 1) + value) / size
                    for total, value in zip(group["centroid"], vector)
                ]
                placed = True
                break
        if not placed:
            groups.append({"centroid": vector, "rows": [(row, vector)]})

    model_reply: dict[str, dict[str, Any]] = {}
    stats["llm_skipped"] = bool(config["llm"]) and not _llm_available(settings, config)
    if config["llm"] and not stats["llm_skipped"]:
        # The prompt is capped by size as well as by count: a small local model
        # has a 2-4k context, and a 25-item prompt would silently truncate.
        payload: list[dict[str, Any]] = []
        budget = 9_000
        for row in rows:
            item = {
                "id": row["id"],
                "text": row["text"][:600],
                "context": (row["context"] or "")[:300],
                "seen": row["occurrences"],
            }
            size = len(item["text"]) + len(item["context"])
            if len(payload) >= MAX_LLM_ITEMS or size > budget:
                break
            payload.append(item)
            budget -= size
        model_reply, error = _ask_model(settings, config, payload, language)
        stats["llm_calls"] = 1 if payload else 0
        stats["llm_error"] = error

    for group in groups:
        cluster_id = str(uuid.uuid4())
        combined = " ".join(row["text"] for row, _vector in group["rows"])
        label = next(
            (
                model_reply[row["id"]]["theme"]
                for row, _vector in group["rows"]
                if row["id"] in model_reply and model_reply[row["id"]]["theme"]
            ),
            "",
        )
        if not label:
            # Without a model, the most repeated candidate reads far better than
            # a bag of Thai character trigrams.
            label = normalize_text(group["rows"][0][0]["text"])[:40]
        theme_label = label[:80]
        connection.execute(
            "INSERT INTO cluster (id, label, theme, keywords, size, window_start, window_end, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cluster_id,
                theme_label,
                theme_label,
                json.dumps(keywords(combined, 8), ensure_ascii=False),
                len(group["rows"]),
                _iso(window_start),
                _iso(now),
                _iso(now),
            ),
        )
        for row, _vector in group["rows"]:
            connection.execute("UPDATE candidate SET cluster_id = ? WHERE id = ?", (cluster_id, row["id"]))
        group["id"] = cluster_id
        group["theme"] = theme_label
        group["keywords"] = keywords(combined, 6)
    stats["clusters"] = len(groups)
    return {group["id"]: group for group in groups}, model_reply


# --------------------------------------------------------------------------- #
# Deep Sleep: scoring, promotion, dream log
# --------------------------------------------------------------------------- #


def _importance_of(row: sqlite3.Row, model_reply: dict[str, dict[str, Any]]) -> tuple[float, str]:
    """Return the model's importance (or a local estimate) and the theme."""
    reply = model_reply.get(row["id"])
    if reply:
        return float(reply["importance"]) / 5.0, reply.get("theme") or ""
    text = row["text"]
    score = 2.0
    if _EXPLICIT_RE.search(text):
        score += 2.0
    if len(text) > 240:
        score += 0.5
    if re.search(r"\d", text):
        score += 0.5
    return min(5.0, score) / 5.0, ""


def score_candidates(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    model_reply: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Score every candidate and return the passing ones plus the count."""
    now = now_local()
    lookback = max(1, int(config["lookback_days"]))
    existing = entries()
    promoted_vectors = [(item["text"], embed(compare_text(item["text"]))) for item in existing]
    cluster_themes = {
        row["id"]: str(row["theme"] or row["label"] or "")
        for row in connection.execute("SELECT id, theme, label FROM cluster")
    }
    rows = connection.execute(
        "SELECT * FROM candidate WHERE state IN ('staged', 'rejected') ORDER BY last_seen DESC LIMIT ?",
        (MAX_CANDIDATES_PER_RUN,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        vector = _unpack(row["embedding"]) or embed(compare_text(row["text"]))
        last_seen = _parse_dt(row["last_seen"]) or now
        age_days = max(0.0, (now - last_seen).total_seconds() / 86400)
        recency = max(0.0, 1.0 - age_days / lookback)
        frequency = min(1.0, int(row["occurrences"] or 1) / 3.0)
        importance, theme = _importance_of(row, model_reply)
        if not theme:
            theme = cluster_themes.get(row["cluster_id"], "")
        similarity = max((cosine(vector, other) for _text, other in promoted_vectors), default=0.0)
        novelty = max(0.0, 1.0 - similarity)
        explicit = 1.0 if _EXPLICIT_RE.search(row["text"]) else 0.0
        duplicate_penalty = 1.0 if similarity >= 0.90 else 0.0
        score = (
            0.30 * recency
            + 0.25 * frequency
            + 0.25 * importance
            + 0.10 * novelty
            + 0.10 * explicit
            - 0.20 * duplicate_penalty
        )
        score = round(max(0.0, min(1.0, score)), 3)
        passes = score >= float(config["threshold"]) and (
            importance >= 0.6 or int(row["occurrences"] or 1) >= 2 or explicit > 0
        )
        breakdown = {
            "recency": round(recency, 3),
            "frequency": round(frequency, 3),
            "importance": round(importance, 3),
            "novelty": round(novelty, 3),
            "explicit": explicit,
            "duplicate_penalty": duplicate_penalty,
        }
        connection.execute(
            "UPDATE candidate SET score = ?, breakdown = ?, state = ?, cluster_id = COALESCE(cluster_id, ?) "
            "WHERE id = ?",
            (
                score,
                json.dumps(breakdown),
                "staged",
                row["cluster_id"],
                row["id"],
            ),
        )
        if passes:
            results.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "score": score,
                    "theme": theme,
                    "context": row["context"] or "",
                    "conversation_id": row["conversation_id"],
                    "occurrences": int(row["occurrences"] or 1),
                    "explicit": explicit > 0,
                    "breakdown": breakdown,
                }
            )
    results.sort(key=lambda item: item["score"], reverse=True)
    # Two near-identical notes can reach the threshold in the same night; only
    # the first one becomes a memory, the other stays staged.
    unique: list[dict[str, Any]] = []
    accepted: list[list[float]] = []
    for item in results:
        vector = embed(compare_text(item["text"]))
        if any(cosine(vector, other) >= 0.90 for other in accepted):
            continue
        accepted.append(vector)
        unique.append(item)
    return unique, len(rows)


def _ensure_heading(path: Path, heading: str, header: str) -> None:
    """Create a Markdown file with a heading once, never rewriting user edits."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{header}\n\n{heading}\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def promote(entries_to_add: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Append accepted memories to MEMORY.md under hidden markers."""
    _ensure_heading(
        MEMORY_FILE,
        MEMORY_HEADING,
        "# MEMORY\n\nLong-term memory promoted from conversations. "
        "Each entry carries a hidden marker so the engine can update or forget it.",
    )
    today = now_local().strftime("%Y-%m-%d")
    written: list[dict[str, Any]] = []
    try:
        text = MEMORY_FILE.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if MEMORY_HEADING not in text:
        text = text.rstrip() + f"\n\n{MEMORY_HEADING}\n"
    for item in entries_to_add[:limit]:
        if f"<!-- mem:{item['id']}" in text:
            continue
        theme = str(item.get("theme") or "").strip()
        body = item["text"].strip()[:600]
        # Without a model the label is just the start of the sentence; do not
        # print it twice when it adds nothing.
        if theme and not body.startswith(theme):
            line = f"- **{theme}** — {body}\n"
        else:
            line = f"- {body}\n"
        block = (
            f"\n<!-- mem:{item['id']} score={item['score']:.3f} date={today} "
            f"sources={str(item.get('conversation_id') or '')[:36]} -->\n"
            + line
        )
        text += block
        written.append(item)
    MEMORY_FILE.write_text(text, encoding="utf-8")
    try:
        os.chmod(MEMORY_FILE, 0o600)
    except OSError:
        pass
    return written


def write_dreams(stats: dict[str, Any], promoted: list[dict[str, Any]], language: str) -> None:
    """Append the readable nightly summary to DREAMS.md."""
    DREAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DREAMS_FILE.exists():
        DREAMS_FILE.write_text("# DREAMS\n\nNightly notes from the memory filter.\n", encoding="utf-8")
    stamp = now_local().strftime("%Y-%m-%d %H:%M")
    themes = ", ".join(stats.get("themes") or []) or "-"
    lines = [
        "",
        f"## {stamp}",
        f"- สแกน {stats.get('messages', 0)} ข้อความใหม่ · ผู้สมัคร {stats.get('candidates_in_window', 0)} รายการ · ผ่านเกณฑ์ {len(promoted)}"
        if language == "th"
        else f"- Scanned {stats.get('messages', 0)} new messages · {stats.get('candidates_in_window', 0)} candidates · {len(promoted)} promoted",
        f"- ธีม: {themes}" if language == "th" else f"- Themes: {themes}",
    ]
    for item in promoted[:8]:
        lines.append(f"- ⭐ **{item.get('theme') or 'Note'}** — {item['text'][:160]}")
    if not promoted:
        lines.append("- ไม่มีอะไรผ่านเกณฑ์คืนนี้" if language == "th" else "- Nothing passed the threshold tonight")
    with DREAMS_FILE.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    try:
        os.chmod(DREAMS_FILE, 0o600)
    except OSError:
        pass
    _trim_dreams()


def _trim_dreams() -> None:
    """Keep DREAMS.md from growing without bound."""
    try:
        if DREAMS_FILE.stat().st_size <= DREAMS_MAX_BYTES:
            return
        text = DREAMS_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    sections = text.split("\n## ")
    header, body = sections[0], sections[1:]
    kept: list[str] = []
    size = len(header)
    for section in reversed(body):
        size += len(section) + 4
        if size > DREAMS_MAX_BYTES // 2:
            break
        kept.append(section)
    DREAMS_FILE.write_text(header + "".join("\n## " + item for item in reversed(kept)), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Public API used by the routes
# --------------------------------------------------------------------------- #


def run(
    trigger: str = "manual",
    dry_run: bool = False,
    settings: dict[str, Any] | None = None,
    language: str = "th",
) -> dict[str, Any]:
    """Run the three phases once and return a summary for the page.

    A dry run executes the same evaluation inside one SQLite transaction and
    rolls it back, so the user can preview what would be promoted without
    touching the Markdown vault or the index.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("memory_busy")
    run_id = str(uuid.uuid4())
    started = _iso()
    stats: dict[str, Any] = {
        "messages": 0,
        "new_candidates": 0,
        "merged_candidates": 0,
        "notes_written": 0,
        "candidates_in_window": 0,
        "clusters": 0,
        "scored": 0,
        "passed": 0,
        "promoted": 0,
        "themes": [],
        "llm_calls": 0,
        "llm_skipped": False,
        "llm_error": "",
    }
    config = settings_from(settings)
    promoted: list[dict[str, Any]] = []
    status = "ok"
    error = ""
    connection: sqlite3.Connection | None = None
    try:
        ensure_storage()
        connection = _connect()
        connection.isolation_level = None
        connection.execute("BEGIN")
        light = light_sleep(connection, config, run_id, dry_run)
        stats.update({key: light.get(key, 0) for key in ("messages", "new_candidates", "merged_candidates", "notes_written")})
        rem, model_reply = rem_sleep(connection, config, settings or {}, run_id, language, stats)
        stats["themes"] = list(
            dict.fromkeys(group["theme"][:40] for group in list(rem.values())[:5])
        )
        scored, evaluated = score_candidates(connection, config, model_reply)
        stats["scored"] = evaluated
        stats["passed"] = len(scored)
        # Items that are already in MEMORY.md must not be counted as new wins in
        # a preview, so both paths apply the same exclusion.
        known = {item["id"] for item in entries()}
        promoted = [item for item in scored if item["id"] not in known][: int(config["max_items"])]
        if not dry_run and promoted:
            written = promote(promoted, int(config["max_items"]))
            stats["promoted"] = len(written)
            for item in written:
                connection.execute(
                    "UPDATE candidate SET state = 'promoted', memory_id = ? WHERE id = ?",
                    (item["id"], item["id"]),
                )
            written_ids = {item["id"] for item in written}
            promoted = [item for item in promoted if item["id"] in written_ids]
        else:
            stats["promoted"] = len(promoted)
        if stats["llm_error"]:
            status = "degraded"
        if not dry_run:
            write_dreams(stats, promoted, language)
        if dry_run:
            connection.execute("ROLLBACK")
        else:
            connection.execute("COMMIT")
            connection.execute("BEGIN")
            _set_meta(connection, "last_run_at", started)
            _set_meta(connection, "last_run_status", status)
            _set_meta(connection, "last_run_date", now_local().strftime("%Y-%m-%d"))
            _set_meta(connection, "last_stats", json.dumps(stats, ensure_ascii=False))
            connection.execute(
                "INSERT INTO run (id, started_at, finished_at, trigger, status, stats, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, started, _iso(), trigger, status, json.dumps(stats, ensure_ascii=False), ""),
            )
            connection.execute("COMMIT")
        _log(
            "memory.run",
            "Memory consolidation finished",
            run=run_id,
            trigger=trigger,
            dry_run=dry_run,
            promoted=stats["promoted"],
            status=status,
        )
        return {
            "ok": True,
            "run_id": run_id,
            "status": status,
            "dry_run": dry_run,
            "stats": stats,
            "promoted": [
                {"id": item["id"], "text": item["text"][:400], "score": item["score"], "theme": item.get("theme") or ""}
                for item in promoted
            ],
            "capabilities": safe_capabilities(),
        }
    except Exception as exc:  # noqa: BLE001 - reported to the page and the log
        error = _redact(str(exc))[:500]
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
        _log("memory.error", "Memory consolidation failed", run=run_id, error=error)
        raise
    finally:
        if connection is not None:
            connection.close()
        _RUN_LOCK.release()


def entries() -> list[dict[str, Any]]:
    """Read the promoted memories back out of MEMORY.md."""
    try:
        text = MEMORY_FILE.read_text(encoding="utf-8")
    except OSError:
        return []
    items: list[dict[str, Any]] = []
    for match in _MEMORY_MARKER_RE.finditer(text):
        body = match.group("body").strip()
        if body.startswith("- "):
            body = body[2:]
        try:
            score_value = float(match.group("score"))
        except ValueError:
            # A hand-edited marker must not break the whole list.
            score_value = 0.0
        items.append(
            {
                "id": match.group("id"),
                "score": score_value,
                "date": match.group("date"),
                "sources": [part for part in match.group("sources").split(",") if part],
                "text": body.strip(),
            }
        )
    items.sort(key=lambda item: (item["date"], item["score"]), reverse=True)
    return items


def forget(memory_id: str) -> bool:
    """Remove one promoted memory from MEMORY.md and mark it forgotten."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(memory_id or "")):
        return False
    try:
        text = MEMORY_FILE.read_text(encoding="utf-8")
    except OSError:
        return False
    pattern = re.compile(
        rf"\n?<!-- mem:{re.escape(memory_id)}[^>]*-->\n?(?:- [^\n]*\n)?",
        re.DOTALL,
    )
    updated = pattern.sub("\n", text)
    if updated == text:
        return False
    MEMORY_FILE.write_text(updated, encoding="utf-8")
    try:
        with _session() as connection:
            # Drop the vector too: a forgotten memory must not keep influencing
            # novelty checks through a stale embedding.
            connection.execute(
                "UPDATE candidate SET state = 'forgotten', memory_id = NULL, embedding = NULL "
                "WHERE memory_id = ? OR id = ?",
                (memory_id, memory_id),
            )
    except sqlite3.DatabaseError:
        pass
    _log("memory.forget", "Removed a promoted memory", memory=memory_id)
    return True


def recent_dreams(limit: int = 120) -> str:
    """Return the newest part of DREAMS.md for the page."""
    try:
        text = DREAMS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[-limit * 120 :]


def status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report the state of the memory system without running anything."""
    config = settings_from(settings)
    ensure_storage()
    with _session() as connection:
        counts = {
            row["state"]: int(row["count"])
            for row in connection.execute("SELECT state, COUNT(*) AS count FROM candidate GROUP BY state")
        }
        last_run = _get_meta(connection, "last_run_at", "")
        last_status = _get_meta(connection, "last_run_status", "")
        last_date = _get_meta(connection, "last_run_date", "")
        last_stats = _get_meta(connection, "last_stats", "{}")
        stored_messages = int(connection.execute("SELECT COUNT(*) AS count FROM message").fetchone()["count"])
        conversations = int(connection.execute("SELECT COUNT(*) AS count FROM source").fetchone()["count"])
    try:
        parsed_stats = json.loads(last_stats)
    except json.JSONDecodeError:
        parsed_stats = {}
    return {
        "enabled": bool(config["enabled"]),
        "schedule": config["schedule"],
        "lookback_days": config["lookback_days"],
        "threshold": config["threshold"],
        "idle_minutes": config["idle_minutes"],
        "max_items": config["max_items"],
        "llm": bool(config["llm"]),
        "provider": config["provider"],
        "model": config["model"],
        "base_url": config["base_url"],
        "window_end": config["window_end"],
        "running": is_running(),
        "idle_seconds": int(idle_seconds()),
        "last_run_at": last_run,
        "last_run_status": last_status,
        "last_run_date": last_date,
        "last_stats": parsed_stats,
        "counts": counts,
        "messages": stored_messages,
        "conversations": conversations,
        "promoted_entries": len(entries()),
        "paths": {
            "memory_dir": str(MEMORY_DIR),
            "memory_file": str(MEMORY_FILE),
            "dreams_file": str(DREAMS_FILE),
            "database": str(DATABASE_FILE),
        },
        "capabilities": capabilities(),
    }


def reindex() -> dict[str, int]:
    """Drop the derived index and build it again from the history folder."""
    # Take the same lock a run takes: rebuilding the index halfway through a
    # consolidation would interleave two writers on the same tables.
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("memory_busy")
    try:
        ensure_storage()
        with _session() as connection:
            connection.execute("DELETE FROM message")
            connection.execute("DELETE FROM candidate")
            connection.execute("DELETE FROM cluster")
            connection.execute("DELETE FROM source")
            try:
                connection.execute("DELETE FROM message_fts")
            except sqlite3.DatabaseError:
                pass
            if _vec_state(connection)["ready"]:
                try:
                    connection.execute("DELETE FROM message_vec")
                except sqlite3.DatabaseError:
                    pass
            _set_meta(connection, "last_ingest_at", "")
        _log("memory.reindex", "Rebuilt the memory index from history")
        return {"ok": True}
    finally:
        _RUN_LOCK.release()


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #


def _minutes(text: str) -> int:
    """Convert an ``HH:MM`` string to minutes after midnight."""
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


def _cron_start_minutes(schedule: str) -> int:
    """Minute-of-day of a cron schedule, or 0 when the fields are not plain.

    ``*/30 3 * * *`` is a valid expression whose minute field is not a number;
    reading it with int() used to raise on every scheduler tick.
    """
    fields = str(schedule).split()
    if len(fields) != 5:
        return 0
    try:
        return int(fields[1]) * 60 + int(fields[0])
    except ValueError:
        return 0


def _due_today(connection: sqlite3.Connection, now: datetime) -> bool:
    """Whether the nightly run is due today but has not happened yet."""
    last_date = _get_meta(connection, "last_run_date")
    if last_date == now.strftime("%Y-%m-%d"):
        return False
    return _get_meta(connection, "due_date") == now.strftime("%Y-%m-%d")


def scheduler_tick() -> None:
    """Run one scheduler decision; separated so it can be tested directly."""
    try:
        import app  # lazy import: app owns the settings and cron matcher

        settings = app.load_settings()
        config = settings_from(settings)
        if not config["enabled"]:
            return
        now = now_local()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        today_text = now.strftime("%Y-%m-%d")
        start_minutes = _cron_start_minutes(config["schedule"])
        end_minutes = _minutes(config["window_end"])
        if end_minutes <= start_minutes:
            end_minutes = 23 * 60 + 59
        now_minutes = now.hour * 60 + now.minute
        with _session() as connection:
            if app.cron_matches(config["schedule"], now) and _get_meta(connection, "due_key") != minute_key:
                _set_meta(connection, "due_key", minute_key)
                _set_meta(connection, "due_date", today_text)
                _log("memory.due", "Memory consolidation became due", schedule=config["schedule"])
            # Catch-up: a phone asleep at the scheduled minute (or a server
            # started inside the window) still consolidates once it is awake.
            if (
                _get_meta(connection, "due_date") != today_text
                and _get_meta(connection, "last_run_date") != today_text
                and start_minutes <= now_minutes <= end_minutes
            ):
                _set_meta(connection, "due_date", today_text)
                _log("memory.due", "Memory consolidation became due (catch-up)", schedule=config["schedule"])
            if not _due_today(connection, now) or is_running():
                return
            if now_minutes > end_minutes:
                _set_meta(connection, "due_date", "")
                return
            if idle_seconds() < int(config["idle_minutes"]) * 60:
                return
            _set_meta(connection, "due_date", "")
        language = str(settings.get("response_language") or "auto")
        if language == "auto":
            language = "th"
        threading.Thread(
            target=_run_from_scheduler, args=(settings, language), daemon=True, name="memory-run"
        ).start()
    except Exception as exc:  # noqa: BLE001 - a tick must never kill the loop
        _log("memory.scheduler_error", "The memory scheduler tick failed", error=_redact(str(exc))[:300])


def _run_from_scheduler(settings: dict[str, Any], language: str) -> None:
    """Execute a scheduled run outside the scheduler thread."""
    try:
        run(trigger="schedule", settings=settings, language=language)
    except Exception:
        pass


def start_scheduler() -> None:
    """Start the memory scheduler loop once per process."""
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return
        _SCHEDULER_STARTED = True

    def loop() -> None:
        time.sleep(5)
        while True:
            try:
                scheduler_tick()
            except Exception:
                pass
            time.sleep(20)

    threading.Thread(target=loop, daemon=True, name="memory-scheduler").start()
    _log("memory.scheduler", "Memory scheduler started")
