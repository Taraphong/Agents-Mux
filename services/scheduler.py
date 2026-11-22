"""The cron scheduler.

One process at a time holds the scheduler lock, checks due jobs every 15
seconds and runs each one in its own thread. Results go to the history store and,
when configured, to Discord. This module never imports app.
"""

import fcntl
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from core.config import SCHEDULE_CONTEXT_MESSAGES, SCHEDULE_LOCK_FILE
from core.history import find_schedule_conversation_id, load_history_record, save_history
from core.log import log_event
from core.providers import agent_profile_prompt, call_provider, clean_messages
from core.redaction import redact_secrets
from core.schedule_store import cron_matches, load_schedules, update_schedule
from core.settings import load_settings
from services.discord_bot import send_discord_schedule_result


SCHEDULE_RUNNING: set[str] = set()
SCHEDULE_RUNNING_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_START_LOCK = threading.Lock()
_SCHEDULER_LOCK_HANDLE: Any = None
def execute_schedule(job: dict[str, Any]) -> None:
    """Run one scheduled job, store its answer, and record the outcome."""
    try:
        settings = load_settings()
        if job.get("model"):
            settings["model"] = job["model"]
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
            ) if part
        )
        conversation_id = schedule_conversation_id(job)
        record = load_history_record(conversation_id)
        previous_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        context_messages = [
            message for message in previous_messages
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        ][-SCHEDULE_CONTEXT_MESSAGES:]
        prompt_message = {"role": "user", "content": job["prompt"], "schedule_id": job["id"]}
        messages = clean_messages(context_messages + [prompt_message], settings)
        started_at = time.perf_counter()
        answer, usage = call_provider(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        save_history({
            "id": conversation_id,
            "title": record.get("title") or f"⏰ {job['name']}",
            "created_at": record.get("created_at"),
            "base_message_count": len(previous_messages),
            "messages": [
                *previous_messages,
                prompt_message,
                {"role": "assistant", "content": answer, "duration_ms": duration_ms, "usage": usage, "schedule_id": job["id"]},
            ],
        })
        try:
            send_discord_schedule_result(job, answer)
        except Exception as exc:
            # The answer is already saved in history, so a Discord delivery
            # problem must not mark the AI run itself as failed.
            log_event("schedule.discord_error", f"Could not send scheduled job {job['name']} to Discord", job=job["id"], error=str(exc))
        update_schedule(job["id"], last_status="success", last_error="", last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        log_event("schedule.success", f"Scheduled job {job['name']} succeeded", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        log_event("schedule.error", f"Scheduled job {job.get('name', job.get('id', ''))} failed", error=str(exc))
        update_schedule(job["id"], last_status="failed", last_error=redact_secrets(str(exc))[:500], last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    finally:
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id:
            with SCHEDULE_RUNNING_LOCK:
                SCHEDULE_RUNNING.discard(job_id)
def schedule_loop() -> None:
    """Check due jobs every 15 seconds and dispatch them in threads."""
    last_minute = ""
    while True:
        now = datetime.now().astimezone()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key != last_minute:
            last_minute = minute_key
            try:
                for job in load_schedules():
                    if not job.get("enabled", True) or job.get("last_run_key") == minute_key:
                        continue
                    try:
                        if not cron_matches(job["schedule"], now):
                            continue
                        job_id = job["id"]
                        with SCHEDULE_RUNNING_LOCK:
                            if job_id in SCHEDULE_RUNNING:
                                log_event("schedule.skipped", "Skipped a job that is still running", job=job_id)
                                continue
                            SCHEDULE_RUNNING.add(job_id)
                        try:
                            update_schedule(job_id, last_run_key=minute_key)
                            threading.Thread(target=execute_schedule, args=(job,), daemon=True).start()
                        except Exception:
                            with SCHEDULE_RUNNING_LOCK:
                                SCHEDULE_RUNNING.discard(job_id)
                            raise
                    except (KeyError, TypeError, ValueError):
                        update_schedule(job.get("id", ""), last_status="failed", last_error="invalid cron")
            except OSError as exc:
                log_event("schedule.error", "Could not read or save the scheduled jobs", error=str(exc))
        time.sleep(15)
def start_scheduler() -> None:
    """Start the cron loop once per process, and only in one process at a time."""
    global _SCHEDULER_STARTED, _SCHEDULER_LOCK_HANDLE
    with _SCHEDULER_START_LOCK:
        if _SCHEDULER_STARTED:
            return
        try:
            handle = open(SCHEDULE_LOCK_FILE, "a+", encoding="utf-8")
        except OSError as exc:
            log_event("schedule.error", "Could not open the scheduler lock file", error=str(exc))
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return
        _SCHEDULER_LOCK_HANDLE = handle
        _SCHEDULER_STARTED = True
    threading.Thread(target=schedule_loop, name="scheduled-ai-jobs", daemon=True).start()
def schedule_conversation_id(job: dict[str, Any]) -> str:
    """Resolve one stable history conversation per scheduled job and persist it."""
    conversation_id = str(job.get("conversation_id") or "").strip()
    if re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return conversation_id
    conversation_id = find_schedule_conversation_id(str(job.get("id") or "")) or str(uuid.uuid4())
    job["conversation_id"] = conversation_id
    job_id = str(job.get("id") or "").strip()
    if job_id:
        update_schedule(job_id, conversation_id=conversation_id)
    return conversation_id
