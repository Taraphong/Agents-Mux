"""Smoke tests for the Flask application object.

These guard the app.py refactor: whatever module a helper moves to, ``app`` must
still expose the same Flask application, the same blueprints and the same core
pages.
"""

import pytest


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    import app

    return app


def test_flask_app_exists(app_module):
    from flask import Flask

    assert isinstance(app_module.app, Flask)


def test_page_blueprints_are_registered(app_module):
    assert {"index", "pair"} <= set(app_module.app.blueprints)


def test_core_pages_are_routed(app_module):
    rules = {rule.rule for rule in app_module.app.url_map.iter_rules()}
    assert "/" in rules
    assert "/pair" in rules


def test_api_route_is_routed(app_module):
    rules = {rule.rule for rule in app_module.app.url_map.iter_rules()}
    assert any(rule.startswith("/api/") for rule in rules)
