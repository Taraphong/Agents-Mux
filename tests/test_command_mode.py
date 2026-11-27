"""Command mode decides whether a tool call stops for approval.

The page used to offer three modes, and ``Fast+`` still asked for approval while
Machine access was on. Only Manual and Auto remain: Manual asks before the tool
runs, Auto runs it inside the turn, and the old ``ask``/``fast`` values keep
working for settings saved by an older checkout.
"""

import pytest

TOOL_ANSWER = '<tool_call>{"name":"run_command","arguments":{"command":"pwd"}}</tool_call>'
FINAL_ANSWER = "The working directory is /home/user."


def chat_settings() -> dict:
    return {
        "provider": "openai",
        "model": "test-model",
        "base_url": "",
        "system_prompt": "",
        "machine_access": True,
    }


def run_chat(monkeypatch, command_mode=None):
    """Call the real /api/chat route with a provider that asks for one tool."""
    import app as app_module
    import core.tools
    from routes import index as index_routes

    settings = chat_settings()
    answers = [TOOL_ANSWER, FINAL_ANSWER]
    tool_calls = []

    def fake_provider(messages, _settings):
        return answers.pop(0), {}

    def fake_tool(name, arguments, approved=False):
        tool_calls.append({"name": name, "arguments": arguments, "approved": approved})
        return {"tool": name, "stdout": "/home/user", "returncode": 0}

    monkeypatch.setattr(index_routes, "rate_limit_response", lambda *_a, **_k: None)
    monkeypatch.setattr(index_routes, "load_settings", lambda: settings)
    monkeypatch.setattr(index_routes, "build_system_prompt", lambda *_a, **_k: "system")
    monkeypatch.setattr(index_routes, "call_provider", fake_provider)
    monkeypatch.setattr(index_routes, "run_local_tool", fake_tool)
    monkeypatch.setattr(index_routes, "log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(core.tools, "load_settings", lambda: settings)

    payload = {"messages": [{"role": "user", "content": "pwd"}], "lang": "en"}
    if command_mode is not None:
        payload["command_mode"] = command_mode
    with app_module.app.test_request_context("/api/chat", method="POST", json=payload):
        response = index_routes.chat()
    return response, tool_calls


def test_auto_mode_runs_the_tool_without_asking(engine, monkeypatch):
    response, tool_calls = run_chat(monkeypatch, "auto")
    body = response.get_json()

    assert response.status_code == 200
    # Machine access is on in these settings, which is the case that used to
    # stop even for Fast+.
    assert "approval_id" not in body
    assert tool_calls == [
        {"name": "run_command", "arguments": {"command": "pwd"}, "approved": True}
    ]
    assert body["answer"] == FINAL_ANSWER


def test_manual_mode_stops_for_approval(engine, monkeypatch):
    response, tool_calls = run_chat(monkeypatch, "manual")
    body = response.get_json()

    assert response.status_code == 200
    assert body["approval_id"]
    assert body["tool_request"]["name"] == "run_command"
    assert tool_calls == []


def test_the_old_mode_values_map_onto_the_two_modes(engine, monkeypatch):
    from routes.index import normalize_command_mode

    assert normalize_command_mode("auto") == "auto"
    assert normalize_command_mode("fast") == "auto"
    assert normalize_command_mode("manual") == "manual"
    assert normalize_command_mode("ask") == "manual"
    assert normalize_command_mode("banana") == "manual"
    assert normalize_command_mode(None) == "manual"


def test_a_saved_fast_mode_never_asks(engine, monkeypatch):
    import app as app_module
    import core.tools
    from routes import index as index_routes

    settings = chat_settings()
    settings["command_mode"] = "fast"
    answers = [TOOL_ANSWER, FINAL_ANSWER]
    tool_calls = []

    monkeypatch.setattr(index_routes, "rate_limit_response", lambda *_a, **_k: None)
    monkeypatch.setattr(index_routes, "load_settings", lambda: settings)
    monkeypatch.setattr(index_routes, "build_system_prompt", lambda *_a, **_k: "system")
    monkeypatch.setattr(index_routes, "call_provider", lambda *_a, **_k: (answers.pop(0), {}))
    monkeypatch.setattr(
        index_routes,
        "run_local_tool",
        lambda name, arguments, approved=False: tool_calls.append(approved) or {"tool": name},
    )
    monkeypatch.setattr(index_routes, "log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(core.tools, "load_settings", lambda: settings)

    with app_module.app.test_request_context(
        "/api/chat",
        method="POST",
        json={"messages": [{"role": "user", "content": "pwd"}], "lang": "en"},
    ):
        response = index_routes.chat()

    assert response.status_code == 200
    assert response.get_json()["answer"] == FINAL_ANSWER
    assert tool_calls == [True]


def test_the_page_offers_exactly_the_two_modes():
    """The select has Manual and Auto, and Fast+ is gone."""
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[1] / "templates" / "index" / "index.html"
    ).read_text(encoding="utf-8")

    start = html.index('id="chat-command-mode"')
    select = html[start : html.index("</select>", start)]
    values = [line.split('"')[1] for line in select.split("value=")[1:]]

    assert values == ["manual", "auto"]
    assert "Fast+" not in select


def make_test_client(monkeypatch, settings):
    """A bare app with the index blueprint, so no session hook is involved."""
    import core.tools
    import routes.index as index_routes
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(index_routes.index_bp)
    monkeypatch.setattr(index_routes, "load_settings", lambda: settings)
    monkeypatch.setattr(index_routes, "rate_limit_response", lambda *_a, **_k: None)
    monkeypatch.setattr(index_routes, "log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(core.tools, "load_settings", lambda: settings)
    return app.test_client()


def tool_policy(client, query=""):
    body = client.get(f"/api/tools{query}").get_json()
    approvals = {item["name"]: item["approval_required"] for item in body["tools"]}
    return body, approvals


def test_tools_endpoint_reports_auto_mode(engine, monkeypatch):
    client = make_test_client(monkeypatch, chat_settings())

    body, approvals = tool_policy(client, "?mode=auto")

    assert body["command_mode"] == "auto"
    assert body["modes"] == ["manual", "auto"]
    assert body["machine_access"] is True
    # Machine access is on, which used to force an approval for every tool.
    assert approvals["run_command"] is False
    assert not any(approvals.values())


def test_tools_endpoint_reports_manual_mode_with_machine_access(engine, monkeypatch):
    client = make_test_client(monkeypatch, chat_settings())

    body, approvals = tool_policy(client)

    assert body["command_mode"] == "manual"
    assert approvals["read_file"] is True
    assert approvals["list_files"] is True
    assert approvals["run_command"] is True
    assert approvals["execute_command"] is True


def test_tools_endpoint_follows_the_mode_without_machine_access(engine, monkeypatch):
    settings = chat_settings()
    settings["machine_access"] = False
    client = make_test_client(monkeypatch, settings)

    _body, manual = tool_policy(client, "?mode=manual")
    _body, auto = tool_policy(client, "?command_mode=auto")

    # Project scope: only the tools that change things ask, and auto asks none.
    assert manual["list_files"] is False
    assert manual["read_file"] is False
    assert manual["run_command"] is True
    assert manual["write_file"] is True
    assert not any(auto.values())


def test_tools_execute_auto_mode_needs_no_token(engine, monkeypatch):
    import routes.index as index_routes

    client = make_test_client(monkeypatch, chat_settings())
    calls = []

    def fake_tool(name, arguments, approved=False):
        calls.append((name, approved))
        return {"tool": name, "stdout": "/home/user"}

    monkeypatch.setattr(index_routes, "run_local_tool", fake_tool)

    response = client.post(
        "/api/tools/execute",
        json={
            "name": "run_command",
            "arguments": {"command": "pwd"},
            "command_mode": "auto",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert calls == [("run_command", True)]


def test_tools_execute_manual_mode_still_needs_the_token(engine, monkeypatch):
    import routes.index as index_routes

    client = make_test_client(monkeypatch, chat_settings())
    calls = []

    def fake_tool(name, arguments, approved=False):
        calls.append((name, approved))
        return {"tool": name}

    monkeypatch.setattr(index_routes, "run_local_tool", fake_tool)

    response = client.post(
        "/api/tools/execute",
        json={
            "name": "run_command",
            "arguments": {"command": "pwd"},
            "command_mode": "manual",
        },
    )

    assert response.status_code == 403
    assert calls == []
