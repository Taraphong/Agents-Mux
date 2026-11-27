"""The legacy api_key migration must write normalized settings, under the lock.

The old single key slot is moved on load. Writing the file inside the migration
would store raw custom keys and an unclamped update block, so the write happens
after normalization instead.
"""

import json

import pytest

import core.settings as settings_module


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / ".app-settings.json"
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", path)
    monkeypatch.setattr(settings_module, "forget_model_names", lambda: None)
    return path


def test_legacy_key_migration_writes_normalized_settings(settings_file):
    settings_file.write_text(
        json.dumps(
            {
                "api_key": "sk-legacy",
                "provider": "gemini",
                "custom_api_keys": {"1bad": "x", "GOOD_KEY": "  y  "},
                "update": {"auto_check": "yes", "idle_minutes": 99999},
            }
        ),
        encoding="utf-8",
    )

    loaded = settings_module.load_settings()

    assert loaded["api_keys"] == {"gemini": "sk-legacy"}
    assert loaded["custom_api_keys"] == {"GOOD_KEY": "y"}
    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "api_key" not in stored
    assert stored["api_keys"] == {"gemini": "sk-legacy"}
    assert stored["custom_api_keys"] == {"GOOD_KEY": "y"}
    assert stored["update"] == {"auto_check": True, "idle_minutes": 1440}


def test_load_does_not_rewrite_an_already_migrated_file(settings_file):
    settings_file.write_text(json.dumps({"api_keys": {"openai": "k"}}), encoding="utf-8")
    before = settings_file.read_text(encoding="utf-8")
    settings_module.load_settings()
    assert settings_file.read_text(encoding="utf-8") == before


def test_save_settings_is_reentrant_under_the_lock(settings_file):
    # /api/settings already holds SETTINGS_LOCK when it saves, so save_settings
    # must take the same (re-entrant) lock without deadlocking the caller.
    with settings_module.SETTINGS_LOCK:
        settings_module.save_settings({"agent_name": "Mux"})
    assert json.loads(settings_file.read_text(encoding="utf-8"))["agent_name"] == "Mux"
