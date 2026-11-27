"""Settings responses must not leak credentials embedded in a Base URL.

A self-hosted chat or memory endpoint can carry credentials
(https://user:token@host/v1) and the settings page only needs the endpoint.
Saving the masked value back must keep the stored URL instead of overwriting
it with the mask, and the memory status report masks the same value.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

import core.settings_update as settings_update_module
import routes.index as index_routes
import routes.shared as shared_routes
from core.redaction import mask_url_credentials

CHAT_URL = "https://chat:s3cret@llm.example/v1"
MEMORY_URL = "https://memory:memsecret@local.example/v1"


@pytest.fixture()
def settings_app(monkeypatch):
    """Expose /api/settings over a stored chat and memory URL with credentials."""
    stored = {
        "provider": "openai",
        "base_url": CHAT_URL,
        "memory": {"base_url": MEMORY_URL},
        "discord_enabled": False,
        "skills": [],
    }
    saved = {}

    def fresh():
        return {**stored, "memory": dict(stored["memory"])}

    for module in (index_routes, shared_routes):
        monkeypatch.setattr(module, "load_settings", fresh)
    monkeypatch.setattr(index_routes, "get_api_key", lambda provider, settings=None: "k")
    monkeypatch.setattr(index_routes, "key_is_configured", lambda provider, settings=None: True)
    monkeypatch.setattr(index_routes, "stored_custom_api_keys", lambda settings=None: {})
    monkeypatch.setattr(index_routes, "get_discord_token", lambda settings=None: "")
    monkeypatch.setattr(index_routes, "discord_status", lambda: {})
    monkeypatch.setattr(index_routes, "list_skills", lambda: [])
    monkeypatch.setattr(index_routes, "apply_settings_update", shared_routes.apply_settings_update)
    # The skills filter moved into the shared settings write path.
    monkeypatch.setattr(settings_update_module, "list_skills", lambda: [])
    monkeypatch.setattr(shared_routes, "save_settings", lambda value: saved.update(value))
    monkeypatch.setattr(shared_routes, "key_is_configured", lambda provider, settings=None: True)
    monkeypatch.setattr(shared_routes, "start_discord_bot", lambda: None)
    monkeypatch.setattr(shared_routes, "stop_discord_bot", lambda: None)

    app = Flask(__name__)
    app.register_blueprint(index_routes.index_bp)
    return SimpleNamespace(client=app.test_client(), saved=saved)


def test_settings_response_masks_credentials_in_both_base_urls(settings_app):
    body = settings_app.client.get("/api/settings").get_json()
    assert body["base_url"] == "https://chat:••••••••@llm.example/v1"
    assert body["memory"]["base_url"] == "https://memory:••••••••@local.example/v1"
    assert "s3cret" not in str(body)
    assert "memsecret" not in str(body)


def test_saving_the_masked_urls_keeps_the_stored_urls(settings_app):
    body = settings_app.client.get("/api/settings").get_json()
    response = settings_app.client.put(
        "/api/settings",
        json={"base_url": body["base_url"], "memory": body["memory"]},
    )
    assert response.status_code == 200
    assert settings_app.saved["base_url"] == CHAT_URL
    assert settings_app.saved["memory"]["base_url"] == MEMORY_URL


def test_a_real_new_url_is_still_saved(settings_app):
    response = settings_app.client.put(
        "/api/settings",
        json={
            "base_url": "https://new:other@new.example/v1",
            "memory": {"base_url": "https://mem:new@mem.example/v1"},
        },
    )
    assert response.status_code == 200
    assert settings_app.saved["base_url"] == "https://new:other@new.example/v1"
    assert settings_app.saved["memory"]["base_url"] == "https://mem:new@mem.example/v1"


def test_memory_status_masks_credentials_in_its_base_url(settings_app, monkeypatch):
    monkeypatch.setattr(
        index_routes.memory_engine,
        "status",
        lambda settings: {
            "enabled": True,
            "base_url": "https://memory:memsecret@local.example/v1",
        },
    )
    body = settings_app.client.get("/api/memory/status").get_json()
    assert body["base_url"] == "https://memory:••••••••@local.example/v1"
    assert "memsecret" not in str(body)
    assert "local.example" in body["base_url"]


def test_memory_status_keeps_a_url_without_credentials(settings_app, monkeypatch):
    monkeypatch.setattr(
        index_routes.memory_engine,
        "status",
        lambda settings: {"enabled": True, "base_url": "http://127.0.0.1:11434/v1"},
    )
    body = settings_app.client.get("/api/memory/status").get_json()
    assert body["base_url"] == "http://127.0.0.1:11434/v1"


def test_mask_url_credentials_keeps_the_host():
    assert mask_url_credentials(CHAT_URL) == "https://chat:••••••••@llm.example/v1"
    assert mask_url_credentials("https://token@host.example/v1") == "https://••••••••@host.example/v1"
    assert mask_url_credentials("https://host.example/v1") == "https://host.example/v1"
    assert mask_url_credentials("") == ""
