"""Tests for DREAMS.md writing.

The nightly summary and its trim both replace the file through the same
temporary-file helper MEMORY.md uses, so a failed write keeps the old text.
"""

import pytest


def dream_message(engine):
    engine.write_dreams(
        {"messages": 3, "candidates_in_window": 2, "themes": ["deploy"]},
        [{"theme": "deploy", "text": "the key lives in the safe"}],
        "en",
    )


def test_write_dreams_creates_the_file_with_header_and_section(engine):
    dream_message(engine)

    text = engine.DREAMS_FILE.read_text(encoding="utf-8")
    assert text.startswith("# DREAMS\n")
    assert "## " in text
    assert "the key lives in the safe" in text


def test_write_dreams_appends_without_dropping_earlier_sections(engine):
    dream_message(engine)
    first = engine.DREAMS_FILE.read_text(encoding="utf-8")

    engine.write_dreams(
        {"messages": 1, "candidates_in_window": 1, "themes": ["later"]},
        [{"theme": "later", "text": "second night note"}],
        "en",
    )
    text = engine.DREAMS_FILE.read_text(encoding="utf-8")

    assert text.startswith(first)
    assert text.count("## ") == first.count("## ") + 1
    assert "second night note" in text


def test_a_failed_dreams_write_keeps_the_existing_file(engine, monkeypatch):
    dream_message(engine)
    original = engine.DREAMS_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        engine.write_dreams(
            {"messages": 1, "candidates_in_window": 1, "themes": []}, [], "en"
        )

    assert engine.DREAMS_FILE.read_text(encoding="utf-8") == original
    assert not list(engine.DREAMS_FILE.parent.glob(".DREAMS.md.*.tmp"))


def test_a_failed_dreams_create_leaves_no_file_or_temp(engine, monkeypatch):
    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        dream_message(engine)

    assert not engine.DREAMS_FILE.exists()
    assert not list(engine.DREAMS_FILE.parent.glob(".DREAMS.md.*.tmp"))


def test_a_failed_dreams_trim_keeps_the_existing_file(engine, monkeypatch):
    engine.DREAMS_FILE.write_text(
        "# DREAMS\n\nNightly notes from the memory filter.\n"
        + "".join(f"\n## 2026-01-0{day} 03:00\n- note {day}\n" for day in range(1, 9)),
        encoding="utf-8",
    )
    engine.DREAMS_MAX_BYTES = 200
    original = engine.DREAMS_FILE.read_text(encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)
    with pytest.raises(OSError):
        engine._trim_dreams()

    assert engine.DREAMS_FILE.read_text(encoding="utf-8") == original
    assert not list(engine.DREAMS_FILE.parent.glob(".DREAMS.md.*.tmp"))


def test_dreams_trim_keeps_the_newest_sections(engine):
    engine.DREAMS_FILE.write_text(
        "# DREAMS\n\nNightly notes from the memory filter.\n"
        + "".join(f"\n## 2026-01-0{day} 03:00\n- note {day}\n" for day in range(1, 9)),
        encoding="utf-8",
    )
    engine.DREAMS_MAX_BYTES = 200

    engine._trim_dreams()
    text = engine.DREAMS_FILE.read_text(encoding="utf-8")

    assert text.startswith("# DREAMS\n")
    assert "note 8" in text
    assert "note 1" not in text
    assert len(text.encode("utf-8")) <= engine.DREAMS_MAX_BYTES
