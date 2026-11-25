"""Paths and shared constants for the application.

The project root is resolved from this file, so no value depends on the current
working directory; every other path is derived from it. Only configuration
lives here: locks and mutable run-time state stay with the code that owns them.
"""

import os
import re
from pathlib import Path

from core.env import env_int


LOG_FILE = Path(os.getenv("AI_WEB_LOG_FILE", "logs/app-log.jsonl"))
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))
HISTORY_ROOT = Path(os.getenv("AI_WEB_HISTORY_DIR", "history"))
HISTORY_LOCK_FILE = HISTORY_ROOT / ".history.lock"
SCHEDULE_FILE = Path(os.getenv("AI_WEB_SCHEDULE_FILE", "scheduled-jobs.json"))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.getenv("AI_WEB_ENV_FILE", str(PROJECT_ROOT / ".env")))
CERT_DIR = PROJECT_ROOT / "certs"
# Files for ad-hoc HTTPS: created once and reused so restarts keep the same
# certificate, and kept apart from certs/cert.pem so the certificate mode
# never picks them up by accident.
ADHOC_CERT_FILE = CERT_DIR / "adhoc-cert.pem"
ADHOC_KEY_FILE = CERT_DIR / "adhoc-key.pem"
# Server control from the web UI goes through start_web.sh so the CLI and the
# page use exactly the same start/stop/restart rules.
SERVER_SCRIPT = PROJECT_ROOT / "start_web.sh"
SERVER_CONTROL_LOG = PROJECT_ROOT / "logs" / "server-control.log"
# Each page keeps its template and its CSS/JS together in templates/<page>/.
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
PAGE_ASSETS = {"index", "pair"}
# Page assets change rarely and their URLs carry the file mtime (?v=...), so the
# browser may keep them for a year and skip the revalidation round trip.
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
SKILLS_ROOT = Path(os.getenv("AI_WEB_SKILLS_DIR", "skills"))
# The AI's own working folder: file tools resolve relative paths here and the
# unrestricted shell starts here, so the agent works in one place instead of
# the app's source tree. It is created on start and its files stay out of Git.
WORKSPACE_ROOT = Path(os.getenv("AI_WEB_WORKSPACE_DIR", "workspace"))
# CodeQL's py/path-injection query only honours a startswith() prefix check
# inside the function that performs the file access, so these normalized roots
# are used by the re-checks written next to those accesses.
PROJECT_ROOT_TEXT = os.path.normpath(os.path.realpath(str(PROJECT_ROOT)))
SKILLS_ROOT_TEXT = os.path.normpath(os.path.realpath(str(PROJECT_ROOT / SKILLS_ROOT)))
HISTORY_ROOT_TEXT = os.path.normpath(os.path.realpath(str(HISTORY_ROOT)))
TOOL_MAX_READ_BYTES = 200_000
TOOL_MAX_WRITE_BYTES = 200_000
APPROVAL_TTL_SECONDS = 15 * 60
MAX_PENDING_APPROVALS = 50
APPROVAL_REQUIRED_TOOLS = {"write_file", "run_command", "create_skill", "create_schedule", "update_schedule"}
# With machine access on, every tool can touch the whole host, so every tool
# call is also an approval-required call.
MACHINE_TOOL_NAMES = {"list_files", "read_file", "write_file", "run_command", "create_skill", "create_schedule", "list_schedules", "update_schedule"}
SCHEDULE_LOCK_FILE = Path(f"{SCHEDULE_FILE}.lock")
SCHEDULE_CONTEXT_MESSAGES = 40
PROTECTED_NAMES = {
    ".env",
    ".app-settings.json",
    ".app-auth.json",
    ".app-memory.db",
    ".app-memory.db-wal",
    ".app-memory.db-shm",
    "MEMORY.md",
    "DREAMS.md",
}
PROTECTED_PARTS = {"history", ".venv", ".git", "__pycache__", "certs"}
COMMAND_TIMEOUT_SECONDS = 60
COMMAND_MAX_OUTPUT_BYTES = 100_000
SENSITIVE_ENV_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
# Device pairing: the server generates single-use keys, the client sends a key
# back and receives an HttpOnly cookie for a long-lived, revocable session.
AUTH_FILE = Path(os.getenv("AI_WEB_AUTH_FILE", ".app-auth.json"))
AUTH_ENABLED = os.getenv("AI_WEB_AUTH", "on").strip().lower() not in {"0", "false", "no", "off"}
AUTH_SESSION_COOKIE = "ai-web-session"
# Browsers refuse to let an insecure origin set a cookie whose name matches an
# existing Secure cookie (RFC 6265bis, "Leave Secure Cookies Alone"). Without a
# second name, a device that paired while the app served HTTPS could never pair
# again after switching to HTTP, because its old Secure cookie blocks the new
# one and is not sent over HTTP. Each scheme therefore gets its own name.
AUTH_SESSION_COOKIE_HTTP = "ai-web-session-http"
AUTH_SESSION_COOKIE_NAMES = (AUTH_SESSION_COOKIE, AUTH_SESSION_COOKIE_HTTP)
AUTH_PAIRING_TTL_MINUTES = env_int("AI_WEB_PAIRING_TTL_MINUTES", 30, 1)
AUTH_SESSION_DAYS = env_int("AI_WEB_SESSION_DAYS", 30, 1)
AUTH_KEY_LENGTH = 12
AUTH_KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
AUTH_PAIRING_MAX_FAILURES = 8
AUTH_PAIRING_FAILURE_WINDOW = 300
AUTH_PUBLIC_PATHS = {"/pair", "/api/auth/pair", "/api/auth/status"}
# Styles and scripts must load before the device is paired; they hold no secrets.
AUTH_PUBLIC_PREFIXES = ("/static/", "/templates/")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_TRUST_PROXY = os.getenv("AI_WEB_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}
TOOL_INSTRUCTIONS = """
You have full tool access to this machine: absolute paths and ~/... reach anywhere on the machine, and run_command runs through a real shell (including sudo when the user running the app has permission), starting in the AI workspace folder (workspace/ inside the app folder). In list_files, read_file and write_file a relative path is also resolved inside that workspace, so put the files you create there.
Every tool call pauses and waits for the user to approve it in the chat, and one approval covers a single request. Never assume approval or skip asking for it.
Call format: <tool_call>{"name":"read_file","arguments":{"path":"/etc/hostname"}}</tool_call> or <tool_call>{"name":"list_files","arguments":{"path":"~"}}</tool_call>
Run a shell command: <tool_call>{"name":"run_command","arguments":{"command":"curl -s https://example.org"}}</tool_call> and write a file: <tool_call>{"name":"write_file","arguments":{"path":"notes.md","content":"..."}}</tool_call>
Every call is one JSON object with a "name" and an "arguments" object, and the block must end with </tool_call>. A bare {"command":"..."} is not a tool call.
Use write_file to write files, run_command (the older name execute_command also works) to run commands, and list_files/read_file to explore the machine.
Known API keys and private keys in the results are redacted automatically.
To create or improve a skill, use the create_skill tool; writes are limited to the skills folder. A skill is a folder with this layout (build only the optional folders the skill really needs):
<name>/
  SKILL.md      required: YAML frontmatter (name, description) plus the instructions
  scripts/      optional runnable code
  references/   optional documentation to read on demand
  assets/       optional templates and images
create_skill takes name, description (what the skill does and when to use it), content (the SKILL.md body) and files (optional object of relative path to text, e.g. {"scripts/fetch.py":"...","references/api.md":"...","assets/template.md":"..."}). The tool writes the frontmatter itself, so content starts with a title and includes "## Guidelines / Rules", "## Step-by-Step Workflow" (number the steps and name the scripts/ or references/ file each step needs) and "## Examples" with a correct input and output. Keep SKILL.md short and point at resource files instead of copying long material into it; read those files only when a step needs them.
When the user explicitly asks to create or change a scheduled job/Cron, use create_schedule or update_schedule; create_schedule takes the arguments name, schedule (5-field Cron), prompt, model (optional), enabled (optional) and discord_channel_id (optional, a Discord Channel ID), while update_schedule takes job_id and the fields to change, using the server timezone. Job ids are UUIDs: call list_schedules first to read the real id (with the current prompt, schedule, model, discord_channel_id and enabled flag) instead of guessing one.
""".strip()
TOOL_ALIASES = {"execute_command": "run_command"}
# The assistant turn that only asks for a tool approval is a placeholder for the
# page, not a model answer. It is never replayed to the provider: a small model
# reads its own sentence back and repeats it instead of using the tool result.
APPROVAL_PLACEHOLDER = "The AI requested a tool that needs approval first"
TOOL_CALL_BLOCK_PATTERN = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)
# A reply that was meant to be a tool call but cannot be parsed is retried once
# with this instruction, instead of being shown to the user as raw JSON.
TOOL_CALL_REPAIR_INSTRUCTION = (
    "Your previous reply was meant to be a tool call, but it could not be read: "
    "the block must be one complete JSON object with a \"name\" and an \"arguments\" object, "
    "and it must end with </tool_call>, like "
    "<tool_call>{\"name\":\"run_command\",\"arguments\":{\"command\":\"curl -s https://example.org\"}}</tool_call>. "
    "Send the same request again as exactly one corrected tool call and nothing else."
)
# Defaults for the background memory engine. They live here so core.settings can
# build its defaults without importing memory_engine, which imports core.log.
DEFAULT_MEMORY_SETTINGS = {
    "enabled": True,
    "schedule": "0 3 * * *",
    "lookback_days": 7,
    "threshold": 0.65,
    "idle_minutes": 15,
    "max_items": 25,
    "include_locked": False,
    "llm": True,
    "provider": "",
    "model": "",
    "base_url": "",
    "window_end": "06:00",
    "dedupe": 0.92,
    "retrieval": True,
    "retrieval_items": 4,
    "retrieval_chars": 800,
    "max_entries": 200,
}
