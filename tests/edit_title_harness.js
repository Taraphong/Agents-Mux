/*
 * Behaviour checks for the conversation title after the first question is
 * edited.
 *
 * The real functions are read out of templates/index/index.js and run against a
 * tiny DOM/fetch stub, so the checks cover the shipped code: the edited
 * question is summarised with the same endpoint a new chat uses and the result
 * renames the conversation, a failed summary falls back to the edited question,
 * and a manual rename made while the summary runs is not overwritten.
 *
 * Run by tests/test_edit_title.py; prints one JSON summary line.
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
    return { ok: true, status: 200, json: async () => ({ title: "  หัวข้อจากคำถามที่แก้ไข  " }) };
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
${extract("refreshTitleAfterPromptEdit")}
return {
  refreshTitleAfterPromptEdit,
  setConversationTitle,
  title: () => conversationTitle,
  reloads: () => historyReloads,
};
`;

const api = new Function("$", "document", "fetch", body)($, doc, fetchStub);

const OLD_TITLE = "พิมพ์คำนี้กลับมาเท่านั้น: ALPHA-1111";
const EDITED_PROMPT = "พิมพ์คำนี้กลับมาเท่านั้น: BETA-2222";
const patches = () => calls.filter((call) => call.method === "PATCH");

(async () => {
  $("chat-model-select").value = "gemini-3.5-flash-lite";

  // 1. The edited question is summarised and the summary renames the same chat.
  api.setConversationTitle(OLD_TITLE);
  await api.refreshTitleAfterPromptEdit("conv-1", EDITED_PROMPT, OLD_TITLE);
  const summaryCall = calls.find((call) => call.url === "/api/history/title");
  equal(
    summaryCall.body,
    { question: EDITED_PROMPT, model: "gemini-3.5-flash-lite", lang: "th" },
    "the summary request carries the edited question",
  );
  equal(patches().length, 1, "one rename is stored");
  equal(patches()[0].url, "/api/history/conv-1", "the rename targets the same chat");
  equal(patches()[0].body.title, "หัวข้อจากคำถามที่แก้ไข", "the summary becomes the title");
  equal(api.title(), "หัวข้อจากคำถามที่แก้ไข", "the sidebar shows the new title");
  equal(api.reloads(), 1, "the history list is reloaded after the rename");

  // 2. A failed summary falls back to the edited question, never the old title.
  scenario = "title-failed";
  api.setConversationTitle(OLD_TITLE);
  const before = patches().length;
  await api.refreshTitleAfterPromptEdit("conv-1", EDITED_PROMPT, OLD_TITLE);
  equal(patches().length, before + 1, "the fallback rename is stored");
  equal(patches()[before].body.title, EDITED_PROMPT, "the edited question names the chat");
  equal(api.title(), EDITED_PROMPT, "the old question no longer names the chat");

  // 3. A dropped connection behaves the same way.
  scenario = "network-error";
  api.setConversationTitle(OLD_TITLE);
  const beforeOffline = patches().length;
  await api.refreshTitleAfterPromptEdit("conv-1", EDITED_PROMPT, OLD_TITLE);
  equal(patches().length, beforeOffline + 1, "the offline fallback still renames");
  equal(patches()[beforeOffline].body.title, EDITED_PROMPT, "the edited question is used");

  // 4. A manual rename made while the summary runs wins.
  scenario = "success";
  api.setConversationTitle("ชื่อที่ผู้ใช้เปลี่ยนเอง");
  const beforeManual = patches().length;
  await api.refreshTitleAfterPromptEdit("conv-1", EDITED_PROMPT, OLD_TITLE);
  equal(patches().length, beforeManual, "a manual rename is not overwritten");
  equal(api.title(), "ชื่อที่ผู้ใช้เปลี่ยนเอง", "the manual title stays");

  // 5. An unsaved chat has nothing to rename.
  const none = api.refreshTitleAfterPromptEdit(null, EDITED_PROMPT, OLD_TITLE);
  equal(none, null, "no conversation means no rename request");

  console.log(JSON.stringify({ ok: true, requests: calls.length, patches: patches().length }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message }));
  process.exitCode = 1;
});
