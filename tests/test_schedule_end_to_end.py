"""End-to-end: a scheduled run reaches history and Discord for real.

The other scheduler tests stub ``save_history`` and ``send_discord_schedule_result``,
so they prove the answer was passed along but not that it is stored and delivered.
Here the real history store runs against a temporary folder, and the report goes
through the real Discord sender (message prefix and chunk splitting included)
with a fake client; only the provider and the Discord client are fakes.
"""

import asyncio
import json
import threading

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
    """Point the real history store at a temporary folder."""
    root = tmp_path / "history"
    root.mkdir()
    monkeypatch.setattr(history, "HISTORY_ROOT", root)
    monkeypatch.setattr(history, "HISTORY_ROOT_TEXT", str(root))
    monkeypatch.setattr(history, "HISTORY_LOCK_FILE", str(tmp_path / "history.lock"))
    return root


@pytest.fixture()
def discord(monkeypatch):
    """Run the real Discord sender against a fake client on a real event loop."""
    sent: list[str] = []

    class FakeChannel:
        async def send(self, content: str) -> None:
            sent.append(content)

    class FakeClient:
        def get_channel(self, channel_id: int) -> FakeChannel | None:
            return FakeChannel() if channel_id == int(CHANNEL_ID) else None

        async def fetch_channel(self, channel_id: int) -> FakeChannel:
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


@pytest.fixture()
def scheduled_run(monkeypatch, history_root, discord):
    """Script the provider and record what the job does, keeping history real."""
    state = {"answers": [], "calls": [], "tools": [], "updates": [], "root": history_root, "sent": discord}

    def fake_call_provider(messages, settings):
        state["calls"].append((messages, settings))
        return state["answers"].pop(0), {"total_tokens": 7}

    def fake_run_local_tool(name, arguments, approved=False):
        state["tools"].append({"name": name, "arguments": arguments, "approved": approved})
        return {"tool": name, "returncode": 0, "stdout": "30.5"}

    monkeypatch.setattr(
        scheduler,
        "load_settings",
        lambda: {"provider": "gemini", "model": "gemini-test", "system_prompt": "base prompt"},
    )
    monkeypatch.setattr(scheduler, "call_provider", fake_call_provider)
    monkeypatch.setattr(scheduler, "run_local_tool", fake_run_local_tool)
    monkeypatch.setattr(
        scheduler,
        "update_schedule",
        lambda job_id, **changes: state["updates"].append((job_id, changes)),
    )
    return state


def test_a_scheduled_run_writes_history_and_delivers_the_report(scheduled_run):
    answer = "🌤️ มหาสารคาม 30.5°C"
    scheduled_run["answers"] = [
        '<tool_call>{"name":"run_command","arguments":{"command":"curl -s https://example.org"}}</tool_call>',
        answer,
    ]

    scheduler.execute_schedule(dict(JOB))

    record = history.load_history_record(CONVERSATION_ID)
    assert record["title"] == "⏰ Weather_MSU"
    assert [message["role"] for message in record["messages"]] == ["user", "assistant"]
    assert record["messages"][0]["content"] == JOB["prompt"]
    assert record["messages"][0]["schedule_id"] == JOB["id"]
    assert record["messages"][1]["content"] == answer
    assert record["messages"][1]["schedule_id"] == JOB["id"]
    # The dated file the web page reads really exists on disk.
    files = list(scheduled_run["root"].rglob(f"*_{CONVERSATION_ID}.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["messages"][-1]["content"] == answer
    assert scheduled_run["sent"] == [f"⏰ {JOB['name']}\n\n{answer}"]
    assert scheduled_run["updates"][-1][1]["last_status"] == "success"


def test_the_next_run_appends_to_the_same_conversation(scheduled_run):
    scheduled_run["answers"] = ["รายงานรอบแรก"]
    scheduler.execute_schedule(dict(JOB))
    scheduled_run["answers"] = ["รายงานรอบสอง"]
    scheduler.execute_schedule(dict(JOB))

    record = history.load_history_record(CONVERSATION_ID)
    assert [message["content"] for message in record["messages"]] == [
        JOB["prompt"],
        "รายงานรอบแรก",
        JOB["prompt"],
        "รายงานรอบสอง",
    ]
    # The second call got the first report back as context, from the real file.
    assert any(message.get("content") == "รายงานรอบแรก" for message in scheduled_run["calls"][1][0])
    assert scheduled_run["sent"] == [
        f"⏰ {JOB['name']}\n\nรายงานรอบแรก",
        f"⏰ {JOB['name']}\n\nรายงานรอบสอง",
    ]


def test_a_long_report_is_split_across_discord_chunks(scheduled_run):
    answer = "รายละเอียดสภาพอากาศ " + "ก" * 4500
    scheduled_run["answers"] = [answer]

    scheduler.execute_schedule(dict(JOB))

    assert len(scheduled_run["sent"]) == 3
    assert all(len(chunk) <= 2000 for chunk in scheduled_run["sent"])
    assert "".join(scheduled_run["sent"]) == f"⏰ {JOB['name']}\n\n{answer}"
    # The stored report is the whole answer, not one chunk.
    stored = history.load_history_record(CONVERSATION_ID)["messages"][-1]["content"]
    assert stored == answer


def test_a_discord_failure_keeps_the_report_in_history(scheduled_run, monkeypatch):
    scheduled_run["answers"] = ["รายงานที่บันทึกไว้"]
    logs = []
    monkeypatch.setattr(scheduler, "log_event", lambda event, message, **details: logs.append(event))

    scheduler.execute_schedule({**JOB, "discord_channel_id": "111111111111111111"})

    assert history.load_history_record(CONVERSATION_ID)["messages"][-1]["content"] == "รายงานที่บันทึกไว้"
    assert scheduled_run["sent"] == []
    assert scheduled_run["updates"][-1][1]["last_status"] == "success"
    assert "schedule.discord_error" in logs
    assert logs[-1] == "schedule.success"
