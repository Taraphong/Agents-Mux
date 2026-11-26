/*
 * Behaviour checks for the conversation title in the chat page.
 *
 * The real functions are read out of templates/index/index.js and run against a
 * tiny DOM/fetch stub, so the checks cover the shipped code: a generated title
 * is PATCHed onto the new conversation, and when the summary request fails the
 * first message stays the title (no rename, no error notice).
 *
 * Run by tests/test_title_fallback.py; prints one JSON summary line.
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

const nodes = new Map();
function $(id) {
  if (!nodes.has(id)) nodes.set(id, { id, value: "", textContent: "", title: "" });
  return nodes.get(id);
}

const doc = {
  querySelector: (selector) =>
    selector === "nav button.active" ? { dataset: { view: "chat" } } : null,
};

let scenario = "success";
const calls = [];

async function fetchStub(url, options = {}) {
  const method = options.method || "GET";
  calls.push({
    url,
    method,
    body: options.body ? JSON.parse(options.body) : null,
  });
  if (url === "/api/history/title") {
    if (scenario === "title-failed") {
      return { ok: false, status: 502, json: async () => ({ error: "summarise failed" }) };
    }
    if (scenario === "network-error") throw new Error("offline");
    return { ok: true, status: 200, json: async () => ({ title: "  หัวข้อจากโมเดล  " }) };
  }
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
}

const body = `
let conversationId = "conv-1";
let conversationTitle = null;
let currentLanguage = "th";
let historyReloads = 0;
async function loadHistoryList() {
  historyReloads += 1;
}
${extract("activeView")}
${extract("updatePageTitle")}
${extract("normalizeConversationTitle")}
${extract("setConversationTitle")}
${extract("requestGeneratedTitle")}
${extract("applyGeneratedTitle")}
return {
  requestGeneratedTitle,
  applyGeneratedTitle,
  setConversationTitle,
  title: () => conversationTitle,
  reloads: () => historyReloads,
};
`;

const api = new Function("$", "document", "fetch", body)($, doc, fetchStub);

const FIRST_MESSAGE = "ช่วยอธิบายสั้น ๆ ว่า Docker คืออะไร";

(async () => {
  $("chat-model-select").value = "gemini-3.5-flash-lite";

  // 1. Success: the generated title is PATCHed onto the saved conversation.
  const generated = await api.requestGeneratedTitle(FIRST_MESSAGE);
  equal(generated, "หัวข้อจากโมเดล", "the reply is trimmed into a title");
  equal(
    calls[0].body,
    { question: FIRST_MESSAGE, model: "gemini-3.5-flash-lite", lang: "th" },
    "the summary request carries the question, the chat model and the language",
  );
  api.setConversationTitle(FIRST_MESSAGE);
  await api.applyGeneratedTitle(Promise.resolve(generated), "conv-1", FIRST_MESSAGE);
  const patch = calls.find((call) => call.method === "PATCH");
  assert(patch, "the generated title is stored with a PATCH");
  equal(patch.url, "/api/history/conv-1", "the PATCH targets the new conversation");
  equal(patch.body.title, "หัวข้อจากโมเดล", "the PATCH sends the generated title");
  equal(api.title(), "หัวข้อจากโมเดล", "the page shows the generated title");
  equal(api.reloads(), 1, "the history list is reloaded after the rename");

  // 2. A 502 from the summary keeps the first message as the title.
  scenario = "title-failed";
  api.setConversationTitle(FIRST_MESSAGE);
  const before = calls.filter((call) => call.method === "PATCH").length;
  const failed = api.requestGeneratedTitle(FIRST_MESSAGE);
  equal(await failed, null, "a failed summary yields no title");
  await api.applyGeneratedTitle(failed, "conv-1", FIRST_MESSAGE);
  equal(api.title(), FIRST_MESSAGE, "the first message stays the title");
  equal(
    calls.filter((call) => call.method === "PATCH").length,
    before,
    "a failed summary renames nothing",
  );
  equal(api.reloads(), 1, "a failed summary leaves the history list alone");

  // 3. A dropped connection behaves the same way.
  scenario = "network-error";
  api.setConversationTitle(FIRST_MESSAGE);
  const offline = api.requestGeneratedTitle(FIRST_MESSAGE);
  equal(await offline, null, "a network error yields no title");
  await api.applyGeneratedTitle(offline, "conv-1", FIRST_MESSAGE);
  equal(api.title(), FIRST_MESSAGE, "the first message survives a network error");
  equal(
    calls.filter((call) => call.method === "PATCH").length,
    before,
    "a network error renames nothing",
  );

  console.log(JSON.stringify({ ok: true, requests: calls.length }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message }));
  process.exitCode = 1;
});
