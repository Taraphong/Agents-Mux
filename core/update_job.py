"""The self-update job behind the settings page.

update.sh does the work; this module starts it once, records its exit status
and exposes the tail of its log so the page can show progress.
"""

import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT


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
def update_log_succeeded() -> bool | None:
    """Read the updater's own success/failure verdict from its log tail."""
    tail, _ = update_log_tail()
    if "✅" in tail:
        return True
    if "❌" in tail:
        return False
    return None
def update_job_snapshot() -> dict[str, Any]:
    """Report the current update job, falling back to the persisted record."""
    with UPDATE_JOB_LOCK:
        process = UPDATE_JOB.get("process")
        if process is not None:
            return {
                "running": process.poll() is None,
                "job": {
                    "mode": UPDATE_JOB.get("mode", ""),
                    "started_at": UPDATE_JOB.get("started_at", ""),
                    "finished_at": UPDATE_JOB.get("finished_at", ""),
                    "ok": UPDATE_JOB.get("ok"),
                    "exit_code": UPDATE_JOB.get("exit_code"),
                },
            }
    persisted = load_update_status()
    if not persisted:
        return {
            "running": False,
            "job": {"mode": "", "started_at": "", "finished_at": "", "ok": None, "exit_code": None},
        }
    # The updater runs in its own session, so it outlives the restart we just did.
    running = process_is_alive(persisted.get("pid"))
    return {
        "running": running,
        "job": {
            "mode": persisted.get("mode", ""),
            "started_at": persisted.get("started_at", ""),
            "finished_at": "" if running else update_log_finished_at(),
            "ok": None if running else update_log_succeeded(),
            "exit_code": None,
        },
    }
def watch_update_job(process: "subprocess.Popen[bytes]") -> None:
    """Record the updater's exit status after the detached process finishes."""
    code = process.wait()
    with UPDATE_JOB_LOCK:
        UPDATE_JOB["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UPDATE_JOB["exit_code"] = code
        UPDATE_JOB["ok"] = code == 0
