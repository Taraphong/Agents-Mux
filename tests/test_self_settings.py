"""The AI can change its own settings, but never its own permission gate.

``get_settings`` returns a masked report and needs no approval, while every
``update_settings`` call goes through the normal approval policy. Stored secrets
and the tool-permission switches stay write-only from the Settings page.
"""

import json

import pytest

import core.settings_update as settings_update
from core.config import APPROVAL_REQUIRED_TOOLS, MACHINE_TOOL_NAMES
from core.settings import DEFAULT_SETTINGS
from core.tools import approval_required_tools, run_local_tool


def base_settings(**overrides) -> dict:
    settings = {**DEFAULT_SETTINGS, "memory": dict(DEFAULT_SETTINGS["memory"])}
    settings["api_keys"] = {"openai": "sk-secret-value"}
    settings["custom_api_keys"] = {"WEATHER_KEY": "weather-secret"}
    settings["discord_token"] = "discord-secret"
    settings.update(overrides)
    return settings


@pytest.fixture()
def stored(monkeypatch):
    """Settings storage that never touches the real .app-settings.json."""
    state = {"settings": base_settings()}

    def load():
        return {**state["settings"], "memory": dict(state["settings"]["memory"])}

    monkeypatch.setattr(settings_update, "load_settings", load)
    monkeypatch.setattr(settings_update, "save_settings", lambda value: state.update(settings=value))
    monkeypatch.setattr(settings_update, "list_skills", lambda: [])
    return state


def test_get_settings_never_returns_a_secret(stored):
    result = run_local_tool("get_settings", {})

    payload = json.dumps(result)
    assert "sk-secret-value" not in payload
    assert "weather-secret" not in payload
    assert "discord-secret" not in payload
    assert result["settings"]["has_api_key"] is True
    assert result["settings"]["custom_api_keys"] == ["WEATHER_KEY"]
    assert result["settings"]["has_discord_token"] is True


def test_update_settings_needs_approval_first(stored):
    with pytest.raises(PermissionError):
        run_local_tool("update_settings", {"settings": {"agent_name": "Nova"}})

    assert stored["settings"]["agent_name"] == "Mux"


def test_an_approved_update_changes_the_agents_name_and_style(stored):
    result = run_local_tool(
        "update_settings",
        {"settings": {"agent_name": "Nova", "response_style": "Direct and technical"}},
        approved=True,
    )

    assert stored["settings"]["agent_name"] == "Nova"
    assert stored["settings"]["response_style"] == "Direct and technical"
    assert set(result["updated"]) == {"agent_name", "response_style"}
    assert result["settings"]["agent_name"] == "Nova"


def test_keys_beside_the_tool_name_are_accepted(stored):
    run_local_tool("update_settings", {"agent_role": "A research assistant"}, approved=True)

    assert stored["settings"]["agent_role"] == "A research assistant"


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": "sk-attacker"},
        {"api_keys": {"openai": "sk-attacker"}},
        {"custom_api_key": {"name": "OTHER", "value": "x"}},
        {"discord_token": "token"},
        {"machine_access": False},
        {"command_mode": "auto"},
        {"nonsense": 1},
    ],
)
def test_the_agent_cannot_write_secrets_permissions_or_unknown_keys(stored, body):
    with pytest.raises(ValueError):
        run_local_tool("update_settings", {"settings": body}, approved=True)

    assert stored["settings"]["api_keys"] == {"openai": "sk-secret-value"}
    assert stored["settings"]["machine_access"] is True
    assert stored["settings"]["command_mode"] == "manual"


def test_numeric_values_are_clamped_into_range(stored):
    run_local_tool(
        "update_settings",
        {"settings": {"temperature": 99, "top_p": -1, "max_tokens": "lots"}},
        approved=True,
    )

    settings = stored["settings"]
    assert settings["temperature"] == 2.0
    assert settings["top_p"] == 0.0
    assert settings["max_tokens"] == DEFAULT_SETTINGS["max_tokens"]


def test_a_base_url_from_another_provider_is_passed_through(stored):
    run_local_tool(
        "update_settings",
        {"settings": {"provider": "groq", "model": "llama-3.3-70b-versatile"}},
        approved=True,
    )

    assert stored["settings"]["provider"] == "groq"
    assert stored["settings"]["model"] == "llama-3.3-70b-versatile"


def test_a_chat_approval_lets_the_ai_change_its_name(stored, monkeypatch):
    """The real /api/chat -> /api/tools/execute loop: ask, approve, then save."""
    import app as app_module  # noqa: F401 - imported for the app fixture side effects
    import core.tools
    import routes.index as index_routes
    from flask import Flask

    settings = stored["settings"]
    answers = [
        '<tool_call>{"name":"update_settings","arguments":{"settings":{"agent_name":"Nova"}}}</tool_call>',
        "I am Nova now.",
    ]
    monkeypatch.setattr(index_routes, "rate_limit_response", lambda *_a, **_k: None)
    monkeypatch.setattr(index_routes, "load_settings", lambda: settings)
    monkeypatch.setattr(core.tools, "load_settings", lambda: settings)
    monkeypatch.setattr(index_routes, "build_system_prompt", lambda *_a, **_k: "system")
    monkeypatch.setattr(index_routes, "call_provider", lambda *_a, **_k: (answers.pop(0), {}))
    monkeypatch.setattr(index_routes, "log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(core.tools, "log_event", lambda *_a, **_k: None)

    app = Flask(__name__)
    app.register_blueprint(index_routes.index_bp)
    client = app.test_client()

    body = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "rename yourself"}], "lang": "en", "command_mode": "manual"},
    ).get_json()
    assert body["tool_request"]["name"] == "update_settings"
    assert body["approval_id"]

    arguments = body["tool_request"]["arguments"]
    denied = client.post(
        "/api/tools/execute",
        json={"name": "update_settings", "arguments": arguments, "command_mode": "manual"},
    )
    assert denied.status_code == 403
    assert stored["settings"]["agent_name"] == "Mux"

    approved = client.post(
        "/api/tools/execute",
        json={
            "name": "update_settings",
            "arguments": arguments,
            "approval_id": body["approval_id"],
            "command_mode": "manual",
        },
    )
    assert approved.status_code == 200
    assert approved.get_json()["ok"] is True
    assert stored["settings"]["agent_name"] == "Nova"


def test_settings_tools_follow_the_approval_policy():
    assert "update_settings" in APPROVAL_REQUIRED_TOOLS
    assert "update_settings" in MACHINE_TOOL_NAMES
    assert "update_settings" in approval_required_tools({"machine_access": False})
    # Reading the masked report is harmless, so it never stops for an approval.
    assert "get_settings" not in approval_required_tools({"machine_access": True})
    assert "get_settings" not in approval_required_tools({"machine_access": False})
