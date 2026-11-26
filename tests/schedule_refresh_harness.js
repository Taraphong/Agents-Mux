/*
 * Behaviour checks for the periodic refresh of the scheduled-jobs list.
 *
 * The real functions are read out of templates/index/index.js and run against a
 * tiny DOM/fetch stub, so the checks cover the shipped code: the list repaints
 * only when the shown fields change, the edit form keeps its typed values, the
 * timer only polls on the Scheduled jobs view of a visible tab, and a quiet
 * refresh never raises a notice.
 *
 * Run by tests/test_schedule_refresh.py; prints one JSON summary line.
 */

const fs = require("fs");
const path = require("path");

const SOURCE = path.join(__dirname, "..", "templates", "index", "index.js");
const src = fs.readFileSync(SOURCE, "utf8");

function extract(name) {
  const marker = `function ${name}(`;
  const at = src.indexOf(marker);
  if (at < 0) throw new Error(`function ${name} not found in index.js`);
  // Keep the async keyword, and skip the parameter list (a default such as
  // `options = {}` would otherwise be mistaken for the body).
  const start = src.slice(at - 6, at) === "async " ? at - 6 : at;
  let depth = 0;
  let cursor = at + marker.length - 1;
  for (; cursor < src.length; cursor += 1) {
    if (src[cursor] === "(") depth += 1;
    else if (src[cursor] === ")") {
      depth -= 1;
      if (depth === 0) {
        cursor += 1;
        break;
      }
    }
  }
  const bodyStart = src.indexOf("{", cursor);
  depth = 0;
  for (let i = bodyStart; i < src.length; i += 1) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") {
      depth -= 1;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error(`function ${name} is not closed`);
}

// The real Thai dictionary, so the retry label is the text users see.
const dictStart = src.indexOf("const I18N = {");
const dictEnd = src.indexOf("\n};", dictStart);
const dictCtx = {};
require("vm").createContext(dictCtx);
require("vm").runInContext(
  `var X = ${src.slice(src.indexOf("{", dictStart), dictEnd + 2)};`,
  dictCtx,
);
const DICT = dictCtx.X;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function equal(actual, expected, message) {
  assert(
    JSON.stringify(actual) === JSON.stringify(expected),
    `${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
  );
}

/* ---- stubs for the browser the page normally runs in ---- */

let renderCount = 0;
const nodes = new Map();

function makeNode(id) {
  const node = { id, value: "", textContent: "", hidden: false, checked: false };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html,
    set: (value) => {
      html = value;
      if (id === "schedule-list") renderCount += 1;
    },
  });
  return node;
}

function $(id) {
  if (!nodes.has(id)) nodes.set(id, makeNode(id));
  return nodes.get(id);
}

const page = { view: "schedule", hidden: false };
const doc = {
  get hidden() {
    return page.hidden;
  },
  querySelector: (selector) =>
    selector === "nav button.active" ? { dataset: { view: page.view } } : null,
  addEventListener: () => {},
};

const net = { calls: 0, payload: [], fail: false };
async function fetchStub() {
  net.calls += 1;
  if (net.fail) throw new Error("network down");
  return {
    ok: true,
    json: async () => ({
      items: JSON.parse(JSON.stringify(net.payload)),
      timezone: "ICT",
    }),
  };
}

function t(key, vars = {}) {
  let text = DICT.th[key] != null ? DICT.th[key] : key;
  for (const [name, value] of Object.entries(vars)) {
    text = text.split(`{${name}}`).join(value);
  }
  return text;
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
}

const notices = [];
function showNotice(message, error = false) {
  notices.push({ message, error });
}

const timers = { callback: null, interval: 0, nextId: 1, cleared: [] };
function setIntervalStub(callback, interval) {
  timers.callback = callback;
  timers.interval = interval;
  const id = timers.nextId;
  timers.nextId += 1;
  return id;
}
function clearIntervalStub(id) {
  timers.cleared.push(id);
}

const body = `
let currentSchedules = [];
let currentScheduleTimezone = "";
let scheduleListSignature = "";
let scheduleLoadInFlight = false;
let scheduleRefreshTimer = null;
const SCHEDULE_REFRESH_MS = 20000;
${extract("activeView")}
${extract("schedulesSignature")}
${extract("renderSchedulesIfChanged")}
${extract("loadSchedules")}
${extract("stopScheduleRefresh")}
${extract("startScheduleRefresh")}
${extract("renderSchedules")}
${extract("scheduleStatusText")}
${extract("scheduleRetryText")}
return { loadSchedules, startScheduleRefresh, stopScheduleRefresh };
`;

const api = new Function(
  "$",
  "document",
  "fetch",
  "t",
  "escapeHtml",
  "showNotice",
  "setInterval",
  "clearInterval",
  "Date",
  body,
)(
  $,
  doc,
  fetchStub,
  t,
  escapeHtml,
  showNotice,
  setIntervalStub,
  clearIntervalStub,
  Date,
);

/* ---- checks ---- */

function clock(offsetMs) {
  const moment = new Date(Date.now() + offsetMs);
  const pad = (value) => String(value).padStart(2, "0");
  return {
    iso: `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(
      moment.getDate(),
    )}T${pad(moment.getHours())}:${pad(moment.getMinutes())}:${pad(
      moment.getSeconds(),
    )}${moment.getTimezoneOffset() > 0 ? "-" : "+"}${pad(
      Math.floor(Math.abs(moment.getTimezoneOffset()) / 60),
    )}:${pad(Math.abs(moment.getTimezoneOffset()) % 60)}`,
    label: `${pad(moment.getHours())}:${pad(moment.getMinutes())}`,
  };
}

function job(retryAt) {
  return {
    id: "job-1",
    name: "Weather_MSU",
    schedule: "0 6 * * *",
    prompt: "รายงานสภาพอากาศ",
    model: "",
    discord_channel_id: "",
    enabled: true,
    last_status: "failed",
    last_error: "HTTPError",
    last_run_at: "2026-11-26T06:02:44+07:00",
    last_run_key: "2026-11-26 06:00",
    retry_at: retryAt,
  };
}

(async () => {
  const first = clock(5 * 60 * 1000);
  const later = clock(20 * 60 * 1000);

  // 1. The first load paints the list with the stored retry time.
  net.payload = [job(first.iso)];
  await api.loadSchedules();
  equal(renderCount, 1, "first load paints the list once");
  assert(
    $("schedule-list").innerHTML.includes(`จะลองใหม่ ${first.label}`),
    `the retry label is missing: ${$("schedule-list").innerHTML}`,
  );

  // 2. The same payload must not repaint: no flash on every poll.
  await api.loadSchedules();
  equal(renderCount, 1, "an unchanged payload does not repaint the list");

  // 3. An edit in progress survives a refresh, and a changed retry time shows.
  $("schedule-name").value = "ชื่องานที่กำลังแก้";
  $("schedule-prompt").value = "prompt ที่พิมพ์ค้างไว้";
  $("schedule-expression").value = "30 7 * * *";
  net.payload = [job(later.iso)];
  await api.loadSchedules();
  equal(renderCount, 2, "a changed retry time repaints the list");
  assert(
    $("schedule-list").innerHTML.includes(`จะลองใหม่ ${later.label}`),
    "the list still shows the old retry time",
  );
  equal($("schedule-name").value, "ชื่องานที่กำลังแก้", "the name field is kept");
  equal(
    $("schedule-prompt").value,
    "prompt ที่พิมพ์ค้างไว้",
    "the prompt field is kept",
  );
  equal(
    $("schedule-expression").value,
    "30 7 * * *",
    "the cron field is kept",
  );

  // 4. The timer polls only on the Scheduled jobs view of a visible tab.
  api.startScheduleRefresh();
  equal(timers.interval, 20000, "the refresh interval is 20 seconds");
  const before = net.calls;
  timers.callback();
  await new Promise((resolve) => setImmediate(resolve));
  equal(net.calls, before + 1, "the timer polls while the view is open");
  equal(renderCount, 2, "a poll with the same payload does not repaint");

  page.view = "chat";
  timers.callback();
  await new Promise((resolve) => setImmediate(resolve));
  equal(net.calls, before + 1, "another view does not poll");

  page.view = "schedule";
  page.hidden = true;
  timers.callback();
  await new Promise((resolve) => setImmediate(resolve));
  equal(net.calls, before + 1, "a hidden tab does not poll");
  page.hidden = false;

  // 5. Starting the timer again replaces the previous one.
  api.startScheduleRefresh();
  equal(timers.cleared.length, 1, "a second start clears the first timer");
  api.stopScheduleRefresh();
  equal(timers.cleared.length, 2, "leaving the view clears the timer");

  // 6. A quiet refresh stays silent on failure; a page load reports it.
  net.fail = true;
  await api.loadSchedules({ quiet: true });
  equal(notices.length, 0, "a quiet refresh shows no notice");
  await api.loadSchedules();
  equal(notices.length, 1, "a normal load reports the failure");

  console.log(JSON.stringify({ ok: true, renders: renderCount }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message }));
  process.exitCode = 1;
});
