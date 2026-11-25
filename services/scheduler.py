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
from datetime import datetime
from typing import Any

from core.config import (
    SCHEDULE_CONTEXT_MESSAGES,
    SCHEDULE_LOCK_FILE,
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


def run_schedule_turn(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Call the model and run its tool calls without asking for an approval.

    A job is unattended and its prompt was written by the owner, so its tools
    run directly. The loop is bounded so a bad job cannot call tools forever.
    """
    answer, usage = call_provider(messages, settings)
    repaired = False
    for _ in range(SCHEDULE_TOOL_ROUNDS):
        try:
            tool_requests = parse_tool_requests(answer)
        except ValueError as exc:
            log_event(
                "schedule.tool_parse_failed",
                "Skipped an unreadable tool_call in a scheduled job",
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
        # instead of calling run_command itself.
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
                skills_prompt(settings),
                JOB_RUN_GUIDANCE,
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
        raw_answer, usage = run_schedule_turn(messages, settings)
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
        update_schedule(job["id"], last_status="success", last_error="", last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        log_event("schedule.success", f"Scheduled job {job['name']} succeeded", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        # The job list is returned by /api/schedules, so only a short reason is
        # stored; the message stays in the log above.
        reason = str(getattr(exc, "kind", "") or exc.__class__.__name__)[:60]
        log_event("schedule.error", f"Scheduled job {job.get('name', job.get('id', ''))} failed", error=str(exc))
        update_schedule(job["id"], last_status="failed", last_error=reason, last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
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
                        update_schedule(job.get("id", ""), last_status="failed", last_error="invalid_cron")
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
