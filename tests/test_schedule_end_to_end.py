"""End-to-end: a scheduled run reaches history and Discord for real.

The other scheduler tests stub ``save_history`` and ``send_discord_schedule_result``,
so they prove the answer was passed along but not that it is stored and delivered.
Here the real history store runs against a temporary folder, and the report goes
through the real Discord sender (message prefix and chunk splitting included)
with a fake client; only the provider, the tools, the Discord client and
``update_schedule`` are fakes.
"""

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from core import history
from services import discord_bot, scheduler

CHANNEL_ID = "1569295865338789979"
CONVERSATION_ID = "a869e191-c52d-43ed-b1dc-366e972e0c3d"
JOB = {
    "id": "615384c4-8c9b-4cac-8124-825685ff2200",
    "name": "Weather_MSU",
    "prompt": "รายงานสภาพอากาศปัจจุบันของ มหาสารคาม",
    "conversation_id": CONVERSATION_ID,
    "discord_channel_id": CHANNEL_ID,
    "schedule": "0 6 * * *",
}


@pytest.fixture()
def history_root(tmp_path, monkeypatch):
    """Point the real history store at a temporary folder.

    The store reads these module globals, so using the real save/load path means
    moving them. The path goes through realpath because the store checks writes
    against the resolved root, and some systems keep their temp folder behind a
    symlink.
    """
    root = Path(os.path.realpath(tmp_path / "history"))
    root.mkdir(parents=True)
    monkeypatch.setattr(history, "HISTORY_ROOT", root)
    monkeypatch.setattr(history, "HISTORY_ROOT_TEXT", str(root))
    monkeypatch.setattr(history, "HISTORY_LOCK_FILE", str(tmp_path / "history.lock"))
    return root


@pytest.fixture()
def discord_messages(monkeypatch):
    """Run the real Discord sender against a fake client.

    The sender hands its coroutine to the bot's event loop, so the fake loop has
    to be running in a thread; the fake client only records what was sent.
    """
    sent: list[str] = []

    class FakeChannel:
        async def send(self, content: str) -> None:
            sent.append(content)

    class FakeClient:
        def get_channel(self, channel_id: int):
            return FakeChannel() if channel_id == int(CHANNEL_ID) else None

        async def fetch_channel(self, channel_id: int):
            raise RuntimeError(f"Unknown channel {channel_id}")

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(discord_bot, "DISCORD_BOT", FakeClient())
    monkeypatch.setattr(discord_bot, "DISCORD_LOOP", loop)
    try:
        yield sent
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


@dataclass
class ScheduledJob:
    """Run a job with a scripted provider while keeping history and Discord real."""

    history_root: Path
    discord_messages: list[str]
    answers: list[str] = field(default_factory=list)
    provider_calls: list[list[dict]] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    update_calls: list[tuple[str, dict]] = field(default_factory=list)

    def run(self, *answers: str, target: dict | None = None) -> dict:
        """Run the job once with these provider answers and return the saved record."""
        self.answers = list(answers)
        scheduler.execute_schedule(dict(target or JOB))
        return history.load_history_record(CONVERSATION_ID)

    def answer_as_provider(self, messages, settings):
        self.provider_calls.append(messages)
        return self.answers.pop(0), {"total_tokens": 7}

    def run_tool(self, name, arguments, approved=False):
        self.tool_calls.append({"name": name, "arguments": arguments, "approved": approved})
        return {"tool": name, "returncode": 0, "stdout": "30.5"}


@pytest.fixture()
def job(monkeypatch, history_root, discord_messages):
    harness = ScheduledJob(history_root=history_root, discord_messages=discord_messages)
    monkeypatch.setattr(
        scheduler,
        "load_settings",
        lambda: {"provider": "gemini", "model": "gemini-test", "system_prompt": "base prompt"},
    )
    monkeypatch.setattr(scheduler, "call_provider", harness.answer_as_provider)
    monkeypatch.setattr(scheduler, "run_local_tool", harness.run_tool)
    monkeypatch.setattr(
        scheduler,
        "update_schedule",
        lambda job_id, **changes: harness.update_calls.append((job_id, changes)),
    )
    return harness


def test_a_scheduled_run_writes_history_and_delivers_the_report(job):
    answer = "🌤️ มหาสารคาม 30.5°C"

    record = job.run(
        '<tool_call>{"name":"run_command","arguments":{"command":"curl -s https://example.org"}}</tool_call>',
        answer,
    )

    assert record["title"] == "⏰ Weather_MSU"
    assert [(m["role"], m["content"], m["schedule_id"]) for m in record["messages"]] == [
        ("user", JOB["prompt"], JOB["id"]),
        ("assistant", answer, JOB["id"]),
    ]
    # The dated file the web page reads really exists on disk.
    files = list(job.history_root.rglob(f"*_{CONVERSATION_ID}.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["messages"][-1]["content"] == answer
    assert job.tool_calls == [
        {"name": "run_command", "arguments": {"command": "curl -s https://example.org"}, "approved": True}
    ]
    assert job.discord_messages == [f"⏰ {JOB['name']}\n\n{answer}"]
    assert job.update_calls[-1][1]["last_status"] == "success"


def test_a_second_run_appends_to_the_same_conversation(job):
    job.run("รายงานรอบแรก")
    record = job.run("รายงานรอบสอง")

    assert [m["content"] for m in record["messages"]] == [
        JOB["prompt"],
        "รายงานรอบแรก",
        JOB["prompt"],
        "รายงานรอบสอง",
    ]
    # The second call got the first report back as context, read from the file.
    assert "รายงานรอบแรก" in [m.get("content") for m in job.provider_calls[1]]
    assert job.discord_messages == [
        f"⏰ {JOB['name']}\n\nรายงานรอบแรก",
        f"⏰ {JOB['name']}\n\nรายงานรอบสอง",
    ]


def test_a_long_report_is_split_across_discord_chunks(job):
    answer = "รายละเอียดสภาพอากาศ " + "ก" * 4500

    record = job.run(answer)

    assert len(job.discord_messages) > 1
    assert all(len(chunk) <= 2000 for chunk in job.discord_messages)
    assert "".join(job.discord_messages) == f"⏰ {JOB['name']}\n\n{answer}"
    # History keeps the whole report, not one chunk.
    assert record["messages"][-1]["content"] == answer


def test_a_discord_failure_keeps_the_report_in_history(job, monkeypatch):
    logs = []
    monkeypatch.setattr(scheduler, "log_event", lambda event, message, **details: logs.append(event))

    record = job.run("รายงานที่บันทึกไว้", target={**JOB, "discord_channel_id": "111111111111111111"})

    assert record["messages"][-1]["content"] == "รายงานที่บันทึกไว้"
    assert job.discord_messages == []
    assert job.update_calls[-1][1]["last_status"] == "success"
    assert "schedule.discord_error" in logs
    assert logs[-1] == "schedule.success"
