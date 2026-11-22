"""Integration tests for the memory fixes that span app.py and the engine.

Covered here: a keyless loopback endpoint is ready for web chat, a summary
provider never inherits the chat provider's Base URL, a marked tool result is
kept out of the index while an ordinary message that merely starts with "Tool
output" is kept, and a daily note gains only the turns it does not have yet.
"""

import json
from datetime import timedelta

import pytest

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
LOOPBACK = "http://127.0.0.1:8080/v1"
REMOTE = "https://api.example.com/v1"


def provider_settings(provider, *, model="local-model", base_url=LOOPBACK):
    """Build the settings dictionary provider_readiness() reads."""
    return {"provider": provider, "model": model, "base_url": base_url, "api_keys": {}}


def write_history(module, messages, *, age_minutes=90):
    """Write one conversation record where light_sleep will find it.

    The timestamp comes from the engine clock, not a fixed date: the scoring
    phase only looks back ``lookback_days`` (7 by default), so a hard-coded
    date would fall out of the window and silently stop promoting.
    """
    stamp_dt = module.now_local() - timedelta(minutes=age_minutes)
    date = stamp_dt.strftime("%Y-%m-%d")
    folder = module.HISTORY_ROOT / date
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
    path = folder / f"{stamp_dt.strftime('%H-%M-%S')}_{CONVERSATION_ID}.json"
    path.write_text(
        json.dumps(record), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# provider_readiness(): a local model server needs no key
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider", ["openai", "or", "groq", "hf"])
def test_openai_compatible_loopback_without_a_key_is_ready(engine, provider):
    import app

    result = app.provider_readiness(provider_settings(provider))

    assert result["ready"] is True
    assert result["checked"] == "local"
    assert result["reason"] == ""
    assert app.keyless_loopback_provider(provider, provider_settings(provider)) is True


@pytest.mark.parametrize("provider", ["gemini", "anthropic"])
def test_providers_that_always_need_a_key_stay_not_ready_on_loopback(engine, provider):
    import app

    result = app.provider_readiness(provider_settings(provider))

    assert result["ready"] is False
    assert result["checked"] == "local"
    assert result["reason"]
    assert app.keyless_loopback_provider(provider, provider_settings(provider)) is False


def test_loopback_without_a_model_is_not_ready(engine):
    import app

    result = app.provider_readiness(provider_settings("openai", model=""))

    assert result["ready"] is False
    assert result["checked"] == "local"


def test_a_remote_endpoint_still_requires_a_key(engine):
    import app

    result = app.provider_readiness(provider_settings("openai", base_url=REMOTE))

    assert result["ready"] is False
    assert result["checked"] == "local"


def test_model_discovery_only_allows_a_keyless_loopback_endpoint(engine, monkeypatch):
    import app
    import core.providers

    calls = []

    def fake_models_get(url, *, timeout, headers=None, params=None):
        calls.append({"url": url, "headers": headers})

        class FakeResponse:
            def json(self):
                return {"data": [{"id": "local-model"}]}

        return FakeResponse()

    # list_models() calls this in core.providers, next to the code that sends it.
    monkeypatch.setattr(core.providers, "provider_models_get", fake_models_get)
    # Reuse the keyless rule; no network request is made.
    assert app.list_models("openai", provider_settings("openai")) == [
        {"id": "local-model", "name": "local-model"}
    ]
    assert calls[0]["headers"] is None
    assert calls[0]["url"] == f"{LOOPBACK}/models"

    with pytest.raises(RuntimeError):
        app.list_models("openai", provider_settings("openai", base_url=REMOTE))


# --------------------------------------------------------------------------- #
# _llm_settings(): the summary provider never gets the chat endpoint
# --------------------------------------------------------------------------- #


def test_summary_provider_does_not_inherit_the_chat_base_url(engine):
    chat = {"provider": "openai", "base_url": "https://proxy.example/v1", "model": "chat"}

    llm = engine._llm_settings(chat, {"provider": "gemini", "model": "g", "base_url": ""})

    assert llm["provider"] == "gemini"
    assert "base_url" not in llm
    # The caller's settings are not mutated by the summary copy.
    assert chat["base_url"] == "https://proxy.example/v1"


def test_summary_provider_keeps_a_memory_specific_base_url(engine):
    chat = {"provider": "openai", "base_url": "https://proxy.example/v1", "model": "chat"}
    local = "http://127.0.0.1:11434/v1"

    llm = engine._llm_settings(
        chat, {"provider": "gemini", "model": "g", "base_url": local}
    )

    assert llm["base_url"] == local


def test_summary_same_provider_or_inherited_provider_keeps_the_chat_base_url(engine):
    chat = {"provider": "openai", "base_url": "https://proxy.example/v1", "model": "chat"}

    same = engine._llm_settings(chat, {"provider": "openai", "model": "", "base_url": ""})
    inherited = engine._llm_settings(chat, {"provider": "", "model": "", "base_url": ""})

    assert same["base_url"] == "https://proxy.example/v1"
    assert inherited["base_url"] == "https://proxy.example/v1"


# --------------------------------------------------------------------------- #
# Tool results come from the stored marker, not from the first words
# --------------------------------------------------------------------------- #


def test_tool_result_is_read_from_the_stored_marker(engine):
    assert engine._is_tool_result({"role": "user", "content": "x", "tool_result": True}) is True
    assert engine._is_tool_result({"role": "user", "content": "x", "tool_result": False}) is False
    assert engine._is_tool_result({"role": "user", "content": "Tool output should be archived"}) is False
    assert engine._is_tool_result(None) is False


def test_light_sleep_skips_marked_tool_output_but_indexes_real_messages(engine):
    write_history(
        engine,
        [
            {"role": "user", "content": "Tool output should be archived separately"},
            {"role": "assistant", "content": "Understood."},
            {
                "role": "user",
                "content": "remember that the deploy key lives in the safe",
                "tool_result": True,
            },
            {"role": "assistant", "content": "Noted, I will remember that."},
        ],
    )
    config = engine.normalize_settings({"llm": False})

    with engine._session() as connection:
        connection.isolation_level = None
        connection.execute("BEGIN")
        stats = engine.light_sleep(connection, config, "run-tool", dry_run=True)
        user_texts = [
            row["text"]
            for row in connection.execute("SELECT text FROM message WHERE role = 'user'")
        ]
        candidates = [
            row["text"] for row in connection.execute("SELECT text FROM candidate")
        ]
        connection.execute("ROLLBACK")

    assert user_texts == ["Tool output should be archived separately"]
    assert candidates == ["Tool output should be archived separately"]
    # Both assistants plus the one real user turn were indexed.
    assert stats["messages"] == 3


# --------------------------------------------------------------------------- #
# Daily notes gain only turns that are not in the note yet
# --------------------------------------------------------------------------- #


def test_daily_note_appends_only_new_turns(engine):
    date = "2026-11-21"
    first = [(0, "You", "first question"), (1, "Assistant", "first reply")]

    assert engine._append_daily_note(CONVERSATION_ID, "Chat", date, first) is True
    note = engine._day_note_path(date)
    text = note.read_text(encoding="utf-8")
    assert text.count("first question") == 1
    assert text.count("first reply") == 1
    assert "<!-- conv:" in text and "<!-- msg:0 -->" in text

    later = first + [(2, "You", "later question")]
    assert engine._append_daily_note(CONVERSATION_ID, "Chat", date, later) is True
    text = note.read_text(encoding="utf-8")
    assert text.count("first question") == 1
    assert text.count("first reply") == 1
    assert text.count("later question") == 1
    # The later turn is inside the existing conversation block, not a new one.
    assert text.count("<!-- conv:") == 1

    assert engine._append_daily_note(CONVERSATION_ID, "Chat", date, [(2, "You", "later question")]) is False
    assert engine._append_daily_note(CONVERSATION_ID, "Chat", date, []) is False


def test_daily_note_keeps_owner_edits_and_adds_other_conversations(engine):
    date = "2026-11-21"
    assert engine._append_daily_note(
        CONVERSATION_ID, "Chat", date, [(0, "You", "hello")]
    ) is True
    note = engine._day_note_path(date)
    note.write_text(note.read_text(encoding="utf-8") + "\nmy edit\n", encoding="utf-8")

    other = "ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert engine._append_daily_note(other, "Second chat", date, [(0, "You", "other chat")]) is True

    text = note.read_text(encoding="utf-8")
    assert "my edit" in text
    assert text.count("<!-- conv:") == 2
    assert text.count("## Second chat") == 1
