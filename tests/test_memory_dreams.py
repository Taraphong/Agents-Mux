"""Tests for DREAMS.md writing.

The nightly summary and its trim both replace the file through the same
temporary-file helper MEMORY.md uses, so a failed write keeps the old text.
"""

import pytest

HEADER = "# DREAMS\n\nNightly notes from the memory filter.\n"


def write_night(engine, note):
    engine.write_dreams(
        {"messages": 3, "candidates_in_window": 2, "themes": ["deploy"]},
        [{"theme": "deploy", "text": note}],
        "en",
    )


def seed_sections(engine, count):
    engine.DREAMS_FILE.write_text(
        HEADER + "".join(f"\n## 2026-01-0{n} 03:00\n- note {n}\n" for n in range(1, count + 1)),
        encoding="utf-8",
    )
    engine.DREAMS_MAX_BYTES = 200


def fail_replace(engine, monkeypatch):
    def failing_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.os, "replace", failing_replace)


def no_temp_files(engine):
    return not list(engine.DREAMS_FILE.parent.glob(".DREAMS.md.*.tmp"))


def test_write_dreams_creates_then_appends_sections(engine):
    write_night(engine, "the key lives in the safe")
    first = engine.DREAMS_FILE.read_text(encoding="utf-8")
    assert first.startswith(HEADER)
    assert "the key lives in the safe" in first

    write_night(engine, "second night note")
    text = engine.DREAMS_FILE.read_text(encoding="utf-8")

    assert text.startswith(first)
    assert text.count("## ") == first.count("## ") + 1
    assert "second night note" in text


def test_a_failed_dreams_write_keeps_the_existing_file(engine, monkeypatch):
    write_night(engine, "first night note")
    original = engine.DREAMS_FILE.read_text(encoding="utf-8")

    fail_replace(engine, monkeypatch)
    with pytest.raises(OSError):
        write_night(engine, "never written")

    assert engine.DREAMS_FILE.read_text(encoding="utf-8") == original
    assert no_temp_files(engine)


def test_a_failed_dreams_create_leaves_no_file_or_temp(engine, monkeypatch):
    fail_replace(engine, monkeypatch)
    with pytest.raises(OSError):
        write_night(engine, "first night note")

    assert not engine.DREAMS_FILE.exists()
    assert no_temp_files(engine)


def test_a_failed_dreams_trim_keeps_the_existing_file(engine, monkeypatch):
    seed_sections(engine, 8)
    original = engine.DREAMS_FILE.read_text(encoding="utf-8")

    fail_replace(engine, monkeypatch)
    with pytest.raises(OSError):
        engine._trim_dreams()

    assert engine.DREAMS_FILE.read_text(encoding="utf-8") == original
    assert no_temp_files(engine)


def test_dreams_trim_keeps_the_newest_sections(engine):
    seed_sections(engine, 8)

    engine._trim_dreams()
    text = engine.DREAMS_FILE.read_text(encoding="utf-8")

    assert text.startswith(HEADER)
    assert "note 8" in text
    assert "note 1" not in text
    assert len(text.encode("utf-8")) <= engine.DREAMS_MAX_BYTES
