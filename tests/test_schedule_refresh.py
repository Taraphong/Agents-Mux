"""The Scheduled jobs list refreshes itself while its view is open.

The view used to load once, so a retry time written by the scheduler (and the
"จะลองใหม่ HH:MM" label built from it) stayed stale until a page reload. The
real page functions are run by ``tests/schedule_refresh_harness.js`` against a
small DOM stub: this test only starts it and checks the wiring around it.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = ROOT / "templates" / "index" / "index.js"
HARNESS = ROOT / "tests" / "schedule_refresh_harness.js"
NODE = shutil.which("node")


def test_the_refresh_behaviour_of_the_real_page_functions():
    if NODE is None:
        pytest.skip("node runs the page script")
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(ROOT),
        env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["ok"] is True, summary
    # First paint, then one repaint for the changed retry time only.
    assert summary["renders"] == 2


def test_the_timer_is_wired_to_the_schedule_view_and_tab_visibility():
    src = INDEX_JS.read_text(encoding="utf-8")

    assert "startScheduleRefresh();" in src
    assert "stopScheduleRefresh();" in src
    assert 'document.addEventListener("visibilitychange"' in src
    # The list is only repainted through the change check, so a poll cannot
    # wipe the edit form or flash the same rows again.
    load = src[src.index("async function loadSchedules(") :]
    load = load[: load.index("\n}\n")]
    assert "renderSchedulesIfChanged(currentSchedules)" in load
    assert "renderSchedules(currentSchedules);" not in load
