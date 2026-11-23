"""Scheduled-job failure text stays local; the API only sees a category.

``last_error`` used to store the redacted exception message, and the whole job
list is returned by ``/api/schedules``. Old files may still contain a message,
so ``load_schedules()`` reduces the field to a bare identifier.
"""

import json

import pytest

RAW_DETAIL = "/home/user/secret-path: boom-marker-777"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import core.log
    import core.schedule_store

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")
    schedule_file = tmp_path / "scheduled-jobs.json"
    schedule_file.write_text(
        json.dumps(
            [
                {
                    "id": "job-1",
                    "name": "Nightly",
                    "schedule": "0 3 * * *",
                    "last_status": "failed",
                    "last_error": RAW_DETAIL,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core.schedule_store, "SCHEDULE_FILE", schedule_file)

    from flask import Flask

    from routes.index import index_bp

    app = Flask(__name__)
    app.register_blueprint(index_bp)
    return app.test_client()


def test_legacy_last_error_never_reaches_the_api(client):
    response = client.get("/api/schedules")
    body = response.get_json()

    assert response.status_code == 200
    assert body["items"][0]["last_error"] == "error"
    assert "boom-marker-777" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("RuntimeError", "RuntimeError"),
        ("invalid_cron", "invalid_cron"),
        ("", ""),
        ("boom: secret-path", "error"),
        ("multi\nline", "error"),
    ],
)
def test_safe_error_kind_keeps_only_an_identifier(value, expected):
    from core.schedule_store import safe_error_kind

    assert safe_error_kind(value) == expected
