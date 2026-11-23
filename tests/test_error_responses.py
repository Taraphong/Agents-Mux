"""API errors stay generic; exception detail belongs to the log.

CodeQL alerts #93/#94 came from exception text reaching a JSON response. The
routes now share ``error_response()``, and this module keeps that shape: a
static check for exception text inside response calls plus behaviour tests for
the endpoints that used to interpolate ``str(exc)``.
"""

import ast
from pathlib import Path

import pytest

MARKER = "internal-detail-marker-4242"
ROUTES = Path(__file__).resolve().parents[1] / "routes"
EXCEPTION_NAMES = {"exc", "err", "error"}


def _is_exception_text(node: ast.AST) -> bool:
    """Report ``str(exc)`` or an f-string that formats an exception variable."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in EXCEPTION_NAMES
    ):
        return True
    if isinstance(node, ast.JoinedStr):
        return any(
            isinstance(value, ast.FormattedValue)
            and isinstance(value.value, ast.Name)
            and value.value.id in EXCEPTION_NAMES
            for value in node.values
        )
    return False


def _offending_lines(tree: ast.AST) -> list[int]:
    """Line numbers of response calls that interpolate exception text."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in {"jsonify", "status_message"}:
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(
            _is_exception_text(child)
            for argument in arguments
            for child in ast.walk(argument)
        ):
            lines.append(node.lineno)
    return lines


def test_the_guard_detects_exception_text():
    sample = ast.parse('jsonify({"error": str(exc)})\n')
    assert _offending_lines(sample) == [1]


def test_routes_never_put_exception_text_in_a_response():
    offenders = []
    for path in sorted(ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(f"{path.name}:{line}" for line in _offending_lines(tree))

    assert not offenders, (
        "Return a generic status_message via error_response() and log the "
        f"detail instead of exposing it: {offenders}"
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A Flask client for the index blueprint, without pairing auth."""
    import core.log

    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")

    from flask import Flask

    from routes.index import index_bp

    app = Flask(__name__)
    app.register_blueprint(index_bp)
    return app.test_client()


def _logged_errors(event: str) -> list[str]:
    from core.log import APP_LOGS

    return [
        str(entry.get("details", {}).get("error", ""))
        for entry in APP_LOGS
        if entry.get("event") == event
    ]


def test_memory_reindex_failure_is_generic(client, monkeypatch):
    import memory_engine

    def explode(*_args, **_kwargs):
        raise OSError(f"cannot rebuild index: {MARKER}")

    monkeypatch.setattr(memory_engine, "reindex", explode)

    response = client.post("/api/memory/reindex")
    body = response.get_json()

    assert response.status_code == 500
    assert MARKER not in response.get_data(as_text=True)
    assert "log" in body["error"].lower()
    assert any(MARKER in error for error in _logged_errors("memory.error"))


def test_tls_env_write_failure_is_generic(client, monkeypatch):
    from routes import index as index_routes

    def explode(_values):
        raise OSError(f"disk full: {MARKER}")

    monkeypatch.setattr(index_routes, "update_env_file", explode)

    response = client.put("/api/server/tls", json={"mode": "http"})
    body = response.get_json()

    assert response.status_code == 500
    assert body["ok"] is False
    assert MARKER not in response.get_data(as_text=True)
    assert any(MARKER in error for error in _logged_errors("system.tls_save_failed"))


def test_server_action_failure_is_generic(client, tmp_path, monkeypatch):
    from routes import index as index_routes

    def explode(*_args, **_kwargs):
        raise OSError(f"cannot exec: {MARKER}")

    monkeypatch.setattr(index_routes, "SERVER_CONTROL_LOG", tmp_path / "server.log")
    monkeypatch.setattr(index_routes.subprocess, "Popen", explode)

    response = client.post("/api/server/action", json={"action": "restart"})
    body = response.get_json()

    assert response.status_code == 500
    assert body["ok"] is False
    assert MARKER not in response.get_data(as_text=True)
    assert any(
        MARKER in error for error in _logged_errors("system.server_action_failed")
    )
