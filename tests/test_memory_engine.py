"""Tests for the memory-consolidation engine.

These cover the data-integrity behaviour of the two storage tiers: a promotion
writes a bounded, hashed entry; Forget removes the whole entry and records a
durable tombstone before the file changes; a reset index still forgets; a
preview writes nothing; a failed run does not leave published entries behind;
and the scheduler initialises its own schema and only catches up when its cron
schedule actually fired that day.
"""

import contextlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
ENTRY_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ENTRY_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
REMEMBER = "remember that the deploy key lives in the safe"


def promoted_entry(module, text, memory_id, *, score=0.8, theme="topic"):
    """Build the dict that the scoring phase hands to promote()."""
    return {
        "id": memory_id,
        "text": text,
        "score": score,
        "theme": theme,
        "conversation_id": CONVERSATION_ID,
        "norm_hash": module._hash(module.compare_text(text).lower()),
    }


def write_history(module, messages, *, date="2026-11-21"):
    """Write one conversation record where light_sleep will find it."""
    folder = module.HISTORY_ROOT / date
    folder.mkdir(parents=True, exist_ok=True)
    stamp = f"{date}T10:00:00+00:00"
    record = {
        "id": CONVERSATION_ID,
        "title": "Test chat",
        "created_at": stamp,
        "updated_at": stamp,
        "locked": False,
        "pinned": False,
        "messages": messages,
    }
    path = folder / f"10-00-00_{CONVERSATION_ID}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def forgotten_hashes(module):
    with module._session() as connection:
        return {
            row["text_hash"]
            for row in connection.execute("SELECT text_hash FROM forgotten")
        }


# --------------------------------------------------------------------------- #
# promote()
# --------------------------------------------------------------------------- #


def test_promote_writes_the_whole_entry_with_its_hash_and_end_marker(engine):
    body = "first line\nsecond line\n\nfourth line"
    first = promoted_entry(engine, body, ENTRY_A)
    second = promoted_entry(engine, "another memory", ENTRY_B, score=0.7)

    written = engine.promote([first, second], limit=10)

    assert [item["id"] for item in written] == [ENTRY_A, ENTRY_B]
    text = engine.MEMORY_FILE.read_text(encoding="utf-8")
    assert f"<!-- /mem:{ENTRY_A} -->" in text
    assert f"hash={first['norm_hash']}" in text

    items = {item["id"]: item for item in engine.entries()}
    assert set(items) == {ENTRY_A, ENTRY_B}
    # The multiline body is read back in full, without the end marker leaking.
    assert "second line" in items[ENTRY_A]["text"]
    assert "fourth line" in items[ENTRY_A]["text"]
    assert all("/mem:" not in item["text"] for item in items.values())

    # Promoting the same ids again must not duplicate the entries.
    assert engine.promote([first, second], limit=10) == []


def test_promote_respects_the_limit_and_skips_known_ids(engine):
    first = promoted_entry(engine, "one", ENTRY_A)
    second = promoted_entry(engine, "two", ENTRY_B, score=0.7)
    assert len(engine.promote([first, second], limit=1)) == 1
    assert len(engine.entries()) == 1
    assert len(engine.promote([first, second], limit=10)) == 1
    assert len(engine.entries()) == 2


# --------------------------------------------------------------------------- #
# forget()
# --------------------------------------------------------------------------- #


def test_forget_removes_the_whole_entry_and_keeps_other_notes(engine):
    body = "remember the deploy key\nsecond line\n\nfourth line"
    forgotten = promoted_entry(engine, body, ENTRY_A)
    kept = promoted_entry(engine, "another memory", ENTRY_B, score=0.7)
    engine.promote([forgotten, kept], limit=10)
    engine.MEMORY_FILE.write_text(
        engine.MEMORY_FILE.read_text(encoding="utf-8") + "\nmy own note\n",
        encoding="utf-8",
    )

    assert engine.forget(ENTRY_A) is True

    text = engine.MEMORY_FILE.read_text(encoding="utf-8")
    for line in ("remember the deploy key", "second line", "fourth line"):
        assert line not in text
    assert "another memory" in text
    assert "my own note" in text
    assert f"<!-- /mem:{ENTRY_A} -->" not in text
    # The tombstone records the hash of the full original text.
    assert forgotten["norm_hash"] in forgotten_hashes(engine)
    # A second Forget has nothing left to remove.
    assert engine.forget(ENTRY_A) is False


def test_forget_after_reindex_uses_the_hash_stored_with_the_entry(engine):
    forgotten = promoted_entry(engine, "a memory that must stay forgotten", ENTRY_A)
    engine.promote([forgotten], limit=10)

    engine.reindex()
    with engine._session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 0

    assert engine.forget(ENTRY_A) is True
    assert forgotten["norm_hash"] in forgotten_hashes(engine)
    assert "must stay forgotten" not in engine.MEMORY_FILE.read_text(encoding="utf-8")


def test_forget_is_busy_while_a_run_holds_the_lock(engine):
    item = promoted_entry(engine, "kept while busy", ENTRY_A)
    engine.promote([item], limit=10)
    before = engine.MEMORY_FILE.read_text(encoding="utf-8")

    engine._RUN_LOCK.acquire()
    try:
        with pytest.raises(RuntimeError, match="memory_busy"):
            engine.forget(ENTRY_A)
    finally:
        engine._RUN_LOCK.release()

    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == before


def test_forget_keeps_the_entry_when_the_tombstone_cannot_be_written(engine, monkeypatch):
    item = promoted_entry(engine, "must survive a database failure", ENTRY_A)
    engine.promote([item], limit=10)
    before = engine.MEMORY_FILE.read_text(encoding="utf-8")

    @contextlib.contextmanager
    def broken_session():
        raise sqlite3.OperationalError("database is locked")
        yield  # pragma: no cover - the context never opens

    monkeypatch.setattr(engine, "_session", broken_session)

    with pytest.raises(RuntimeError, match="memory_forget_failed"):
        engine.forget(ENTRY_A)

    # The marker is still in the file, so the user can retry the Forget.
    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == before
    assert engine._RUN_LOCK.locked() is False


# --------------------------------------------------------------------------- #
# reindex()
# --------------------------------------------------------------------------- #


def test_reindex_resets_derived_tables_but_keeps_tombstones(engine):
    item = promoted_entry(engine, "indexed memory", ENTRY_A)
    engine.promote([item], limit=10)
    memory_before = engine.MEMORY_FILE.read_text(encoding="utf-8")
    with engine._session() as connection:
        connection.execute(
            "INSERT INTO candidate (id, text, norm_hash, state) VALUES ('c', 'x', 'h', 'staged')"
        )
        connection.execute(
            "INSERT INTO message (conversation_id, idx, role, text, norm_hash) "
            "VALUES ('c', 0, 'user', 'x', 'h')"
        )
        connection.execute("INSERT INTO source (conversation_id) VALUES ('c')")
        connection.execute("INSERT INTO cluster (id) VALUES ('cl')")
        connection.execute(
            "INSERT INTO forgotten (text_hash, forgotten_at, text) VALUES ('keep-me', ?, 'x')",
            (engine._iso(),),
        )

    assert engine.reindex() == {"ok": True}

    with engine._session() as connection:
        for table in ("message", "candidate", "cluster", "source"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM forgotten").fetchone()[0] == 1
        assert engine._get_meta(connection, "last_ingest_at") == ""
    # A reset index never rewrites the published memories.
    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == memory_before


def test_reindex_is_busy_while_a_run_holds_the_lock(engine):
    engine._RUN_LOCK.acquire()
    try:
        with pytest.raises(RuntimeError, match="memory_busy"):
            engine.reindex()
    finally:
        engine._RUN_LOCK.release()


# --------------------------------------------------------------------------- #
# run(): dry run, promotion and failure recovery
# --------------------------------------------------------------------------- #


def test_dry_run_writes_nothing_and_rolls_back_the_index(engine):
    write_history(
        engine,
        [
            {"role": "user", "content": REMEMBER},
            {"role": "assistant", "content": "Noted."},
        ],
    )

    result = engine.run(dry_run=True, settings={"memory": {"llm": False}}, language="en")

    assert result["dry_run"] is True
    assert not engine.MEMORY_FILE.exists()
    assert not engine.DREAMS_FILE.exists()
    assert not list(engine.MEMORY_DIR.glob("*.md"))
    with engine._session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM message").fetchone()[0] == 0


def test_run_promotes_and_the_promoted_entry_can_be_forgotten(engine):
    write_history(
        engine,
        [
            {"role": "user", "content": REMEMBER},
            {"role": "assistant", "content": "Noted."},
        ],
    )

    result = engine.run(settings={"memory": {"llm": False}}, language="en")

    assert result["stats"]["promoted"] == 1
    assert result["stats"]["llm_skipped"] is False  # summaries are disabled
    assert result["stats"]["llm_error"] == ""
    items = engine.entries()
    assert len(items) == 1
    assert "deploy key" in items[0]["text"]

    assert engine.forget(items[0]["id"]) is True
    assert "deploy key" not in engine.MEMORY_FILE.read_text(encoding="utf-8")


def test_a_run_that_fails_after_promotion_removes_what_it_published(engine, monkeypatch):
    write_history(
        engine,
        [
            {"role": "user", "content": REMEMBER},
            {"role": "assistant", "content": "Noted."},
        ],
    )

    def failing_dreams(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine, "write_dreams", failing_dreams)

    with pytest.raises(OSError):
        engine.run(settings={"memory": {"llm": False}}, language="en")

    published = (
        engine.MEMORY_FILE.read_text(encoding="utf-8")
        if engine.MEMORY_FILE.exists()
        else ""
    )
    assert "<!-- mem:" not in published
    with engine._session() as connection:
        promoted = connection.execute(
            "SELECT COUNT(*) FROM candidate WHERE state = 'promoted'"
        ).fetchone()[0]
    assert promoted == 0
    assert engine._RUN_LOCK.locked() is False


def test_an_invalid_schedule_releases_the_run_lock(engine):
    with pytest.raises(ValueError):
        engine.run(settings={"memory": {"schedule": "not a cron"}}, language="en")

    assert engine._RUN_LOCK.locked() is False


# --------------------------------------------------------------------------- #
# scheduler_tick()
# --------------------------------------------------------------------------- #


def scheduler_settings(**overrides):
    memory = {
        "enabled": True,
        "schedule": "0 3 * * *",
        "window_end": "06:00",
        "idle_minutes": 720,
        "llm": False,
    }
    memory.update(overrides)
    return {"memory": memory, "response_language": "en"}


def prepare_scheduler(monkeypatch, engine, settings):
    import app

    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(
        engine,
        "_run_from_scheduler",
        lambda *_args, **_kwargs: pytest.fail("the scheduler must not start a run here"),
    )


def test_scheduler_creates_its_schema_on_a_fresh_install(engine, monkeypatch):
    prepare_scheduler(monkeypatch, engine, scheduler_settings())
    for suffix in ("", "-wal", "-shm"):
        Path(f"{engine.DATABASE_FILE}{suffix}").unlink(missing_ok=True)
    assert not engine.DATABASE_FILE.exists()

    engine.scheduler_tick()

    # Reading meta proves the schema was created before the scheduler used it.
    with engine._session() as connection:
        assert engine._get_meta(connection, "last_run_date") == ""


@pytest.mark.parametrize(
    ("schedule", "due_today"),
    [
        ("0 3 * * *", True),  # daily, 03:00 already passed
        ("0 3 * * 1", True),  # Monday, and the tick is on a Monday
        ("0 3 * * 2", False),  # Tuesday-only schedule must not catch up on Monday
        ("*/30 3 * * *", True),  # stepped minute field, 03:00 already fired
        ("0 5 * * *", False),  # 05:00 has not fired yet at 03:15
    ],
)
def test_catch_up_only_after_a_real_cron_match_today(
    engine, monkeypatch, schedule, due_today
):
    prepare_scheduler(monkeypatch, engine, scheduler_settings(schedule=schedule))
    monday = datetime(2026, 11, 23, 3, 15)
    assert monday.weekday() == 0
    monkeypatch.setattr(engine, "now_local", lambda: monday)

    engine.scheduler_tick()

    with engine._session() as connection:
        due = engine._get_meta(connection, "due_date")
    assert bool(due) is due_today, f"due_date={due!r} for {schedule}"


def test_scheduler_does_nothing_when_disabled(engine, monkeypatch):
    prepare_scheduler(monkeypatch, engine, scheduler_settings(enabled=False))
    for suffix in ("", "-wal", "-shm"):
        Path(f"{engine.DATABASE_FILE}{suffix}").unlink(missing_ok=True)

    engine.scheduler_tick()

    # A disabled scheduler must not create storage on its own.
    assert not engine.DATABASE_FILE.exists()


# --------------------------------------------------------------------------- #
# safe_llm_error()
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("", ""),
        ("empty_model_answer", "empty_model_answer"),
        ("401 Client Error: Unauthorized for url: https://api.example/v1", "auth"),
        ("403 Forbidden: invalid API key", "auth"),
        ("429 Too Many Requests", "rate_limit"),
        ("HTTPSConnectionPool read timeout", "timeout"),
        ("Connection reset by peer", "connection"),
        ("404 model not found", "model_missing"),
        ("No API key is configured", "missing_key"),
        ("something unexpected happened", "model_error"),
    ],
)
def test_safe_llm_error_maps_failures_to_categories(engine, message, expected):
    assert engine.safe_llm_error(message) == expected


def test_safe_llm_error_never_returns_raw_exception_text(engine):
    raw = "401 Unauthorized for https://api.example/v1?key=sk-secret-value"
    result = engine.safe_llm_error(raw)
    assert result == "auth"
    assert result in engine.LLM_ERROR_KINDS
    assert "sk-secret-value" not in result
    assert "https://" not in result
