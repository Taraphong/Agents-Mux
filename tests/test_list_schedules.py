"""The model can read scheduled jobs, and tool failures explain themselves.

``update_schedule`` needs a real job id, but nothing let the model look one up,
so it guessed and the page only showed a generic "the tool could not run".
These tests cover the listing tool and the redacted reason on the error path.
"""

import json


def write_jobs(tmp_path, jobs):
    path = tmp_path / "scheduled-jobs.json"
    path.write_text(json.dumps(jobs), encoding="utf-8")
    return path


def make_client():
    from flask import Flask

    from routes.index import index_bp

    app = Flask(__name__)
    app.register_blueprint(index_bp)
    return app.test_client()


def test_list_schedules_returns_the_job_id_and_fields(tmp_path, monkeypatch):
    import core.log
    import core.schedule_store

    from core.tools import run_local_tool

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")
    monkeypatch.setattr(
        core.schedule_store,
        "SCHEDULE_FILE",
        write_jobs(
            tmp_path,
            [
                {
                    "id": "24530de5-adb5-41db-9117-74b185f19c0e",
                    "name": "Weather_YangTalat",
                    "schedule": "0 6 * * *",
                    "prompt": "รายงานสภาพอากาศ",
                    "model": "gemini-3.5-flash-lite",
                    "discord_channel_id": "1568452947367694356",
                    "enabled": True,
                    "last_status": "success",
                    "last_run_at": "2026-11-25T06:00:00+07:00",
                    "last_error": "/home/user/secret: boom-marker",
                }
            ],
        ),
    )

    result = run_local_tool("list_schedules", {})

    assert result["tool"] == "list_schedules"
    assert result["count"] == 1
    job = result["jobs"][0]
    assert job["id"] == "24530de5-adb5-41db-9117-74b185f19c0e"
    assert job["name"] == "Weather_YangTalat"
    assert job["schedule"] == "0 6 * * *"
    assert job["prompt"] == "รายงานสภาพอากาศ"
    assert job["discord_channel_id"] == "1568452947367694356"
    assert job["enabled"] is True
    # The stored failure text is not part of a listing.
    assert "last_error" not in job
    assert "boom-marker" not in json.dumps(result, ensure_ascii=False)


def test_tools_execute_reports_the_real_failure(tmp_path, monkeypatch):
    import core.log
    import core.schedule_store
    import core.tools

    monkeypatch.setattr(core.log, "LOG_FILE", tmp_path / "app.log")
    monkeypatch.setattr(core.schedule_store, "SCHEDULE_FILE", write_jobs(tmp_path, []))
    # Pin the approval policy so a checkout setting cannot change the path.
    monkeypatch.setattr(core.tools, "load_settings", lambda: {"machine_access": False})

    client = make_client()
    arguments = {"job_id": "no-such-job", "enabled": True}
    approval_id, _expires_at = core.tools.request_tool_approval("update_schedule", arguments)

    response = client.post(
        "/api/tools/execute",
        json={"name": "update_schedule", "arguments": arguments, "approval_id": approval_id},
    )
    body = response.get_json()

    assert response.status_code == 400
    assert body["ok"] is False
    assert body["approval_consumed"] is True
    assert "Scheduled job not found" in body["detail"]


def test_tools_endpoint_lists_list_schedules(monkeypatch):
    import core.tools

    monkeypatch.setattr(core.tools, "load_settings", lambda: {"machine_access": False})

    body = make_client().get("/api/tools").get_json()

    assert "list_schedules" in [tool["name"] for tool in body["tools"]]
