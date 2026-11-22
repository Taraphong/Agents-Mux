"""Scheduled jobs and the cron matcher.

The job list is one JSON file guarded by a process lock; the cron helpers are
pure so the scheduler loop can ask them about any local time.
"""

import json
import re
import threading
from datetime import datetime
from typing import Any

from core.config import SCHEDULE_FILE


SCHEDULE_LOCK = threading.Lock()


def load_schedules() -> list[dict[str, Any]]:
    """Load the scheduled jobs list, tolerating a missing or broken file."""
    if not SCHEDULE_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_schedules(jobs: list[dict[str, Any]]) -> None:
    """Write the scheduled jobs list to disk as formatted JSON."""
    SCHEDULE_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def cron_values(field: str, minimum: int, maximum: int, alias_max: int | None = None) -> set[int]:
    """Expand one cron field into concrete values, rejecting malformed input."""
    upper = alias_max if alias_max is not None else maximum
    values: set[int] = set()
    for part in str(field).split(","):
        match = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", part.strip())
        if not match:
            raise ValueError(f"Invalid cron field: {part}")
        base, step_text = match.group(1), match.group(2)
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError("A cron step must be greater than 0")
        if base == "*":
            start, end = minimum, upper
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError("Invalid cron range (the first value must not exceed the last)")
        else:
            start = int(base)
            # "N/step" (e.g. 0/5) starts at N and repeats every step, while a
            # bare "N" is a single value. Treating both as N silently turned
            # "0/5" into "minute 0 only".
            end = upper if step_text else start
        if start > end:
            raise ValueError("Invalid cron range (the first value must not exceed the last)")
        if start < minimum or end > upper:
            raise ValueError(f"The cron value must be between {minimum} and {upper}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("Empty cron value")
    if alias_max is not None:
        # Cron accepts both 0 and 7 for Sunday.
        values = {minimum if value == alias_max else value for value in values}
    if min(values) < minimum or max(values) > maximum:
        raise ValueError(f"The cron value must be between {minimum} and {maximum}")
    return values


def validate_cron(expression: str) -> str:
    """Validate a five-field cron expression and return it normalized."""
    aliases = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *"}
    expression = aliases.get(str(expression).strip().lower(), str(expression).strip())
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("A cron expression needs 5 fields, for example */5 * * * * or 0 9 * * 1-5")
    for field, minimum, maximum, alias_max in zip(
        fields, (0, 0, 1, 1, 0), (59, 23, 31, 12, 6), (None, None, None, None, 7)
    ):
        cron_values(field, minimum, maximum, alias_max)
    return expression


def cron_matches(expression: str, now: datetime) -> bool:
    """Return whether a cron expression fires at the given local time."""
    minute, hour, day_of_month, month, day_of_week = validate_cron(expression).split()
    if now.minute not in cron_values(minute, 0, 59):
        return False
    if now.hour not in cron_values(hour, 0, 23):
        return False
    if now.month not in cron_values(month, 1, 12):
        return False
    dom_matches = now.day in cron_values(day_of_month, 1, 31)
    dow_matches = ((now.weekday() + 1) % 7) in cron_values(day_of_week, 0, 6, 7)
    # Standard cron ORs day-of-month and day-of-week when both are restricted.
    if day_of_month.strip() == "*" or day_of_week.strip() == "*":
        return dom_matches and dow_matches
    return dom_matches or dow_matches


def update_schedule(job_id: str, **changes: Any) -> None:
    """Apply field changes to one scheduled job and save the list."""
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        for job in jobs:
            if job.get("id") == job_id:
                job.update(changes)
                break
        save_schedules(jobs)
