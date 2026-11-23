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


def _is_exception_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in EXCEPTION_NAMES


def _is_exception_text(node: ast.AST) -> bool:
    """Report exception text built for a response, however it is formatted."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"str", "repr"}:
            return bool(node.args) and _is_exception_name(node.args[0])
        if isinstance(func, ast.Name) and func.id == "format_exc":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "format_exc":
            return True
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "format"
            and isinstance(func.value, ast.Constant)
            and isinstance(func.value.value, str)
        ):
            return any(_is_exception_name(argument) for argument in node.args)
    if isinstance(node, ast.JoinedStr):
        return any(
            isinstance(value, ast.FormattedValue)
            and _is_exception_name(value.value)
            for value in node.values
        )
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mod)
        and isinstance(node.left, ast.Constant)
        and isinstance(node.left.value, str)
        and "%" in node.left.value
    ):
        return _is_exception_name(node.right)
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


@pytest.mark.parametrize(
    "source",
    [
        'jsonify({"error": str(exc)})',
        'jsonify({"error": repr(exc)})',
        'jsonify({"error": f"{exc}"})',
        'jsonify({"error": "%s" % exc})',
        'jsonify({"error": "{}".format(exc)})',
        'jsonify({"error": traceback.format_exc()})',
    ],
)
def test_the_guard_detects_exception_text(source):
    assert _offending_lines(ast.parse(source)) == [1]


def test_the_guard_allows_a_response_without_exception_text():
    assert _offending_lines(ast.parse('jsonify({"ok": True, "error": "missing"})')) == []


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


def test_error_response_cannot_be_talked_into_leaking_the_error():
    from flask import Flask

    from core.messages import status_message
    from routes.shared import error_response

    app = Flask(__name__)
    with app.test_request_context("/"):
        response, status = error_response(
            "en",
            "server_busy",
            message="test",
            body={"ok": False, "error": "leaked detail"},
        )

    assert status == 500
    assert response.get_json() == {
        "ok": False,
        "error": status_message("en", "server_busy"),
    }


def test_memory_reindex_failure_is_generic(client, monkeypatch):
    import memory_engine

    def explode(*_args, **_kwargs):
        raise OSError(f"cannot rebuild index: {MARKER}")

    monkeypatch.setattr(memory_engine, "reindex", explode)

    response = client.post("/api/memory/reindex")
    body = response.get_json()

    assert response.status_code == 500
    assert body["error"] == "Could not rebuild the memory index; check the system log"
    assert MARKER not in response.get_data(as_text=True)
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
    assert body["error"] == "Could not write the .env file; check the system log"
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
    assert body["error"] == "Could not start the server control command; check the system log"
    assert MARKER not in response.get_data(as_text=True)
    assert any(
        MARKER in error for error in _logged_errors("system.server_action_failed")
    )
