"""The cron loop must start a job when its schedule is due.

Only the Run now button was covered, so a job that fires on its own at 06:00 was
untested. ``run_due_jobs`` holds the cron decision and ``schedule_loop`` only
decides when to check, so both can be tested without waiting for a real minute.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services import scheduler

TZ = timezone(timedelta(hours=7))
JOB = {
    "id": "615384c4-8c9b-4cac-8124-825685ff2200",
    "name": "Weather_MSU",
    "schedule": "0 6 * * *",
    "prompt": "รายงานสภาพอากาศ",
    "enabled": True,
}
MINUTE_KEY = "2026-11-25 06:00"


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 25, hour, minute, tzinfo=TZ)


class StopLoop(Exception):
    """Sentinel used to end ``schedule_loop`` inside a test."""


@pytest.fixture()
def job_env(monkeypatch):
    """Replace the job list, the job thread and the schedule store."""
    state = {"jobs": [dict(JOB)], "started": [], "updates": [], "events": []}

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


@pytest.fixture()
def loop(monkeypatch):
    """Drive ``schedule_loop`` with a fake clock until a fixed number of sleeps."""

    class Harness:
        def __init__(self):
            self.minutes = []
            self.sleeps = []
            self.due = lambda now: self.minutes.append(now)

        def run(self, times, stop_after_sleeps):
            pending = list(times)

            class FakeDateTime:
                @classmethod
                def now(cls):
                    return pending.pop(0) if pending else times[-1]

            def fake_sleep(seconds):
                self.sleeps.append(seconds)
                if len(self.sleeps) >= stop_after_sleeps:
                    raise StopLoop

            monkeypatch.setattr(scheduler, "datetime", FakeDateTime)
            monkeypatch.setattr(scheduler.time, "sleep", fake_sleep)
            monkeypatch.setattr(scheduler, "run_due_jobs", self.due)
            with pytest.raises(StopLoop):
                scheduler.schedule_loop()

    return Harness()


def test_a_due_job_starts_at_its_cron_minute(job_env):
    scheduler.run_due_jobs(at(6, 0))

    assert [job["id"] for job in job_env["started"]] == [JOB["id"]]
    assert job_env["updates"] == [
        (JOB["id"], {"last_run_key": MINUTE_KEY, "retry_at": "", "retry_attempt": 0})
    ]


def test_a_cron_run_starts_its_own_retry_chain(job_env):
    job_env["jobs"] = [
        {
            **JOB,
            "schedule": "* * * * *",
            "retry_at": "2026-11-25T06:40:00+07:00",
            "retry_attempt": 2,
        }
    ]

    scheduler.run_due_jobs(at(6, 0))

    started = job_env["started"][0]
    assert started["retry_attempt"] == 0
    assert started["retry_at"] == ""


@pytest.mark.parametrize(
    ("overrides", "now"),
    [
        ({}, at(5, 59)),
        ({"enabled": False}, at(6, 0)),
        ({"last_run_key": MINUTE_KEY}, at(6, 0)),
    ],
    ids=["before-the-minute", "disabled", "already-ran-this-minute"],
)
def test_a_job_that_is_not_due_is_not_started(job_env, overrides, now):
    job_env["jobs"] = [{**JOB, **overrides}]

    scheduler.run_due_jobs(now)

    assert job_env["started"] == []
    assert job_env["updates"] == []


def test_a_job_that_is_still_running_is_skipped(job_env):
    scheduler.SCHEDULE_RUNNING.add(JOB["id"])

    scheduler.run_due_jobs(at(6, 0))

    assert job_env["started"] == []
    assert [event for event, _ in job_env["events"]] == ["schedule.skipped"]


def test_an_invalid_cron_marks_the_job_failed(job_env):
    job_env["jobs"] = [{**JOB, "schedule": "not a cron"}]

    scheduler.run_due_jobs(at(6, 0))

    assert job_env["started"] == []
    assert job_env["updates"] == [(JOB["id"], {"last_status": "failed", "last_error": "invalid_cron"})]


def test_the_loop_checks_each_new_minute_only(loop):
    loop.run([at(6, 0), at(6, 0), at(6, 1)], stop_after_sleeps=3)

    assert [moment.minute for moment in loop.minutes] == [0, 1]
    assert loop.sleeps == [15, 15, 15]


def test_the_loop_keeps_running_when_the_jobs_cannot_be_read(loop, monkeypatch):
    events = []

    def broken(now):
        raise OSError("cannot read the scheduled jobs")

    loop.due = broken
    monkeypatch.setattr(scheduler, "log_event", lambda event, message, **details: events.append(event))

    loop.run([at(6, 0)], stop_after_sleeps=1)

    assert events == ["schedule.error"]
