"""A scheduled job that fails is retried after a delay.

The morning weather jobs failed with a provider 503 and a read timeout, and
because ``last_run_key`` was already set for that minute they were never tried
again — a daily job therefore lost its whole day. A failure now leaves a
``retry_at`` time on the job, and the loop starts it again on the first check
after that moment.
"""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from core.config import SCHEDULE_RETRY_DELAYS
from services import scheduler

TZ = timezone(timedelta(hours=7))
JOB = {
    "id": "615384c4-8c9b-4cac-8124-825685ff2200",
    "name": "Weather_MSU",
    "schedule": "0 6 * * *",
    "prompt": "รายงานสภาพอากาศ",
    "enabled": True,
    "conversation_id": "a869e191-c52d-43ed-b1dc-366e972e0c3d",
}
MINUTE_KEY = "2026-11-26 06:00"


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 26, hour, minute, tzinfo=TZ)


@pytest.fixture()
def run(monkeypatch):
    """Run one job against a scripted provider that always fails."""
    state = {"saved": [], "discord": [], "updates": [], "events": []}

    def failing_provider(messages, settings):
        raise RuntimeError("503 Server Error: Service Unavailable")

    monkeypatch.setattr(scheduler, "load_settings", lambda: {"provider": "gemini", "model": "test"})
    monkeypatch.setattr(scheduler, "call_provider", failing_provider)
    monkeypatch.setattr(scheduler, "load_history_record", lambda conversation_id: {"messages": []})
    monkeypatch.setattr(scheduler, "save_history", lambda record: state["saved"].append(record))
    monkeypatch.setattr(scheduler, "send_discord_schedule_result", lambda job, answer: state["discord"].append(answer))
    monkeypatch.setattr(
        scheduler,
        "update_schedule",
        lambda job_id, **changes: state["updates"].append(changes),
    )
    monkeypatch.setattr(
        scheduler,
        "log_event",
        lambda event, message, **details: state["events"].append((event, details)),
    )
    return state


def test_a_failed_run_schedules_the_first_retry(run, monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return at(6, 2)

    monkeypatch.setattr(scheduler, "datetime", FakeDateTime)

    scheduler.execute_schedule(dict(JOB, last_run_key=MINUTE_KEY))

    changes = run["updates"][-1]
    assert changes["last_status"] == "failed"
    assert changes["retry_attempt"] == 1
    delay = datetime.fromisoformat(changes["retry_at"]) - at(6, 2)
    assert delay == timedelta(seconds=SCHEDULE_RETRY_DELAYS[0])
    assert [event for event, _ in run["events"]] == ["schedule.error", "schedule.retry"]
    assert run["discord"] == []


def test_each_failure_waits_the_next_delay(run, monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return at(6, 2)

    monkeypatch.setattr(scheduler, "datetime", FakeDateTime)

    scheduler.execute_schedule(dict(JOB, retry_attempt=1))

    changes = run["updates"][-1]
    assert changes["retry_attempt"] == 2
    delay = datetime.fromisoformat(changes["retry_at"]) - at(6, 2)
    assert delay == timedelta(seconds=SCHEDULE_RETRY_DELAYS[1])


def test_the_last_failure_clears_the_retry_and_waits_for_the_next_cron_minute(run):
    scheduler.execute_schedule(dict(JOB, retry_attempt=len(SCHEDULE_RETRY_DELAYS)))

    changes = run["updates"][-1]
    assert changes["retry_at"] == ""
    assert changes["retry_attempt"] == 0
    assert [event for event, _ in run["events"]] == ["schedule.error", "schedule.gave_up"]


def test_a_broken_retry_attempt_does_not_stop_the_run(run):
    scheduler.execute_schedule(dict(JOB, retry_attempt="not a number"))

    changes = run["updates"][-1]
    assert changes["retry_attempt"] == 1


def test_a_success_clears_the_retry(run, monkeypatch):
    monkeypatch.setattr(scheduler, "call_provider", lambda messages, settings: ("รายงาน", {}))
    monkeypatch.setattr(
        scheduler,
        "load_history_record",
        lambda conversation_id: {"title": "⏰ Weather_MSU", "messages": []},
    )

    scheduler.execute_schedule(dict(JOB, retry_attempt=1, retry_at="2026-11-26T06:10:00+07:00"))

    changes = run["updates"][-1]
    assert changes["last_status"] == "success"
    assert changes["retry_at"] == ""
    assert changes["retry_attempt"] == 0


@pytest.fixture()
def loop_env(monkeypatch):
    state = {"jobs": [], "started": [], "updates": [], "events": []}

    monkeypatch.setattr(scheduler, "load_schedules", lambda: state["jobs"])
    monkeypatch.setattr(
        scheduler,
        "update_schedule",
        lambda job_id, **changes: state["updates"].append((job_id, changes)),
    )
    monkeypatch.setattr(scheduler, "start_job", lambda job: state["started"].append(job))
    monkeypatch.setattr(
        scheduler,
        "log_event",
        lambda event, message, **details: state["events"].append((event, details)),
    )
    scheduler.SCHEDULE_RUNNING.clear()
    yield state
    scheduler.SCHEDULE_RUNNING.clear()


def test_a_due_retry_starts_even_though_this_minute_already_ran(loop_env):
    loop_env["jobs"] = [
        {**JOB, "last_run_key": MINUTE_KEY, "retry_at": at(6, 5).isoformat(timespec="seconds"), "retry_attempt": 1}
    ]

    scheduler.run_due_jobs(at(6, 5))

    assert [job["id"] for job in loop_env["started"]] == [JOB["id"]]
    assert loop_env["updates"] == [(JOB["id"], {"retry_at": ""})]
    assert [event for event, _ in loop_env["events"]] == ["schedule.retry_start"]


def test_a_retry_that_is_not_due_yet_does_not_run(loop_env):
    loop_env["jobs"] = [{**JOB, "last_run_key": MINUTE_KEY, "retry_at": at(6, 5).isoformat(timespec="seconds")}]

    scheduler.run_due_jobs(at(6, 4))

    assert loop_env["started"] == []
    assert loop_env["updates"] == []


def test_a_retry_never_runs_a_disabled_job(loop_env):
    loop_env["jobs"] = [
        {**JOB, "enabled": False, "retry_at": at(6, 5).isoformat(timespec="seconds")}
    ]

    scheduler.run_due_jobs(at(6, 5))

    assert loop_env["started"] == []


def test_a_retry_waits_while_the_job_is_still_running(loop_env):
    loop_env["jobs"] = [{**JOB, "retry_at": at(6, 5).isoformat(timespec="seconds")}]
    scheduler.SCHEDULE_RUNNING.add(JOB["id"])

    scheduler.run_due_jobs(at(6, 5))

    assert loop_env["started"] == []
    assert [event for event, _ in loop_env["events"]] == ["schedule.skipped"]


def test_a_broken_retry_time_is_ignored(loop_env):
    loop_env["jobs"] = [{**JOB, "last_run_key": MINUTE_KEY, "retry_at": "yesterday"}]

    scheduler.run_due_jobs(at(6, 5))

    assert loop_env["started"] == []


def test_the_retry_keeps_the_job_and_its_conversation(loop_env):
    loop_env["jobs"] = [
        {**JOB, "retry_at": at(6, 5).isoformat(timespec="seconds"), "retry_attempt": 2}
    ]

    scheduler.run_due_jobs(at(6, 5))

    started = copy.deepcopy(loop_env["started"][0])
    assert started["conversation_id"] == JOB["conversation_id"]
    assert started["retry_attempt"] == 2
