"""The self-update job behind the settings page.

update.sh does the work; this module starts it once, records its exit status,
exposes the tail of its log so the page can show progress, and checks for a new
version by itself once nobody has used the app for a while.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from core.log import log_event


# Self-update: the web page can run the project's own update.sh. Only the two
# fixed modes below are accepted, so no user input reaches the command line.
UPDATE_SCRIPT = PROJECT_ROOT / "update.sh"
UPDATE_LOG_FILE = Path(os.getenv("AI_WEB_UPDATE_LOG_FILE", "logs/update.log"))
UPDATE_LOG_TAIL_LINES = 160
UPDATE_MODES = {"check", "apply"}
UPDATE_JOB_LOCK = threading.Lock()
UPDATE_JOB: dict[str, Any] = {}
# A real update restarts this process, so the job is also persisted: the new
# server reads it back to report what happened before the restart.
UPDATE_STATUS_FILE = Path(os.getenv("AI_WEB_UPDATE_STATUS_FILE", "logs/update-status.json"))

# update.sh ends every run with this machine-readable line, so the page can show
# "N files can be updated" instead of guessing from prose.
UPDATE_COUNT_MARKER = "UPDATE_CHANGED="

# An automatic check downloads the remote tarball, so it runs at most this often
# and only after the app has sat unused for the configured number of minutes.
AUTO_CHECK_COOLDOWN_SECONDS = 6 * 60 * 60
UPDATE_WATCH_INTERVAL_SECONDS = 60
UPDATE_WATCH_START_DELAY_SECONDS = 45
_WATCHER_STARTED = False
_WATCHER_LOCK = threading.Lock()
_LAST_AUTO_CHECK = 0.0


class UpdateJobError(RuntimeError):
    """Why an update job could not start; the route maps it to a message."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def update_build_info() -> dict[str, Any]:
    """Describe the app files on disk; the updater keeps no version number."""
    try:
        stat = (PROJECT_ROOT / "app.py").stat()
    except OSError:
        return {"app_updated_at": "", "app_size": 0}
    return {
        "app_updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "app_size": stat.st_size,
    }


def update_script_ready() -> bool:
    """Return whether update.sh exists and can be executed."""
    return UPDATE_SCRIPT.is_file() and os.access(UPDATE_SCRIPT, os.X_OK)


def update_log_tail() -> tuple[str, bool]:
    """Return the end of the update log and whether older lines were dropped."""
    try:
        text = UPDATE_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return "", False
    lines = text.splitlines()
    return "\n".join(lines[-UPDATE_LOG_TAIL_LINES:]), len(lines) > UPDATE_LOG_TAIL_LINES


def save_update_status(payload: dict[str, Any]) -> None:
    """Persist the running update so the next server process can report it."""
    try:
        UPDATE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = UPDATE_STATUS_FILE.with_name(f".{UPDATE_STATUS_FILE.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, UPDATE_STATUS_FILE)
    except OSError:
        return


def load_update_status() -> dict[str, Any]:
    """Read the persisted update record, tolerating a missing or broken file."""
    try:
        data = json.loads(UPDATE_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def process_is_alive(pid: Any) -> bool:
    """Return whether the PID recorded for an update is still running."""
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def update_log_finished_at() -> str:
    """Use the log's timestamp as the finish time after a server restart."""
    try:
        return datetime.fromtimestamp(UPDATE_LOG_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def update_log_succeeded(tail: str) -> bool | None:
    """Read the updater's own success/failure verdict from its log tail.

    A check that finds new files ends with the dry-run line instead of ✅, so
    that line counts as success too: otherwise the page could never report the
    update it just found.
    """
    if "❌" in tail:
        return False
    if "✅" in tail or "🔍 Dry run finished" in tail:
        return True
    return None


def update_check_result(tail: str) -> int | None:
    """Read the changed-file count update.sh printed during its last run."""
    for line in tail.splitlines():
        text = line.strip()
        if text.startswith(UPDATE_COUNT_MARKER):
            try:
                return int(text.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def update_check_state(snapshot: dict[str, Any], tail: str) -> dict[str, Any]:
    """Describe the last check so the page can say whether an update exists.

    Only a finished, successful *check* answers that question: an apply run
    reports what it installed, which would look like a pending update right
    after the update finished.
    """
    job = snapshot.get("job") or {}
    changed = update_check_result(tail)
    checked = job.get("mode") == "check" and job.get("ok") is True and not snapshot.get("running")
    return {
        "finished_at": job.get("finished_at") or "",
        "changed": changed,
        "available": bool(changed) if checked and changed is not None else None,
    }


def _job_fields(source: dict[str, Any]) -> dict[str, Any]:
    """Pick the job fields the page reads out of a job or status record."""
    return {
        "mode": source.get("mode", ""),
        "started_at": source.get("started_at", ""),
        "finished_at": source.get("finished_at", ""),
        "ok": source.get("ok"),
        "exit_code": source.get("exit_code"),
        "trigger": source.get("trigger", ""),
    }


def update_job_snapshot() -> dict[str, Any]:
    """Report the current update job, falling back to the persisted record."""
    with UPDATE_JOB_LOCK:
        process = UPDATE_JOB.get("process")
        if process is not None:
            return {"running": process.poll() is None, "job": _job_fields(UPDATE_JOB)}
    persisted = load_update_status()
    if not persisted:
        return {"running": False, "job": _job_fields({})}
    # The updater runs in its own session, so it outlives the restart we just did.
    running = process_is_alive(persisted.get("pid"))
    job = _job_fields(persisted)
    if not running:
        tail, _ = update_log_tail()
        job["finished_at"] = update_log_finished_at()
        job["ok"] = update_log_succeeded(tail)
    return {"running": running, "job": job}


def update_auto_settings() -> dict[str, Any]:
    """Read the idle auto-check settings (imported here to keep this module light)."""
    from core.settings import load_settings, normalize_update_settings

    return normalize_update_settings(load_settings().get("update"))


def update_idle_seconds() -> float:
    """Seconds since the user last used the app."""
    import memory_engine

    return float(memory_engine.idle_seconds())


def update_auto_state() -> dict[str, Any]:
    """Report the automatic check so the page can explain when it runs."""
    config = update_auto_settings()
    persisted = load_update_status()
    return {
        "enabled": config["auto_check"],
        "idle_minutes": config["idle_minutes"],
        "idle_seconds": int(update_idle_seconds()),
        "last_auto_check_at": str(persisted.get("auto_checked_at") or ""),
    }


def watch_update_job(process: "subprocess.Popen[bytes]") -> None:
    """Record the updater's exit status after the detached process finishes."""
    code = process.wait()
    with UPDATE_JOB_LOCK:
        UPDATE_JOB["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UPDATE_JOB["exit_code"] = code
        UPDATE_JOB["ok"] = code == 0


def start_update_job(mode: str, trigger: str = "web") -> "subprocess.Popen[bytes]":
    """Start update.sh once, detached from Flask, and watch it.

    The web route and the idle watcher share this, so a running job is never
    replaced by a second updater.
    """
    if mode not in UPDATE_MODES:
        raise UpdateJobError("invalid_mode")
    if not update_script_ready():
        raise UpdateJobError("missing")
    if update_job_snapshot()["running"]:
        raise UpdateJobError("busy")
    args = [str(UPDATE_SCRIPT)]
    if mode == "check":
        # A dry run only compares files, so it must not write or restart.
        args += ["--dry-run", "--no-restart"]
    with UPDATE_JOB_LOCK:
        process = UPDATE_JOB.get("process")
        if process and process.poll() is None:
            raise UpdateJobError("busy")
        try:
            UPDATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(UPDATE_LOG_FILE, "wb") as handle:
                new_process = subprocess.Popen(
                    args,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    # A real update restarts the server; a separate session keeps
                    # this updater alive while the web process is replaced.
                    start_new_session=True,
                    env={**os.environ, "AI_WEB_UPDATE_FROM_WEB": "1"},
                )
        except OSError as exc:
            raise UpdateJobError("start_failed") from exc
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UPDATE_JOB.clear()
        UPDATE_JOB.update({
            "process": new_process,
            "pid": new_process.pid,
            "mode": mode,
            "trigger": trigger,
            "started_at": started_at,
            "finished_at": "",
            "ok": None,
            "exit_code": None,
        })
        # auto_checked_at is the only record of the last idle check; it survives
        # the restart an apply performs, unlike the in-memory timestamp below.
        status = load_update_status()
        status.update({"mode": mode, "started_at": started_at, "pid": new_process.pid, "trigger": trigger})
        if trigger == "auto":
            status["auto_checked_at"] = started_at
        save_update_status(status)
    threading.Thread(target=watch_update_job, args=(new_process,), daemon=True).start()
    return new_process


def maybe_run_auto_check() -> bool:
    """Start a background check when the app has been idle long enough.

    Only the watcher thread calls this, so the cooldown needs no lock.
    """
    global _LAST_AUTO_CHECK
    config = update_auto_settings()
    if not config["auto_check"]:
        return False
    if update_idle_seconds() < config["idle_minutes"] * 60:
        return False
    if update_job_snapshot()["running"]:
        return False
    if time.time() - _LAST_AUTO_CHECK < AUTO_CHECK_COOLDOWN_SECONDS:
        return False
    try:
        start_update_job("check", trigger="auto")
    except UpdateJobError:
        return False
    _LAST_AUTO_CHECK = time.time()
    log_event("system.update_auto_check", "Started the idle-time update check", idle_minutes=config["idle_minutes"])
    return True


def update_watch_loop() -> None:
    """Check the idle timer once a minute; a tick must never kill the loop."""
    time.sleep(UPDATE_WATCH_START_DELAY_SECONDS)
    while True:
        try:
            maybe_run_auto_check()
        except Exception:  # noqa: BLE001 - a failed tick must not stop the watcher
            pass
        time.sleep(UPDATE_WATCH_INTERVAL_SECONDS)


def start_update_watcher() -> None:
    """Start the idle auto-check loop once per process."""
    global _WATCHER_STARTED
    with _WATCHER_LOCK:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    threading.Thread(target=update_watch_loop, daemon=True, name="update-watcher").start()
