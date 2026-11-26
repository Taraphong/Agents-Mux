"""The cron scheduler.

One process at a time holds the scheduler lock, checks due jobs every 15
seconds and runs each one in its own thread. Results go to the history store and,
when configured, to Discord. This module never imports app.
"""

import fcntl
import json
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from core.config import (
    SCHEDULE_CONTEXT_MESSAGES,
    SCHEDULE_LOCK_FILE,
    SCHEDULE_RETRY_DELAYS,
    SCHEDULE_TOOL_ROUNDS,
    TOOL_CALL_REPAIR_INSTRUCTION,
    TOOL_INSTRUCTIONS,
    is_approval_placeholder,
)
from core.history import find_schedule_conversation_id, load_history_record, save_history
from core.log import log_event
from core.prompts import agent_profile_prompt
from core.providers import call_provider, clean_messages
from core.schedule_store import cron_matches, load_schedules, update_schedule
from core.settings import load_settings
from core.skills import skills_prompt
from core.tools import has_tool_marker, parse_tool_requests, run_local_tool, strip_tool_markers
from services.discord_bot import send_discord_schedule_result


SCHEDULE_RUNNING: set[str] = set()
SCHEDULE_RUNNING_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_START_LOCK = threading.Lock()
_SCHEDULER_LOCK_HANDLE: Any = None

TOOL_RESULT_CONTINUATION = (
    "Tool results:\n{output}\n\n"
    "Finish the job in plain text using these results. Never show a tool_call or raw "
    "JSON unless it is the answer, and never ask the user for approval."
)

JOB_RUN_GUIDANCE = (
    "This is an automated scheduled run. Carry out the job instruction and report only its "
    "result in plain text. Never ask the user questions, and never create or edit scheduled jobs."
)


def schedule_time_note(now: datetime) -> str:
    """Tell the model the machine's real local time instead of letting it guess."""
    return (
        f"Current local time on this machine: {now.isoformat(timespec='seconds')}. "
        "Use it when the job mentions the time or date; never guess them."
    )


class ScheduleAnswerError(RuntimeError):
    """A scheduled run produced something that cannot be reported."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def schedule_context_messages(
    previous_messages: list[Any],
    job_id: str = "",
) -> list[dict[str, Any]]:
    """Return the job's own previous runs to send to the provider.

    Only turns this scheduler wrote for the same job are kept. Chat messages
    share the job's conversation, and replaying them made a job answer "I updated
    the scheduled job" instead of running its prompt. The approval placeholder
    is page text and tool results are transient, so both are dropped as well.
    """
    context: list[dict[str, Any]] = []
    for message in previous_messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") not in {"user", "assistant"} or message.get("tool_result"):
            continue
        if job_id and str(message.get("schedule_id") or "") != job_id:
            continue
        content = str(message.get("content") or "")
        if message.get("role") == "assistant" and is_approval_placeholder(content):
            continue
        context.append(message)
    return context[-SCHEDULE_CONTEXT_MESSAGES:]


def job_log_details(job: dict[str, Any] | None) -> dict[str, str]:
    """Name the job in a log record, so a failure can be traced from the log."""
    data = job or {}
    return {"job": str(data.get("id") or ""), "name": str(data.get("name") or "")}


def run_schedule_turn(
    messages: list[dict[str, Any]],
    settings: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call the model and run its tool calls without asking for an approval.

    A job is unattended and its prompt was written by the owner, so its tools
    run directly. The loop is bounded so a bad job cannot call tools forever.
    """
    job_details = job_log_details(job)
    answer, usage = call_provider(messages, settings)
    repaired = False
    for _ in range(SCHEDULE_TOOL_ROUNDS):
        try:
            tool_requests = parse_tool_requests(answer)
        except ValueError as exc:
            log_event(
                "schedule.tool_parse_failed",
                "Skipped an unreadable tool_call in a scheduled job",
                **job_details,
                error=str(exc),
            )
            tool_requests = []
        if not tool_requests:
            if not repaired and has_tool_marker(answer):
                repaired = True
                messages.extend([
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": TOOL_CALL_REPAIR_INSTRUCTION},
                ])
                answer, usage = call_provider(messages, settings)
                continue
            break
        results = []
        for tool_request in tool_requests:
            name = tool_request["name"]
            try:
                results.append(run_local_tool(name, tool_request["arguments"], approved=True))
            except (FileNotFoundError, PermissionError, ValueError, OSError, subprocess.SubprocessError) as exc:
                log_event(
                    "schedule.tool_error",
                    f"Scheduled job tool {name} failed",
                    **job_details,
                    tool=name,
                    error=str(exc),
                )
                results.append({"tool": name, "error": str(exc)[:300]})
        messages.extend([
            {"role": "assistant", "content": answer},
            {"role": "user", "content": TOOL_RESULT_CONTINUATION.format(output=json.dumps(results, ensure_ascii=False))},
        ])
        answer, usage = call_provider(messages, settings)
    return answer, usage


def retry_delay_seconds(attempt: int) -> int:
    """Seconds to wait before retry number ``attempt`` (0 is the first), or 0 when spent."""
    if 0 <= attempt < len(SCHEDULE_RETRY_DELAYS):
        return SCHEDULE_RETRY_DELAYS[attempt]
    return 0


def retry_attempt_of(job: dict[str, Any]) -> int:
    """Read how many retries this run already used, ignoring a broken value."""
    try:
        return max(0, int(job.get("retry_attempt") or 0))
    except (TypeError, ValueError):
        return 0


def retry_moment(value: Any) -> datetime | None:
    """Parse a stored retry time; an unreadable value means no retry is pending."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A value written without an offset is local time, which is what this
    # machine's loop compares against.
    return moment if moment.tzinfo else moment.astimezone()


def retry_changes(job: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Describe the next retry for a failed run, or its end when delays are spent."""
    attempt = retry_attempt_of(job)
    delay = retry_delay_seconds(attempt)
    if not delay:
        return {"retry_at": "", "retry_attempt": 0}
    return {
        "retry_at": (now + timedelta(seconds=delay)).isoformat(timespec="seconds"),
        "retry_attempt": attempt + 1,
    }


def schedule_answer_problem(answer: str) -> str:
    """Name why a final answer cannot be reported, or return an empty string."""
    text = strip_tool_markers(str(answer or "")).strip()
    if not text:
        return "unreadable_tool_call" if has_tool_marker(answer) else "empty_answer"
    if is_approval_placeholder(text):
        return "approval_placeholder"
    return ""


def execute_schedule(job: dict[str, Any]) -> None:
    """Run one scheduled job, store its answer, and record the outcome.

    The job may use tools, and only a real final answer counts as success: a
    placeholder, an unreadable tool call, or an empty reply is recorded as a
    failure and never sent to Discord.
    """
    try:
        settings = load_settings()
        if job.get("model"):
            settings["model"] = job["model"]
        # A job must know the tool protocol, exactly like the chat page: without
        # the tool instructions a model answers "I cannot access your API key"
        # instead of calling run_command itself. The machine's time is given
        # here because a prompt that asks for the time made the model invent one.
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
                skills_prompt(settings),
                JOB_RUN_GUIDANCE,
                schedule_time_note(datetime.now().astimezone()),
                TOOL_INSTRUCTIONS,
            ) if part
        )
        conversation_id = schedule_conversation_id(job)
        record = load_history_record(conversation_id)
        previous_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        context_messages = schedule_context_messages(previous_messages, str(job.get("id") or ""))
        prompt_message = {"role": "user", "content": job["prompt"], "schedule_id": job["id"]}
        messages = clean_messages(context_messages + [prompt_message], settings)
        started_at = time.perf_counter()
        raw_answer, usage = run_schedule_turn(messages, settings, job)
        answer = strip_tool_markers(str(raw_answer or "")).strip()
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        problem = schedule_answer_problem(raw_answer)
        if problem:
            raise ScheduleAnswerError(problem)
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
        update_schedule(
            job["id"],
            last_status="success",
            last_error="",
            last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            retry_at="",
            retry_attempt=0,
        )
        log_event("schedule.success", f"Scheduled job {job['name']} succeeded", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        # The job list is returned by /api/schedules, so only a short reason is
        # stored; the message stays in the log above.
        reason = str(getattr(exc, "kind", "") or exc.__class__.__name__)[:60]
        # The job id and name go in the details so a failure can be traced from
        # the log alone: the message is free text and the time is not unique.
        log_event(
            "schedule.error",
            f"Scheduled job {job.get('name', job.get('id', ''))} failed",
            **job_log_details(job),
            error=str(exc),
        )
        moment = datetime.now().astimezone()
        retry = retry_changes(job, moment)
        update_schedule(
            job["id"],
            last_status="failed",
            last_error=reason,
            last_run_at=moment.isoformat(timespec="seconds"),
            **retry,
        )
        if retry["retry_at"]:
            log_event(
                "schedule.retry",
                f"Scheduled job {job.get('name', job.get('id', ''))} will run again",
                job=job.get("id"),
                attempt=retry["retry_attempt"],
                retry_at=retry["retry_at"],
            )
        else:
            log_event("schedule.gave_up", f"Scheduled job {job.get('name', job.get('id', ''))} used all its retries", job=job.get("id"))
    finally:
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id:
            with SCHEDULE_RUNNING_LOCK:
                SCHEDULE_RUNNING.discard(job_id)


def start_job(job: dict[str, Any]) -> None:
    """Run one due job in its own thread."""
    threading.Thread(target=execute_schedule, args=(job,), daemon=True).start()


def run_due_jobs(now: datetime) -> None:
    """Start every enabled job whose cron matches this minute.

    Kept apart from the loop so the cron decision can be tested without waiting
    for 06:00: the loop only decides when to check, this decides what runs.
    """
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    for job in load_schedules():
        if not job.get("enabled", True):
            continue
        # A failed run leaves its retry time behind; it is tried again on the
        # first check after that moment instead of waiting for the next cron
        # minute, which for a daily job used to be a whole day later.
        pending_retry = retry_moment(job.get("retry_at"))
        is_retry = pending_retry is not None and pending_retry <= now
        if not is_retry:
            if job.get("last_run_key") == minute_key:
                continue
            try:
                due = cron_matches(job["schedule"], now)
            except (KeyError, TypeError, ValueError):
                # Only a broken cron expression lands here: a save failure below must
                # not be reported as an invalid schedule.
                update_schedule(job.get("id", ""), last_status="failed", last_error="invalid_cron")
                continue
            if not due:
                continue
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        with SCHEDULE_RUNNING_LOCK:
            if job_id in SCHEDULE_RUNNING:
                log_event("schedule.skipped", "Skipped a job that is still running", job=job_id)
                continue
            SCHEDULE_RUNNING.add(job_id)
        try:
            if is_retry:
                # Clear the slot before running so a crashed attempt cannot
                # dispatch the same retry every minute; a failure writes a new
                # one before this thread ends.
                update_schedule(job_id, retry_at="")
                log_event("schedule.retry_start", f"Retrying scheduled job {job.get('name', job_id)}", job=job_id, attempt=retry_attempt_of(job))
            else:
                # A fresh cron run replaces any pending retry and starts its own
                # chain: inheriting the old count made a frequent job give up
                # after three failures spread over unrelated runs.
                job.update({"last_run_key": minute_key, "retry_at": "", "retry_attempt": 0})
                update_schedule(job_id, last_run_key=minute_key, retry_at="", retry_attempt=0)
            start_job(job)
        except Exception:
            with SCHEDULE_RUNNING_LOCK:
                SCHEDULE_RUNNING.discard(job_id)
            raise


def schedule_loop() -> None:
    """Check due jobs every 15 seconds and dispatch them in threads."""
    last_minute = ""
    while True:
        now = datetime.now().astimezone()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key != last_minute:
            last_minute = minute_key
            try:
                run_due_jobs(now)
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
