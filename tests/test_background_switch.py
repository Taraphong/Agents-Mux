"""AI_WEB_ENABLE_SCHEDULER must control the loops on both entry points.

Running `python app.py` owns the process, so the cron, memory and idle-update
loops start by default and an explicit off value stops them. An external WSGI
server only imports the module, so it must opt in with the switch.
"""

import pytest

import app
import memory_engine


@pytest.fixture()
def started(monkeypatch):
    """Record which background loops would be started."""
    calls: list[str] = []
    monkeypatch.setattr(app, "start_scheduler", lambda: calls.append("cron"))
    monkeypatch.setattr(memory_engine, "start_scheduler", lambda: calls.append("memory"))
    monkeypatch.setattr(app, "start_update_watcher", lambda: calls.append("update"))
    return calls


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_python_app_honours_an_explicit_off_switch(started, monkeypatch, value):
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", value)
    app.start_background_tasks(default=True)
    assert started == []


@pytest.mark.parametrize("value", [None, ""])
def test_python_app_starts_the_loops_by_default(started, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("AI_WEB_ENABLE_SCHEDULER", raising=False)
    else:
        monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", value)
    app.start_background_tasks(default=True)
    assert started == ["cron", "memory", "update"]


def test_wsgi_import_keeps_the_loops_off_by_default(started, monkeypatch):
    monkeypatch.delenv("AI_WEB_ENABLE_SCHEDULER", raising=False)
    app.start_background_tasks()
    assert started == []


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_wsgi_import_starts_the_loops_when_switched_on(started, monkeypatch, value):
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", value)
    app.start_background_tasks()
    assert started == ["cron", "memory", "update"]
