"""A scheduled job must run unattended, use its tools, and report a real answer.

The job used to send its own approval placeholder to Discord: the scheduler
replayed the job conversation (placeholder included) and never ran the tools a
prompt asked for, while still recording the run as a success.
"""

import copy
import re
from datetime import datetime, timedelta, timezone

import pytest

from core.config import APPROVAL_PLACEHOLDER
from services import scheduler

JOB = {
    "id": "615384c4-8c9b-4cac-8124-825685ff2200",
    "name": "Weather_MSU",
    "prompt": "รายงานสภาพอากาศปัจจุบันของ มหาสารคาม",
    "conversation_id": "a869e191-c52d-43ed-b1dc-366e972e0c3d",
    "discord_channel_id": "1569295865338789979",
}


@pytest.fixture()
def run(monkeypatch):
    """Run one job against a scripted provider and record its side effects."""
    state = {
        "answers": [],
        "provider_messages": [],
        "saved": [],
        "discord": [],
        "updates": [],
        "tools": [],
        "history": [],
    }

    def fake_call_provider(messages, settings):
        state["provider_messages"].append(copy.deepcopy(messages))
        answer = state["answers"].pop(0) if state["answers"] else ""
        return answer, {"total_tokens": 1}

    def fake_run_local_tool(name, arguments, approved=False):
        state["tools"].append({"name": name, "arguments": arguments, "approved": approved})
        return {"tool": name, "returncode": 0, "stdout": "ok"}

    monkeypatch.setattr(scheduler, "load_settings", lambda: {"provider": "gemini", "model": "test"})
    monkeypatch.setattr(scheduler, "call_provider", fake_call_provider)
    monkeypatch.setattr(
        scheduler,
        "load_history_record",
        lambda conversation_id: {"title": "⏰ Weather_MSU", "messages": state["history"]},
    )
    monkeypatch.setattr(scheduler, "save_history", lambda record: state["saved"].append(record))
    monkeypatch.setattr(
        scheduler,
        "send_discord_schedule_result",
        lambda job, answer: state["discord"].append(answer),
    )
    monkeypatch.setattr(
        scheduler,
        "update_schedule",
        lambda job_id, **changes: state["updates"].append(changes),
    )
    monkeypatch.setattr(scheduler, "run_local_tool", fake_run_local_tool)
    return state


def test_only_the_jobs_own_runs_are_replayed(run):
    job_id = JOB["id"]
    run["history"] = [
        {"role": "user", "content": "แชตเก่าที่ผู้ใช้คุยในบทสนทนานี้"},
        {"role": "assistant", "content": "ผมได้อัปเดตงานให้แล้ว"},
        {"role": "user", "content": "รายงานรอบก่อน", "schedule_id": job_id},
        {"role": "assistant", "content": "รายงานเก่า", "schedule_id": job_id},
        {"role": "assistant", "content": APPROVAL_PLACEHOLDER, "schedule_id": job_id},
        {
            "role": "user",
            "content": "Tool result: ...",
            "tool_result": True,
            "tool_name": "run_command",
            "schedule_id": job_id,
        },
    ]
    run["answers"] = ["รายงานใหม่"]

    scheduler.execute_schedule(dict(JOB))

    sent = run["provider_messages"][0]
    contents = [message.get("content") for message in sent]
    assert "แชตเก่าที่ผู้ใช้คุยในบทสนทนานี้" not in contents
    assert "ผมได้อัปเดตงานให้แล้ว" not in contents
    assert APPROVAL_PLACEHOLDER not in contents
    assert "Tool result: ..." not in contents
    assert "รายงานรอบก่อน" in contents
    assert "รายงานเก่า" in contents
    assert JOB["prompt"] in contents
    assert "automated scheduled run" in sent[0]["content"]


def test_tools_run_without_an_approval_and_the_answer_is_reported(run):
    run["answers"] = [
        '<tool_call>{"name":"run_command","arguments":{"command":"curl -s https://example.org"}}</tool_call>',
        "🌤️ รายงานสภาพอากาศ: 30.52°C",
    ]

    scheduler.execute_schedule(dict(JOB))

    assert run["tools"] == [
        {
            "name": "run_command",
            "arguments": {"command": "curl -s https://example.org"},
            "approved": True,
        }
    ]
    system_prompt = run["provider_messages"][0][0]["content"]
    assert "<tool_call>" in system_prompt
    assert run["saved"][0]["messages"][-1]["content"] == "🌤️ รายงานสภาพอากาศ: 30.52°C"
    assert run["discord"] == ["🌤️ รายงานสภาพอากาศ: 30.52°C"]
    assert run["updates"][-1]["last_status"] == "success"


def test_a_placeholder_answer_marks_the_job_failed_and_is_not_sent(run):
    run["answers"] = [APPROVAL_PLACEHOLDER]

    scheduler.execute_schedule(dict(JOB))

    assert run["saved"] == []
    assert run["discord"] == []
    assert run["updates"][-1]["last_status"] == "failed"
    assert run["updates"][-1]["last_error"] == "approval_placeholder"


def test_an_empty_answer_marks_the_job_failed(run):
    run["answers"] = ["   "]

    scheduler.execute_schedule(dict(JOB))

    assert run["saved"] == []
    assert run["discord"] == []
    assert run["updates"][-1]["last_error"] == "empty_answer"


def test_the_time_note_carries_the_machine_offset():
    note = scheduler.schedule_time_note(
        datetime(2026, 11, 25, 19, 26, 9, tzinfo=timezone(timedelta(hours=7)))
    )

    assert note.startswith("Current local time on this machine: 2026-11-25T19:26:09+07:00")
    assert "never guess" in note


def test_the_system_prompt_tells_the_model_the_machine_time(run):
    run["answers"] = ["รายงาน"]

    scheduler.execute_schedule(dict(JOB))

    system_prompt = run["provider_messages"][0][0]["content"]
    match = re.search(r"Current local time on this machine: (\S+)\.", system_prompt)
    assert match, system_prompt
    moment = datetime.fromisoformat(match.group(1))
    assert moment.utcoffset() is not None
    # The time note must stay before the tool rules, which work best last.
    assert system_prompt.index("Current local time") < system_prompt.index("<tool_call>")


def test_a_tool_error_names_the_job_in_the_log(run, monkeypatch):
    events = []
    monkeypatch.setattr(
        scheduler,
        "log_event",
        lambda event, message, **details: events.append((event, details)),
    )

    def broken_tool(name, arguments, approved=False):
        raise OSError("no such file")

    monkeypatch.setattr(scheduler, "run_local_tool", broken_tool)
    run["answers"] = [
        '<tool_call>{"name":"read_file","arguments":{"path":"/nope"}}</tool_call>',
        "รายงาน",
    ]

    scheduler.execute_schedule(dict(JOB))

    failure = next(details for event, details in events if event == "schedule.tool_error")
    assert failure["job"] == JOB["id"]
    assert failure["name"] == JOB["name"]
    assert failure["tool"] == "read_file"
    assert failure["error"] == "no such file"


def test_an_unreadable_tool_call_names_the_job_in_the_log(run, monkeypatch):
    events = []
    monkeypatch.setattr(
        scheduler,
        "log_event",
        lambda event, message, **details: events.append((event, details)),
    )
    run["answers"] = ["<tool_call>not json at all</tool_call>", "รายงาน"]

    scheduler.execute_schedule(dict(JOB))

    failure = next(
        details for event, details in events if event == "schedule.tool_parse_failed"
    )
    assert failure["job"] == JOB["id"]
    assert failure["name"] == JOB["name"]
    assert failure["error"]


def test_a_tool_call_that_never_resolves_marks_the_job_failed(run):
    marker = '<tool_call>{"name":"run_command","arguments":{"command":"true"}}</tool_call>'
    run["answers"] = [marker] * (scheduler.SCHEDULE_TOOL_ROUNDS + 1)

    scheduler.execute_schedule(dict(JOB))

    assert len(run["tools"]) == scheduler.SCHEDULE_TOOL_ROUNDS
    assert run["discord"] == []
    assert run["updates"][-1]["last_error"] == "unreadable_tool_call"
