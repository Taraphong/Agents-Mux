"""A scheduled job must run unattended, use its tools, and report a real answer.

The job used to send its own approval placeholder to Discord: the scheduler
replayed the job conversation (placeholder included) and never ran the tools a
prompt asked for, while still recording the run as a success.
"""

import copy

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


def test_approval_placeholder_and_tool_results_are_not_replayed(run):
    run["history"] = [
        {"role": "user", "content": "แชตเก่า"},
        {"role": "assistant", "content": APPROVAL_PLACEHOLDER},
        {
            "role": "user",
            "content": "Tool result: ...",
            "tool_result": True,
            "tool_name": "run_command",
        },
        {"role": "assistant", "content": "รายงานครั้งก่อน"},
    ]
    run["answers"] = ["รายงานใหม่"]

    scheduler.execute_schedule(dict(JOB))

    sent = run["provider_messages"][0]
    contents = [message.get("content") for message in sent]
    assert APPROVAL_PLACEHOLDER not in contents
    assert "Tool result: ..." not in contents
    assert "แชตเก่า" in contents
    assert "รายงานครั้งก่อน" in contents
    assert JOB["prompt"] in contents


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


def test_a_tool_call_that_never_resolves_marks_the_job_failed(run):
    marker = '<tool_call>{"name":"run_command","arguments":{"command":"true"}}</tool_call>'
    run["answers"] = [marker] * (scheduler.SCHEDULE_TOOL_ROUNDS + 1)

    scheduler.execute_schedule(dict(JOB))

    assert len(run["tools"]) == scheduler.SCHEDULE_TOOL_ROUNDS
    assert run["discord"] == []
    assert run["updates"][-1]["last_error"] == "unreadable_tool_call"
