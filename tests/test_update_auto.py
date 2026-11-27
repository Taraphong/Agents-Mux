"""The idle auto-update check and the changed-file summary.

The idle check must wait for real inactivity, never replace a running job, and
read its verdict from the markers update.sh prints.
"""

import core.update_job as update_job
from core.settings import normalize_update_settings


def _write_log(tmp_path, monkeypatch, lines):
    log = tmp_path / "update.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(update_job, "UPDATE_LOG_FILE", log)
    return log


def test_normalize_update_settings_clamps_values():
    assert normalize_update_settings(None) == {"auto_check": True, "idle_minutes": 30}
    assert normalize_update_settings({"auto_check": False, "idle_minutes": 1}) == {
        "auto_check": False,
        "idle_minutes": 5,
    }
    assert normalize_update_settings({"auto_check": 0, "idle_minutes": 99999})["idle_minutes"] == 1440
    assert normalize_update_settings({"idle_minutes": "bad"})["idle_minutes"] == 30


def test_update_check_state_reports_a_new_version(tmp_path, monkeypatch):
    _write_log(tmp_path, monkeypatch, [
        "📦 Source: owner/repo@main",
        "   → core/ (3 file(s) changed)",
        "UPDATE_CHANGED=4",
        "UPDATE_FILES=core(3) app.py",
        "🆕 4 file(s) differ from owner/repo@main",
        "🔍 Dry run finished — no files were written",
    ])
    snapshot = {
        "running": False,
        "job": {"mode": "check", "finished_at": "2026-01-01 10:00:00", "ok": True},
    }
    state = update_job.update_check_state(snapshot)
    assert state["changed"] == 4
    assert state["files"] == "core(3) app.py"
    assert state["available"] is True


def test_update_check_state_reports_up_to_date(tmp_path, monkeypatch):
    _write_log(tmp_path, monkeypatch, [
        "   = core/ (unchanged)",
        "UPDATE_CHANGED=0",
        "UPDATE_FILES=",
        "✅ Already up to date (owner/repo@main)",
    ])
    snapshot = {
        "running": False,
        "job": {"mode": "check", "finished_at": "2026-01-01 10:00:00", "ok": True},
    }
    assert update_job.update_check_state(snapshot)["available"] is False


def test_update_check_state_ignores_an_apply_run(tmp_path, monkeypatch):
    # An apply logs the files it installed; that must not look like a pending
    # update right after the update finished.
    _write_log(tmp_path, monkeypatch, ["UPDATE_CHANGED=2", "UPDATE_FILES=app.py", "✅ Update finished"])
    snapshot = {
        "running": False,
        "job": {"mode": "apply", "finished_at": "2026-01-01 10:00:00", "ok": True},
    }
    assert update_job.update_check_state(snapshot)["available"] is None


def test_update_log_succeeded_accepts_a_check_that_found_changes(tmp_path, monkeypatch):
    # A check with new files ends with the dry-run line and never prints ✅.
    _write_log(tmp_path, monkeypatch, [
        "UPDATE_CHANGED=2",
        "🆕 2 file(s) differ from owner/repo@main",
        "🔍 Dry run finished — no files were written",
    ])
    assert update_job.update_log_succeeded() is True


def test_update_log_succeeded_reports_a_failure(tmp_path, monkeypatch):
    _write_log(tmp_path, monkeypatch, ["❌ Download failed: https://example.invalid"])
    assert update_job.update_log_succeeded() is False


def test_maybe_run_auto_check_waits_for_idle(monkeypatch):
    calls = []
    monkeypatch.setattr(update_job, "update_auto_settings", lambda: {"auto_check": True, "idle_minutes": 30})
    monkeypatch.setattr(update_job, "update_idle_seconds", lambda: 60)
    monkeypatch.setattr(update_job, "update_job_snapshot", lambda: {"running": False, "job": {}})
    monkeypatch.setattr(update_job, "start_update_job", lambda *args, **kwargs: calls.append(args))
    assert update_job.maybe_run_auto_check() is False
    assert calls == []


def test_maybe_run_auto_check_respects_the_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(update_job, "update_auto_settings", lambda: {"auto_check": False, "idle_minutes": 30})
    monkeypatch.setattr(update_job, "update_idle_seconds", lambda: 999999)
    monkeypatch.setattr(update_job, "start_update_job", lambda *args, **kwargs: calls.append(args))
    assert update_job.maybe_run_auto_check() is False
    assert calls == []


def test_maybe_run_auto_check_starts_once_then_cools_down(monkeypatch):
    calls = []
    monkeypatch.setattr(update_job, "update_auto_settings", lambda: {"auto_check": True, "idle_minutes": 30})
    monkeypatch.setattr(update_job, "update_idle_seconds", lambda: 31 * 60)
    monkeypatch.setattr(update_job, "update_job_snapshot", lambda: {"running": False, "job": {}})
    monkeypatch.setattr(
        update_job,
        "start_update_job",
        lambda mode, trigger="web": calls.append((mode, trigger)),
    )
    monkeypatch.setattr(update_job, "_LAST_AUTO_CHECK", 0.0)
    assert update_job.maybe_run_auto_check() is True
    assert calls == [("check", "auto")]
    # A second tick inside the cooldown must not download the archive again.
    assert update_job.maybe_run_auto_check() is False
    assert calls == [("check", "auto")]


def test_maybe_run_auto_check_skips_a_running_job(monkeypatch):
    calls = []
    monkeypatch.setattr(update_job, "update_auto_settings", lambda: {"auto_check": True, "idle_minutes": 30})
    monkeypatch.setattr(update_job, "update_idle_seconds", lambda: 999999)
    monkeypatch.setattr(update_job, "update_job_snapshot", lambda: {"running": True, "job": {}})
    monkeypatch.setattr(update_job, "start_update_job", lambda *args, **kwargs: calls.append(args))
    assert update_job.maybe_run_auto_check() is False
    assert calls == []
