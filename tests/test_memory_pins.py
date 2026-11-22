"""Tests for pinning memories and the MEMORY.md entry cap.

A pin lives in the entry's hidden marker, survives new promotions, and keeps
an entry from being evicted when the file is trimmed to its cap.
"""

import json
import uuid
from datetime import timedelta

import pytest

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"


def remember(engine, text, *, score=0.5):
    item = {
        "id": str(uuid.uuid4()),
        "text": text,
        "score": score,
        "theme": "topic",
        "conversation_id": CONVERSATION_ID,
        "norm_hash": engine._hash(engine.compare_text(text).lower()),
    }
    assert engine.promote([item], limit=10)
    return item["id"]


def by_id(engine):
    return {item["id"]: item for item in engine.entries()}


def write_history(module, messages, *, age_minutes=90):
    stamp_dt = module.now_local() - timedelta(minutes=age_minutes)
    folder = module.HISTORY_ROOT / stamp_dt.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = stamp_dt.isoformat(timespec="seconds")
    record = {
        "id": CONVERSATION_ID,
        "title": "Test chat",
        "created_at": stamp,
        "updated_at": stamp,
        "locked": False,
        "pinned": False,
        "messages": messages,
    }
    (folder / f"{stamp_dt.strftime('%H-%M-%S')}_{CONVERSATION_ID}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def test_pin_sets_and_clears_the_marker(engine):
    memory_id = remember(engine, "the deploy key lives in the safe")
    assert by_id(engine)[memory_id]["pinned"] is False

    assert engine.pin(memory_id, True) is True
    assert by_id(engine)[memory_id]["pinned"] is True

    # A later promotion rewrites MEMORY.md and must keep the pin.
    remember(engine, "another memory", score=0.6)
    assert by_id(engine)[memory_id]["pinned"] is True

    assert engine.pin(memory_id, False) is True
    assert by_id(engine)[memory_id]["pinned"] is False


def test_pinning_the_same_state_is_idempotent(engine):
    memory_id = remember(engine, "the deploy key lives in the safe")

    assert engine.pin(memory_id, True) is True
    assert engine.pin(memory_id, True) is True
    assert by_id(engine)[memory_id]["pinned"] is True


def test_pin_on_a_missing_entry_returns_false(engine):
    assert engine.pin(str(uuid.uuid4()), True) is False
    assert engine.pin("not-a-uuid", True) is False


def test_pin_is_busy_while_a_run_holds_the_lock(engine):
    memory_id = remember(engine, "the deploy key lives in the safe")

    engine._RUN_LOCK.acquire()
    try:
        with pytest.raises(RuntimeError, match="memory_busy"):
            engine.pin(memory_id, True)
    finally:
        engine._RUN_LOCK.release()

    assert by_id(engine)[memory_id]["pinned"] is False


def test_trim_evicts_the_oldest_unpinned_entries(engine):
    pinned_id = remember(engine, "pinned low score memory", score=0.10)
    second = remember(engine, "second lowest", score=0.20)
    third = remember(engine, "third lowest", score=0.30)
    remember(engine, "fourth", score=0.40)
    remember(engine, "fifth", score=0.50)
    assert engine.pin(pinned_id, True) is True

    removed = engine._trim_to_cap(3)

    assert set(removed) == {second, third}
    remaining = by_id(engine)
    assert len(remaining) == 3
    assert pinned_id in remaining
    assert pinned_id != ""
    assert "pinned low score memory" in remaining[pinned_id]["text"]


def test_trim_does_nothing_when_the_file_is_under_the_cap(engine):
    remember(engine, "one")
    remember(engine, "two")

    assert engine._trim_to_cap(3) == []
    assert len(engine.entries()) == 2


def test_pinned_entries_are_never_evicted_even_over_the_cap(engine):
    first = remember(engine, "first pinned", score=0.1)
    second = remember(engine, "second pinned", score=0.2)
    assert engine.pin(first, True) and engine.pin(second, True)

    assert engine._trim_to_cap(1) == []
    assert len(engine.entries()) == 2


def test_trim_can_protect_the_entries_a_run_just_wrote(engine):
    protected = remember(engine, "new low score entry", score=0.10)
    remember(engine, "middle entry", score=0.30)
    remember(engine, "highest entry", score=0.40)

    removed = engine._trim_to_cap(2, protect={protected})

    assert removed
    assert protected not in removed
    assert protected in by_id(engine)


def test_trim_does_not_protect_more_entries_than_the_cap_allows(engine):
    ids = {remember(engine, f"promoted {index}", score=0.1 + index / 10): index
           for index in range(11)}

    removed = engine._trim_to_cap(10, protect=set(ids))

    assert len(removed) == 1
    assert len(by_id(engine)) == 10
    # The lowest-scoring new entry is the one that has to go.
    assert removed == [min(ids, key=ids.get)]


def test_a_failed_pin_write_leaves_memory_intact(engine, monkeypatch):
    memory_id = remember(engine, "candidate to pin")
    original = engine.MEMORY_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        engine.pin(memory_id, True)

    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == original
    assert by_id(engine)[memory_id]["pinned"] is False
    assert not list(engine.MEMORY_FILE.parent.glob(".MEMORY.md.*.tmp"))


def test_a_failed_promote_write_leaves_memory_intact(engine, monkeypatch):
    remember(engine, "already stored note", score=0.4)
    original = engine.MEMORY_FILE.read_text(encoding="utf-8")
    item = {
        "id": str(uuid.uuid4()),
        "text": "new note that cannot be written",
        "score": 0.6,
        "theme": "topic",
        "conversation_id": CONVERSATION_ID,
        "norm_hash": engine._hash(engine.compare_text("new note that cannot be written").lower()),
    }

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        engine.promote([item], limit=10)

    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == original
    assert not list(engine.MEMORY_FILE.parent.glob(".MEMORY.md.*.tmp"))


def test_a_failed_forget_write_leaves_memory_intact(engine, monkeypatch):
    memory_id = remember(engine, "note to forget")
    original = engine.MEMORY_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        engine.forget(memory_id)

    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == original
    assert memory_id in by_id(engine)
    assert not list(engine.MEMORY_FILE.parent.glob(".MEMORY.md.*.tmp"))


def test_a_failed_recovery_write_keeps_the_memory_file(engine, monkeypatch):
    memory_id = remember(engine, "published before the run failed")
    original = engine.MEMORY_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    # Recovery swallows the write error instead of masking the run failure.
    engine._remove_promoted_entries({memory_id})

    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == original
    assert memory_id in by_id(engine)


def test_a_failed_trim_write_leaves_memory_intact(engine, monkeypatch):
    remember(engine, "kept one", score=0.1)
    remember(engine, "kept two", score=0.2)
    remember(engine, "kept three", score=0.3)
    original = engine.MEMORY_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    removed = engine._trim_to_cap(2)

    assert removed == []
    assert engine.MEMORY_FILE.read_text(encoding="utf-8") == original
    assert not list(engine.MEMORY_FILE.parent.glob(".MEMORY.md.*.tmp"))


def test_a_run_without_promotions_does_not_trim(engine):
    ids = {remember(engine, f"kept memory {index}", score=0.2 + index / 100)
           for index in range(11)}

    result = engine.run(settings={"memory": {"llm": False, "max_entries": 10}}, language="en")

    assert result["stats"]["promoted"] == 0
    assert result["stats"]["evicted"] == 0
    # Lowering the cap only takes effect on a run that promotes something.
    assert set(by_id(engine)) == ids


def test_a_failed_run_does_not_evict_an_old_memory(engine, monkeypatch):
    old_ids = {remember(engine, f"old memory {index}", score=0.1 + index / 100)
               for index in range(10)}
    write_history(
        engine,
        [
            {"role": "user", "content": "remember that the deploy key lives in the safe"},
            {"role": "assistant", "content": "Noted."},
        ],
    )

    def failing_dreams(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine, "write_dreams", failing_dreams)
    with pytest.raises(OSError):
        engine.run(settings={"memory": {"llm": False, "max_entries": 10}}, language="en")

    # The run rolled back before the cap was applied, so every old entry stays.
    remaining = by_id(engine)
    assert set(remaining) == old_ids


def test_max_entries_settings_are_normalised(engine):
    defaults = engine.normalize_settings({})
    assert defaults["max_entries"] == 200

    clamped = engine.normalize_settings({"max_entries": 5000})
    assert clamped["max_entries"] == 1000

    floor = engine.normalize_settings({"max_entries": 1})
    assert floor["max_entries"] == 10


def test_the_pin_route_toggles_and_validates(engine):
    import app as app_module
    import index_routes

    memory_id = remember(engine, "the deploy key lives in the safe")
    url = f"/api/memory/entries/{memory_id}/pin"

    with app_module.app.test_request_context(url, method="PUT", json={"pinned": True}):
        response = index_routes.memory_entry_pin(memory_id)
    assert response.status_code == 200
    assert by_id(engine)[memory_id]["pinned"] is True

    # Error branches return (response, status); direct calls give the tuple.
    with app_module.app.test_request_context(url, method="PUT", json={"pinned": "yes"}):
        _invalid, invalid_status = index_routes.memory_entry_pin(memory_id)
    assert invalid_status == 400

    # A JSON array is truthy but not an object; it must be a 400, not a 500.
    with app_module.app.test_request_context(url, method="PUT", json=["x"]):
        _array, array_status = index_routes.memory_entry_pin(memory_id)
    assert array_status == 400

    missing_id = str(uuid.uuid4())
    with app_module.app.test_request_context(
        f"/api/memory/entries/{missing_id}/pin", method="PUT", json={"pinned": True}
    ):
        _missing, missing_status = index_routes.memory_entry_pin(missing_id)
    assert missing_status == 404
