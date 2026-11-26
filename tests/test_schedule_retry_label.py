"""The Settings job list shows the pending retry time the server stored.

A failed run leaves ``retry_at`` on the job (see ``services.scheduler``), and the
page has to show the wall clock inside it, in the current language. The page
script is exercised for real with node: the dictionary and
``scheduleRetryText`` are read from ``templates/index/index.js``, so a renamed
key or a changed format fails here instead of only in the browser.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services import scheduler

ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = ROOT / "templates" / "index" / "index.js"
TZ = timezone(timedelta(hours=7))
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node runs the page script")

# Runs the real function from index.js with the page's own t() lookup. The job
# list is rendered at a fixed clock time and always in local Thai time, so the
# expected text does not depend on when or where the tests run.
HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.env.INDEX_JS, "utf8");
const start = src.indexOf("const I18N = {"), end = src.indexOf("\n};", start);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(`var X = ${src.slice(src.indexOf("{", start), end + 2)};`, ctx);
const dict = ctx.X;
const match = src.match(/function scheduleRetryText\(job\) \{[\s\S]*?\n\}/);
if (!match) { console.error("scheduleRetryText not found"); process.exit(2); }
let raw = "";
process.stdin.on("data", (chunk) => { raw += chunk; });
process.stdin.on("end", () => {
  const payload = JSON.parse(raw);
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...args) {
      if (args.length) super(...args); else super(payload.now);
    }
    static now() { return payload.now; }
  }
  const read = (lang) => {
    const t = (key, vars) => {
      let text = dict[lang] && dict[lang][key] != null ? dict[lang][key] : key;
      for (const [name, value] of Object.entries(vars || {})) {
        text = text.split(`{${name}}`).join(value);
      }
      return text;
    };
    const page = new Function("t", "Date", `${match[0]}; return scheduleRetryText;`)(t, FakeDate);
    return page(payload.job);
  };
  console.log(JSON.stringify({ th: read("th"), en: read("en") }));
});
"""


def render(job: dict, now: datetime) -> dict:
    """Render the retry label the Settings list would show for this job."""
    result = subprocess.run(
        [NODE, "-e", HARNESS],
        input=json.dumps({"job": job, "now": int(now.timestamp() * 1000)}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "INDEX_JS": str(INDEX_JS), "TZ": "Asia/Bangkok"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def failed_job(now: datetime, attempt: int = 0) -> dict:
    """Build the job the scheduler saves after a failure."""
    job = {"id": "job-1", "retry_attempt": attempt}
    job.update(scheduler.retry_changes(job, now))
    return job


def test_the_stored_retry_time_is_shown_in_thai_and_english():
    now = datetime(2026, 11, 26, 6, 2, tzinfo=TZ)
    job = failed_job(now)

    assert job["retry_at"] == "2026-11-26T06:07:00+07:00"
    assert render(job, now) == {"th": "จะลองใหม่ 06:07", "en": "Retry at 06:07"}


def test_the_second_retry_shows_its_own_time():
    now = datetime(2026, 11, 26, 6, 2, tzinfo=TZ)
    job = failed_job(now, attempt=1)

    assert job["retry_at"] == "2026-11-26T06:17:00+07:00"
    assert render(job, now) == {"th": "จะลองใหม่ 06:17", "en": "Retry at 06:17"}


def test_a_retry_time_that_has_passed_is_not_shown():
    job = failed_job(datetime(2026, 11, 26, 6, 2, tzinfo=TZ))
    later = datetime(2026, 11, 26, 6, 10, tzinfo=TZ)

    assert render(job, later) == {"th": "", "en": ""}


@pytest.mark.parametrize("value", ["", "   ", "yesterday", None])
def test_a_job_without_a_usable_retry_time_shows_nothing(value):
    now = datetime(2026, 11, 26, 6, 2, tzinfo=TZ)

    assert render({"retry_at": value}, now) == {"th": "", "en": ""}


def test_a_successful_job_shows_no_retry():
    now = datetime(2026, 11, 26, 6, 2, tzinfo=TZ)

    assert render({"retry_at": "", "last_status": "success"}, now) == {"th": "", "en": ""}


def test_switching_language_rebuilds_the_job_list():
    src = INDEX_JS.read_text(encoding="utf-8")
    body = src[src.index("function applyTranslations()") :]
    body = body[: body.index("\nfunction ", 1)]

    assert "renderSchedules(currentSchedules)" in body
