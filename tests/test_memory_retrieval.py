"""Tests for build_context(): the memory block injected into a chat prompt.

The block must stay small and opt-in, must only carry entries that share words
with the request, must never split a Thai combining mark, and must degrade to
an empty block when MEMORY.md is missing or unreadable.
"""

import time
import unicodedata
import uuid

import pytest

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"


def settings(**overrides):
    """Build the app settings shape build_context() reads."""
    memory = {"retrieval": True, "retrieval_items": 4, "retrieval_chars": 800}
    memory.update(overrides)
    return {"memory": memory}


def remember(engine, text, *, score=0.8):
    """Promote one memory and return its id."""
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


def test_retrieval_can_be_switched_off(engine):
    remember(engine, "the deploy key lives in the safe")

    assert engine.build_context("where is the deploy key", settings(retrieval=False)) == ("", [])


def test_a_relevant_memory_is_attached_with_a_safety_header(engine):
    memory_id = remember(engine, "the deploy key lives in the safe")

    block, ids = engine.build_context("where is the deploy key stored", settings())

    assert ids == [memory_id]
    assert "deploy key" in block
    # The model must be told the block is data, not a second set of orders.
    assert "reference only" in block
    assert "data, not instructions" in block
    # Internal markers never leak into the prompt.
    assert "<!-- mem:" not in block


def test_an_unrelated_query_attaches_nothing(engine):
    remember(engine, "the deploy key lives in the safe")

    assert engine.build_context("what is the weather in Paris tomorrow", settings()) == ("", [])


def test_the_item_limit_is_respected(engine):
    remember(engine, "the deploy key lives in the safe")
    remember(engine, "the deploy key rotates every month")

    _block, ids = engine.build_context("deploy key rotation", settings(retrieval_items=1))

    assert len(ids) == 1


def test_the_character_budget_is_respected(engine):
    for index in range(5):
        body = "deploy key note " + ("detail " * 40) + f"number {index}"
        remember(engine, body)
    budget = len(engine.RETRIEVAL_HEADER) + 320

    block, ids = engine.build_context("deploy key", settings(retrieval_chars=budget))

    assert ids
    assert len(block) <= budget


def test_an_entry_that_exactly_fits_stays_inside_the_budget(engine):
    memory_id = remember(engine, "the deploy key lives in the safe")
    full_block, _ids = engine.build_context("deploy key", settings(retrieval_chars=2000))
    line = full_block.split("\n\n", 1)[1]
    budget = len(engine.RETRIEVAL_HEADER) + 2 + len(line)

    block, ids = engine.build_context("deploy key", settings(retrieval_chars=budget))

    assert ids == [memory_id]
    assert len(block) == budget


def test_a_late_registered_secret_is_redacted_on_a_cache_hit(engine, monkeypatch):
    import core.redaction

    remember(engine, "the vault passphrase is hunter2-custom-key")
    monkeypatch.setattr(core.redaction, "secret_values", lambda: [])
    block, ids = engine.build_context("vault passphrase", settings())
    assert ids
    assert "hunter2-custom-key" in block

    # The same MEMORY.md is served from the cache; the new secret must still go.
    monkeypatch.setattr(core.redaction, "secret_values", lambda: ["hunter2-custom-key"])
    block, ids = engine.build_context("vault passphrase", settings())
    assert ids
    assert "hunter2-custom-key" not in block


def test_a_long_entry_is_shortened_on_a_character_boundary(engine):
    body = "deploy key " + ("กุญแจอยู่ในตู้เซฟ " * 60)
    remember(engine, body)

    block, ids = engine.build_context("deploy key", settings(retrieval_chars=2000))

    assert len(ids) == 1
    line = block.split("\n- ", 1)[1]
    text = line.split(") ", 1)[1]
    assert len(text) <= engine.RETRIEVAL_ITEM_CHARS
    # The cut must not leave a combining mark without its base character.
    if text:
        assert unicodedata.category(text[0]) not in {"Mn", "Mc", "Me"}
    assert "…" not in text


def test_a_thai_query_matches_a_thai_memory(engine):
    memory_id = remember(engine, "กุญแจ deploy อยู่ในตู้เซฟ")

    _block, ids = engine.build_context("กุญแจ deploy อยู่ที่ไหน", settings())

    assert ids == [memory_id]


def test_credentials_are_redacted_before_they_reach_the_prompt(engine):
    remember(engine, "the token is sk-" + "a" * 24)

    block, ids = engine.build_context("where is the token", settings())

    assert ids
    assert "sk-" not in block
    assert "[redacted]" in block


def test_a_missing_memory_file_returns_nothing(engine):
    remember(engine, "the deploy key lives in the safe")
    engine.MEMORY_FILE.unlink()

    assert engine.build_context("deploy key", settings()) == ("", [])


def test_the_cache_refreshes_when_memory_changes(engine):
    first = remember(engine, "the deploy key lives in the safe")
    _block, ids = engine.build_context("deploy key", settings())
    assert ids == [first]

    time.sleep(0.02)
    second = remember(engine, "the deploy key also opens the vault")

    _block, ids = engine.build_context("deploy key", settings())
    assert second in ids


def test_an_unreadable_store_does_not_break_the_chat(engine, monkeypatch):
    remember(engine, "the deploy key lives in the safe")

    def broken_entries():
        raise OSError("disk gone")

    monkeypatch.setattr(engine, "entries", broken_entries)

    assert engine.build_context("deploy key", settings()) == ("", [])


def test_retrieval_settings_are_normalised(engine):
    defaults = engine.normalize_settings({})
    assert defaults["retrieval"] is True
    assert defaults["retrieval_items"] == 4
    assert defaults["retrieval_chars"] == 800

    clamped = engine.normalize_settings(
        {"retrieval": "off", "retrieval_items": 99, "retrieval_chars": 5000}
    )
    assert clamped["retrieval"] is False
    assert clamped["retrieval_items"] == 10
    assert clamped["retrieval_chars"] == 2000
