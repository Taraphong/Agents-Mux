"""Tests for pinning memories and the MEMORY.md entry cap.

A pin lives in the entry's hidden marker, survives new promotions, and keeps
an entry from being evicted when the file is trimmed to its cap.
"""

import uuid

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

    missing_id = str(uuid.uuid4())
    with app_module.app.test_request_context(
        f"/api/memory/entries/{missing_id}/pin", method="PUT", json={"pinned": True}
    ):
        _missing, missing_status = index_routes.memory_entry_pin(missing_id)
    assert missing_status == 404
