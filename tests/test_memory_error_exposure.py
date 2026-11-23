"""Regression tests for CodeQL py/stack-trace-exposure (#93 and #94).

Both alerts started from the sqlite-vec probe: ``_vec_state()`` returned the raw
sqlite error text as ``vector_error``, which ``capabilities()`` then carried into
``/api/memory/status`` and ``/api/memory/run``. The exception text must stay in
the diagnostic log while the API only reports a generic reason.
"""

import pytest

MARKER = "internal-detail-marker-98765"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A Flask client with only the index blueprint, so pairing auth is out."""
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")

    import core.log

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")

    from flask import Flask

    from routes.index import index_bp

    app = Flask(__name__)
    app.register_blueprint(index_bp)
    return app.test_client()


def test_vector_probe_keeps_the_sqlite_error_out_of_capabilities(engine, tmp_path, monkeypatch):
    import core.log
    from core.log import APP_LOGS

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")
    broken = tmp_path / "broken-vec0.so"
    broken.write_bytes(b"this is not a shared library")
    monkeypatch.setattr(engine, "VEC_EXTENSION_FILE", broken)
    engine._VEC_STATE.update({"checked": False, "ready": False, "error": ""})

    caps = engine.capabilities()

    assert caps["vector"] == "python-blob"
    assert caps["vector_error"] == engine.VECTOR_LOAD_ERROR
    assert str(broken) not in str(caps)

    logged = [entry for entry in APP_LOGS if entry.get("event") == "memory.vector"]
    assert any("broken-vec0.so" in str(entry.get("details", {}).get("error", "")) for entry in logged)


def test_model_summary_failure_returns_a_category_and_logs_the_detail(engine, tmp_path, monkeypatch):
    import core.log
    from core.log import APP_LOGS

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"provider rejected the request: {MARKER}")

    monkeypatch.setattr(engine, "call_provider", explode)

    result, error = engine._ask_model(
        {"provider": "openai", "model": "m", "api_keys": {"openai": "k"}},
        engine.normalize_settings({}),
        [{"id": "1", "text": "candidate", "context": "", "seen": 1}],
        "en",
    )

    assert result == {}
    assert error in engine.LLM_ERROR_KINDS
    assert MARKER not in error

    logged = [entry for entry in APP_LOGS if entry.get("event") == "memory.llm"]
    assert any(MARKER in str(entry.get("details", {}).get("error", "")) for entry in logged)


@pytest.mark.parametrize(
    ("message", "kind"),
    [("request timed out", "timeout"), ("HTTP 429 rate limit", "rate_limit")],
)
def test_model_summary_failure_keeps_its_category(engine, monkeypatch, message, kind):
    def explode(*_args, **_kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(engine, "call_provider", explode)

    _result, error = engine._ask_model(
        {"provider": "openai", "model": "m", "api_keys": {"openai": "k"}},
        engine.normalize_settings({}),
        [{"id": "1", "text": "candidate", "context": "", "seen": 1}],
        "en",
    )

    assert error == kind


def test_memory_run_failure_returns_a_generic_message(client, monkeypatch):
    from core.log import APP_LOGS

    import memory_engine

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"provider rejected the request: {MARKER}")

    monkeypatch.setattr(memory_engine, "run", explode)

    response = client.post("/api/memory/run", json={})
    body = response.get_json()

    assert response.status_code == 500
    assert MARKER not in response.get_data(as_text=True)
    assert "memory run failed" in body["error"].lower()

    logged = [entry for entry in APP_LOGS if entry.get("event") == "memory.error"]
    assert any(MARKER in str(entry.get("details", {}).get("error", "")) for entry in logged)


def test_memory_run_busy_stays_a_conflict(client, monkeypatch):
    import memory_engine

    def busy(*_args, **_kwargs):
        raise RuntimeError("memory_busy")

    monkeypatch.setattr(memory_engine, "run", busy)

    response = client.post("/api/memory/run", json={})

    assert response.status_code == 409
