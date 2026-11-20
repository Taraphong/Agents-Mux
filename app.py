import os
import asyncio
import base64
import fcntl
import gzip
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import shlex
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from collections import deque

import requests
import memory_engine
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import (
    ThreadedWSGIServer,
    WSGIRequestHandler,
    load_ssl_context,
)

load_dotenv()


def env_int(name: str, default: int, minimum: int) -> int:
    """Read an integer environment variable, clamping invalid input to safe bounds."""
    try:
        value = int(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


app = Flask(__name__)
# The in-memory log is a rolling window: a server that runs for weeks on Termux
# must not keep every event in RAM, so only the newest entries are retained.
APP_LOGS: deque[dict[str, Any]] = deque(maxlen=env_int("AI_WEB_LOG_MAX_ENTRIES", 1000, 50))
# Reject oversized bodies before they reach the JSON parser or the history writer.
app.config["MAX_CONTENT_LENGTH"] = env_int("AI_WEB_MAX_CONTENT_BYTES", 8 * 1024 * 1024, 64 * 1024)
APP_LOG_LOCK = threading.Lock()
LOGGER = logging.getLogger("ai-web")
LOG_FILE = Path(os.getenv("AI_WEB_LOG_FILE", "logs/app-log.jsonl"))
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))
HISTORY_ROOT = Path(os.getenv("AI_WEB_HISTORY_DIR", "history"))
HISTORY_LOCK_FILE = HISTORY_ROOT / ".history.lock"
SCHEDULE_FILE = Path(os.getenv("AI_WEB_SCHEDULE_FILE", "scheduled-jobs.json"))
SCHEDULE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent
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
APP_STARTED_AT = time.time()
SERVER_JOB: dict[str, Any] = {"process": None, "action": "", "started_at": ""}
SERVER_JOB_LOCK = threading.Lock()
# Each page keeps its template and its CSS/JS together in templates/<page>/.
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
PAGE_ASSETS = {"index", "pair"}
# Text responses are gzipped when the client asks for it: the phone serves this
# page over a slow Wi-Fi link, so 291 KB of HTML/CSS/JS must not go out raw.
GZIP_MIMETYPES = {"text/html", "text/css", "application/javascript", "text/javascript"}
GZIP_MIN_BYTES = 1024
# Page assets change rarely and their URLs carry the file mtime (?v=...), so the
# browser may keep them for a year and skip the revalidation round trip.
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
ASSET_GZIP_CACHE: dict[tuple[str, int, int], bytes] = {}
ASSET_GZIP_LOCK = threading.Lock()
ASSET_GZIP_CACHE_LIMIT = 8
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
PENDING_TOOL_REQUESTS: dict[str, dict[str, Any]] = {}
PENDING_APPROVAL_LOCK = threading.Lock()
APPROVAL_TTL_SECONDS = 15 * 60
MAX_PENDING_APPROVALS = 50
APPROVAL_REQUIRED_TOOLS = {"write_file", "run_command", "create_skill", "create_schedule", "update_schedule"}
# With machine access on, every tool can touch the whole host, so every tool
# call is also an approval-required call.
MACHINE_TOOL_NAMES = {"list_files", "read_file", "write_file", "run_command", "create_skill", "create_schedule", "update_schedule"}
SCHEDULE_LOCK_FILE = Path(f"{SCHEDULE_FILE}.lock")
SCHEDULE_CONTEXT_MESSAGES = 40
SCHEDULE_RUNNING: set[str] = set()
SCHEDULE_RUNNING_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_START_LOCK = threading.Lock()
_SCHEDULER_LOCK_HANDLE: Any = None
PROTECTED_NAMES = {".env", ".app-settings.json", ".app-auth.json", ".app-memory.db"}
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
AUTH_LOCK = threading.Lock()
AUTH_PAIRING_FAILURES: dict[str, list[float]] = {}
AUTH_PAIRING_MAX_FAILURES = 8
AUTH_PAIRING_FAILURE_WINDOW = 300
AUTH_PUBLIC_PATHS = {"/pair", "/api/auth/pair", "/api/auth/status"}
# Styles and scripts must load before the device is paired; they hold no secrets.
AUTH_PUBLIC_PREFIXES = ("/static/", "/templates/")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_TRUST_PROXY = os.getenv("AI_WEB_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}

if AUTH_TRUST_PROXY:
    # Honour X-Forwarded-Proto/Host when TLS terminates at a reverse proxy so
    # request.is_secure (and the Secure session cookie) reflects the client.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
TOOL_INSTRUCTIONS = """
You have full tool access to this machine: absolute paths and ~/... reach anywhere on the machine, and run_command runs through a real shell (including sudo when the user running the app has permission), starting in the AI workspace folder (workspace/ inside the app folder). In list_files, read_file and write_file a relative path is also resolved inside that workspace, so put the files you create there.
Every tool call pauses and waits for the user to approve it in the chat, and one approval covers a single request. Never assume approval or skip asking for it.
Call format: <tool_call>{"name":"read_file","arguments":{"path":"/etc/hostname"}}</tool_call> or <tool_call>{"name":"list_files","arguments":{"path":"~"}}</tool_call>
Use write_file to write files, run_command (the older name execute_command also works) to run commands, and list_files/read_file to explore the machine.
Known API keys and private keys in the results are redacted automatically.
To create or improve a skill, use the create_skill tool with a .md file name and clear skill content; writes are limited to the skills folder.
When the user explicitly asks to create or change a scheduled job/Cron, use create_schedule or update_schedule; create_schedule takes the arguments name, schedule (5-field Cron), prompt, model (optional), enabled (optional) and discord_channel_id (optional, a Discord Channel ID), while update_schedule takes job_id and the fields to change, using the server timezone.
""".strip()

TOOL_ALIASES = {"execute_command": "run_command"}
TOOL_CALL_BLOCK_PATTERN = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)


def load_persisted_logs() -> None:
    """Restore the append-only diagnostic trail after a server restart."""
    if not LOG_FILE.exists():
        return
    try:
        with LOG_FILE.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    APP_LOGS.append(record)
    except OSError as exc:
        LOGGER.warning("Could not read the persisted log file: %s", exc)


def skill_dir(name: str) -> Path:
    """Resolve a skill name to its directory inside the skills root."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name).strip().lower()).strip("-")
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Invalid skill name")
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    directory = normalized_path_under(safe_name, root, "Skill name is outside the allowed folder")
    if directory.parent != root:
        raise ValueError("Skill name is outside the allowed folder")
    return directory


def skill_path(name: str) -> Path:
    """Return the canonical Agent Skills entrypoint: <skill>/SKILL.md."""
    return skill_dir(name) / "SKILL.md"


def list_skills() -> list[dict[str, str]]:
    """Load every skill folder that contains a SKILL.md entrypoint."""
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    if not root.exists():
        return []
    items = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        path = directory / "SKILL.md"
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")[:20_000]
        except OSError:
            continue
        items.append({"name": directory.name, "content": content})
    return items


def selected_skill_prompt(settings: dict[str, Any]) -> str:
    """Build the skill guidance block for the skills selected in settings."""
    selected = settings.get("skills", [])
    if not isinstance(selected, list):
        return ""
    by_name = {item["name"]: item["content"] for item in list_skills()}
    blocks = [f"## Skill: {name}\n{by_name[name]}" for name in selected if name in by_name]
    return "Guidance from the selected Skills:\n\n" + "\n\n".join(blocks) if blocks else ""


def log_event(event: str, message: str, **details: Any) -> None:
    """Append a UI-readable diagnostic record without storing secrets."""
    safe_details = {}
    for key, value in details.items():
        if key.lower() in {"api_key", "authorization", "token", "content"}:
            continue
        safe_details[key] = redact_secrets(str(value))[:500]
    record = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": str(event)[:60],
        "message": redact_secrets(str(message))[:500],
        "details": safe_details,
    }
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with APP_LOG_LOCK:
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(serialized)
            APP_LOGS.append(record)
    except OSError as exc:
        LOGGER.warning("Could not write the persisted log: %s", exc)
        with APP_LOG_LOCK:
            APP_LOGS.append(record)
    # Only the event name reaches the plain-text console log. The message and its
    # details stay in APP_LOGS/log file below, where redact_secrets has run, so a
    # credential can never be written here as clear text.
    LOGGER.info("%s", event)


load_persisted_logs()

DEFAULT_SETTINGS = {
    "memory": memory_engine.DEFAULT_MEMORY_SETTINGS.copy(),
    "agent_name": "Mux",
    "agent_role": "A versatile AI assistant",
    "response_language": "auto",
    "response_style": "Friendly, concise, and clear",
    "use_markdown": True,
    "ask_clarifying_questions": True,
    "provider": os.getenv("AI_PROVIDER", "openai"),
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "base_url": os.getenv("AI_BASE_URL", ""),
    "system_prompt": "You are a polite, clear AI assistant who helps the user achieve their goals.",
    "memory_review": (
        "Before answering, review the earlier conversation to keep continuity, check facts and "
        "outstanding tasks, and ask the user when information conflicts. Do not reveal internal reasoning."
    ),
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 1,
    "stream": False,
    "thinking_level": "off",
    "command_mode": "ask",
    "fallback_enabled": False,
    "fallback_provider": os.getenv("AI_FALLBACK_PROVIDER", "openai"),
    "fallback_model": os.getenv("AI_FALLBACK_MODEL", ""),
    "gemini_live_model": os.getenv("GEMINI_LIVE_MODEL", ""),
    "gemini_agent": os.getenv("GEMINI_AGENT", ""),
    "gemini_decision_model": os.getenv("GEMINI_DECISION_MODEL", ""),
    "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN", "").strip()),
    "discord_prefix": os.getenv("DISCORD_BOT_PREFIX", "!ai"),
    "discord_allowed_users": [
        item.strip() for item in os.getenv("DISCORD_ALLOWED_USER_IDS", "").split(",") if item.strip()
    ],
    "discord_allowed_channels": [
        item.strip() for item in os.getenv("DISCORD_ALLOWED_CHANNEL_IDS", "").split(",") if item.strip()
    ],
    "machine_access": True,
    "custom_api_keys": {},
}

FALLBACK_MODELS = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini", "o3"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
    "hf": ["meta-llama/Llama-3.1-8B-Instruct", "mistralai/Mistral-7B-Instruct"],
    "or": ["openai/gpt-3.5-turbo", "anthropic/claude-3-haiku-20240307"],
    "groq": ["mixtral-8x7b-32768", "gemma-7b-it"],
}

PROVIDERS = ("openai", "gemini", "anthropic", "hf", "or", "groq")
PROVIDER_LABELS = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic", "hf": "Hugging Face", "or": "OpenRouter", "groq": "Groq"}
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "hf": "HF_API_KEY",
    "or": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
}

PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "anthropic": "https://api.anthropic.com/v1",
    "hf": "https://router.huggingface.co/v1",
    "or": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}
STATUS_CACHE_TTL = 300
# Each entry keeps the checked key so a result is only reused for the same key;
# the key stays in memory, where the loaded settings already hold it.
STATUS_CACHE: dict[str, tuple[float, str, dict[str, Any]]] = {}

# Gemini exposes several feature groups behind one API key. The capability
# report below groups the models the key can actually reach, so the UI can say
# what is available instead of guessing from the key alone.
GEMINI_DECISION_MODEL = "gemini-decision-1"
GEMINI_DEFAULT_AGENT = "antigravity-preview-09-2026"
GEMINI_LIVE_FALLBACK_MODEL = "gemini-2.0-flash-live-001"
GEMINI_AGENT_PRESETS = (GEMINI_DEFAULT_AGENT, "deep-research")
GEMINI_CAPABILITY_CACHE_TTL = 300
# Each entry keeps the checked key beside the report, so a result is only reused
# for the same key without deriving an identifier from the secret itself.
GEMINI_CAPABILITY_CACHE: dict[str, tuple[float, str, dict[str, Any]]] = {}
GEMINI_CAPABILITY_PROBE = 0
GEMINI_CAPABILITY_LOCK = threading.Lock()
# Inline multimodal parts travel in the JSON body, so a single attachment is
# capped well below the provider limits and checked before it is forwarded.
MULTIMODAL_MAX_BYTES = 6 * 1024 * 1024
MULTIMODAL_MIME_TYPES = {"application/pdf"}
MULTIMODAL_MIME_PREFIXES = ("image/", "audio/", "video/")

DISCORD_CONTEXTS: dict[str, deque[dict[str, str]]] = {}
DISCORD_CONVERSATION_IDS: dict[str, str] = {}
DISCORD_CONTEXT_LOCK = threading.Lock()
DISCORD_BOT: Any = None
DISCORD_THREAD: threading.Thread | None = None
DISCORD_LOOP: Any = None
DISCORD_ACTIVE_TOKEN = ""
SETTINGS_LOCK = threading.Lock()


def normalize_provider(value: Any) -> str:
    """Clamp an unknown provider name to a supported provider id."""
    provider = str(value or "openai").strip().lower()
    return provider if provider in PROVIDERS else "openai"


def parse_discord_ids(value: Any, limit: int = 100) -> tuple[list[str], list[str]]:
    """Split a Discord allowlist input into unique numeric IDs and bad entries.

    Accepts a comma/space separated string or a list, because the settings API
    accepts both the web form input and a JSON array. Invalid entries are
    reported instead of dropped so a typo cannot silently empty the allowlist.
    """
    if isinstance(value, str):
        raw_items: list[Any] = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    ids: list[str] = []
    invalid: list[str] = []
    for item in raw_items:
        item = str(item).strip()
        if not item:
            continue
        if not item.isdigit():
            invalid.append(item[:40])
            continue
        if item not in ids and len(ids) < limit:
            ids.append(item)
    return ids, invalid


def normalize_discord_ids(value: Any, limit: int = 100) -> list[str]:
    """Normalize a stored Discord allowlist into unique numeric IDs."""
    return parse_discord_ids(value, limit)[0]


def discord_access_allowed(settings: dict[str, Any], channel_id: Any, user_id: Any) -> bool:
    """Return whether a Discord channel/user pair passes the allowlists.

    An empty allowlist means "no restriction", so existing installs keep
    working after the upgrade.
    """
    allowed_channels = normalize_discord_ids(settings.get("discord_allowed_channels"))
    allowed_users = normalize_discord_ids(settings.get("discord_allowed_users"))
    if allowed_channels and str(channel_id) not in allowed_channels:
        return False
    if allowed_users and str(user_id) not in allowed_users:
        return False
    return True


def stored_api_keys(settings: dict[str, Any]) -> dict[str, str]:
    """Return the per-provider API key map from settings."""
    raw = settings.get("api_keys")
    keys = raw if isinstance(raw, dict) else {}
    return {provider: str(keys.get(provider) or "").strip() for provider in PROVIDERS}


CUSTOM_KEY_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def normalize_custom_key_name(value: Any) -> str:
    """Validate a user-chosen name for an extra API key (used as an env var)."""
    name = re.sub(r"[\s-]+", "_", str(value or "").strip()).upper()
    if not CUSTOM_KEY_NAME_PATTERN.fullmatch(name):
        raise ValueError("The key name must start with A-Z and use only A-Z, 0-9 and _ (64 characters max)")
    return name


def stored_custom_api_keys(settings: dict[str, Any]) -> dict[str, str]:
    """Return the extra named API keys, dropping invalid or empty entries."""
    raw = settings.get("custom_api_keys")
    if not isinstance(raw, dict):
        return {}
    keys: dict[str, str] = {}
    for name, value in raw.items():
        try:
            valid_name = normalize_custom_key_name(name)
        except ValueError:
            continue
        text = str(value or "").strip()
        if text:
            keys[valid_name] = text
    return keys


def migrate_legacy_api_key(settings: dict[str, Any]) -> dict[str, Any]:
    """Move the old single api_key slot into the per-provider map, once."""
    if "api_keys" in settings:
        settings.pop("api_key", None)
        return settings
    legacy = str(settings.get("api_key") or "").strip()
    settings.pop("api_key", None)
    settings["api_keys"] = {}
    if legacy:
        settings["api_keys"][normalize_provider(settings.get("provider"))] = legacy
        try:
            save_settings(settings)
        except OSError:
            pass
    return settings


def load_settings() -> dict[str, Any]:
    """Load settings from disk, falling back to defaults on error."""
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    settings = migrate_legacy_api_key(settings)
    settings.pop("terminal_enabled", None)
    settings["custom_api_keys"] = stored_custom_api_keys(settings)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """Write the current settings atomically so readers never see a partial file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = SETTINGS_FILE.with_name(f".{SETTINGS_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        payload = json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8")
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temp_path, SETTINGS_FILE)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    # A changed API key or base URL can change the model list, so drop the cached
    # ids Discord autocomplete answers from.
    forget_model_names()


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


def execute_schedule(job: dict[str, Any]) -> None:
    """Run one scheduled job, store its answer, and record the outcome."""
    try:
        settings = load_settings()
        if job.get("model"):
            settings["model"] = job["model"]
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
            ) if part
        )
        conversation_id = schedule_conversation_id(job)
        record = load_history_record(conversation_id)
        previous_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        context_messages = [
            message for message in previous_messages
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        ][-SCHEDULE_CONTEXT_MESSAGES:]
        prompt_message = {"role": "user", "content": job["prompt"], "schedule_id": job["id"]}
        messages = clean_messages(context_messages + [prompt_message], settings)
        started_at = time.perf_counter()
        answer, usage = call_provider(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        save_history({
            "id": conversation_id,
            "title": record.get("title") or f"⏰ {job['name']}",
            "created_at": record.get("created_at"),
            "base_message_count": len(previous_messages),
            "messages": [
                *previous_messages,
                prompt_message,
                {"role": "assistant", "content": answer, "duration_ms": duration_ms, "usage": usage, "schedule_id": job["id"]},
            ],
        })
        try:
            send_discord_schedule_result(job, answer)
        except Exception as exc:
            # The answer is already saved in history, so a Discord delivery
            # problem must not mark the AI run itself as failed.
            log_event("schedule.discord_error", f"Could not send scheduled job {job['name']} to Discord", job=job["id"], error=str(exc))
        update_schedule(job["id"], last_status="success", last_error="", last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        log_event("schedule.success", f"Scheduled job {job['name']} succeeded", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        log_event("schedule.error", f"Scheduled job {job.get('name', job.get('id', ''))} failed", error=str(exc))
        update_schedule(job["id"], last_status="failed", last_error=redact_secrets(str(exc))[:500], last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    finally:
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id:
            with SCHEDULE_RUNNING_LOCK:
                SCHEDULE_RUNNING.discard(job_id)


def schedule_loop() -> None:
    """Check due jobs every 15 seconds and dispatch them in threads."""
    last_minute = ""
    while True:
        now = datetime.now().astimezone()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key != last_minute:
            last_minute = minute_key
            try:
                for job in load_schedules():
                    if not job.get("enabled", True) or job.get("last_run_key") == minute_key:
                        continue
                    try:
                        if not cron_matches(job["schedule"], now):
                            continue
                        job_id = job["id"]
                        with SCHEDULE_RUNNING_LOCK:
                            if job_id in SCHEDULE_RUNNING:
                                log_event("schedule.skipped", "Skipped a job that is still running", job=job_id)
                                continue
                            SCHEDULE_RUNNING.add(job_id)
                        try:
                            update_schedule(job_id, last_run_key=minute_key)
                            threading.Thread(target=execute_schedule, args=(job,), daemon=True).start()
                        except Exception:
                            with SCHEDULE_RUNNING_LOCK:
                                SCHEDULE_RUNNING.discard(job_id)
                            raise
                    except (KeyError, TypeError, ValueError):
                        update_schedule(job.get("id", ""), last_status="failed", last_error="invalid cron")
            except OSError as exc:
                log_event("schedule.error", "Could not read or save the scheduled jobs", error=str(exc))
        time.sleep(15)


def send_discord_schedule_result(job: dict[str, Any], answer: str) -> None:
    """Send a scheduled job result to its configured Discord channel."""
    channel_id = str(job.get("discord_channel_id") or "").strip()
    if not channel_id:
        return
    if not channel_id.isdigit():
        raise ValueError("The Discord Channel ID must be a number")
    if DISCORD_BOT is None or DISCORD_LOOP is None or DISCORD_LOOP.is_closed():
        raise RuntimeError("The Discord bot is not connected yet")

    async def deliver() -> None:
        """Send the scheduled result chunks to the Discord channel."""
        channel = DISCORD_BOT.get_channel(int(channel_id))
        if channel is None:
            channel = await DISCORD_BOT.fetch_channel(int(channel_id))
        for chunk in split_discord_message(f"⏰ {job['name']}\n\n{answer}"):
            await channel.send(chunk)

    future = asyncio.run_coroutine_threadsafe(deliver(), DISCORD_LOOP)
    future.result(timeout=30)


def start_scheduler() -> None:
    """Start the cron loop once per process, and only in one process at a time."""
    global _SCHEDULER_STARTED, _SCHEDULER_LOCK_HANDLE
    with _SCHEDULER_START_LOCK:
        if _SCHEDULER_STARTED:
            return
        try:
            handle = open(SCHEDULE_LOCK_FILE, "a+", encoding="utf-8")
        except OSError as exc:
            log_event("schedule.error", "Could not open the scheduler lock file", error=str(exc))
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return
        _SCHEDULER_LOCK_HANDLE = handle
        _SCHEDULER_STARTED = True
    threading.Thread(target=schedule_loop, name="scheduled-ai-jobs", daemon=True).start()


def normalized_path_under(raw_path: str, root: Path, message: str, error: type[Exception] = ValueError) -> Path:
    """Normalize a user path and keep it inside *root*.

    The shape matters: CodeQL's py/path-injection query only treats a path as
    checked when it passes through os.path.normpath()/realpath() and is then
    compared with str.startswith(). Path.relative_to() alone is not recognised
    as a check, so the guard is written the way the query understands.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise error(message)
    root_text = os.path.normpath(os.path.realpath(str(root)))
    candidate_text = os.path.normpath(
        os.path.realpath(os.path.join(root_text, os.path.expanduser(raw_path.strip())))
    )
    if candidate_text != root_text and not candidate_text.startswith(root_text + os.sep):
        raise error(message)
    return Path(candidate_text)


def resolve_project_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a user path inside the project while blocking protected files."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path inside the project is required")
    project_root = PROJECT_ROOT.resolve()
    candidate = normalized_path_under(raw_path, project_root, "Only paths inside the project folder are allowed")
    # Repeat the normalized prefix check here: CodeQL only treats a startswith()
    # guard in this function as a barrier for the accesses below.
    candidate_text = os.path.normpath(str(candidate))
    if candidate_text == PROJECT_ROOT_TEXT:
        candidate_text = PROJECT_ROOT_TEXT + os.sep
    if not candidate_text.startswith(PROJECT_ROOT_TEXT + os.sep):
        raise ValueError("Only paths inside the project folder are allowed")
    candidate = Path(candidate_text)
    relative_text = os.path.relpath(str(candidate), str(project_root))
    relative_parts: list[str] = [] if relative_text == os.curdir else relative_text.split(os.sep)
    if any(part in PROTECTED_PARTS for part in relative_parts) or candidate.name in PROTECTED_NAMES:
        raise ValueError("Access to files or folders holding secrets is not allowed")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def machine_access_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return whether tools may reach the whole machine instead of the project only."""
    settings = settings if settings is not None else load_settings()
    return bool(settings.get("machine_access", True))


def approval_required_tools(settings: dict[str, Any] | None = None) -> set[str]:
    """Return the tools that need a fresh, single-use user approval."""
    if machine_access_enabled(settings):
        return set(MACHINE_TOOL_NAMES)
    return set(APPROVAL_REQUIRED_TOOLS)


def resolve_tool_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a tool path safely for tool execution requests."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path is required")
    candidate = normalized_path_under(
        raw_path,
        PROJECT_ROOT,
        "The path is outside the project folder and is not allowed",
        PermissionError,
    )
    candidate_text = os.path.normpath(str(candidate))
    if candidate_text == PROJECT_ROOT_TEXT:
        candidate_text = PROJECT_ROOT_TEXT + os.sep
    if not candidate_text.startswith(PROJECT_ROOT_TEXT + os.sep):
        raise PermissionError("The path is outside the project folder and is not allowed")
    candidate = Path(candidate_text)
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def resolve_machine_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a path anywhere on the machine for machine-access tools.

    Machine access is the documented default; without this resolver the tools
    advertised as machine-scoped still refused every path outside the project.
    The parent is resolved through realpath before ".." is collapsed, so a
    symlinked folder cannot turn an approved write into a different file, and
    the final component may still be missing because write_file creates it.
    protected_write_target() resolves the finished path before it decides, so a
    symlinked final file is checked against the same secret rules.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path is required")
    raw_text = raw_path.strip()
    if "\x00" in raw_text:
        raise ValueError("Invalid path")
    expanded = os.path.expanduser(raw_text)
    parent_text, name = os.path.split(expanded)
    if not name or name in {".", ".."}:
        raise ValueError("Invalid path")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError("Invalid path")
    resolved_parent = os.path.realpath(parent_text or os.curdir)
    candidate = Path(os.path.normpath(os.path.join(resolved_parent, name)))
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def workspace_directory() -> Path:
    """Return the AI workspace folder, creating it on first use."""
    root = Path(os.path.normpath(str(PROJECT_ROOT / WORKSPACE_ROOT)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_tool_path(raw_path: Any) -> Path:
    """Resolve a tool path against the AI workspace instead of the app folder.

    A relative path (or no path at all) belongs to the workspace, while an
    absolute path or one starting with ~ still reaches the rest of the machine
    when machine access is on.
    """
    text = "" if raw_path is None else str(raw_path).strip()
    if not text or text in {".", "./"}:
        return workspace_directory()
    expanded = os.path.expanduser(text)
    if os.path.isabs(expanded):
        return Path(os.path.normpath(expanded))
    return Path(os.path.normpath(os.path.join(str(workspace_directory()), expanded)))


try:
    workspace_directory()
except OSError as exc:
    LOGGER.warning("Could not create the AI workspace folder: %s", exc)


def configured_secret_targets() -> list[Path]:
    """Return the settings, auth, history and certificate paths in use."""
    # ENV_FILE is included because .env itself can be a symlink: resolving the
    # write target would otherwise hide the protected name behind its target.
    targets = [SETTINGS_FILE, AUTH_FILE, HISTORY_ROOT, ENV_FILE]
    for name in ("AI_WEB_TLS_CERT", "AI_WEB_TLS_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            targets.append(Path(value))
    resolved: list[Path] = []
    for target in targets:
        try:
            resolved.append(target.expanduser().resolve())
        except OSError:
            continue
    return resolved


def protected_write_target(path: Path) -> bool:
    """Return True when a write would touch a secret or machine-specific file.

    These files hold API keys, pairing state, certificates and conversation
    history, so no tool may overwrite them even when machine access is on.
    The settings, auth, history and certificate locations can be moved with
    environment variables, so the configured paths are compared as well: a
    write to a custom settings file must stay blocked like the default one.
    """
    parts = [part for part in path.parts if part not in {"/", "", "."}]
    if any(part in PROTECTED_NAMES for part in parts):
        return True
    if any(part in PROTECTED_PARTS for part in parts):
        return True
    # Canonicalize in a non-strict way for untrusted paths: resolve the parent
    # through realpath, then collapse traversal in the final path text.
    try:
        expanded = os.path.expanduser(str(path))
        parent_text, name = os.path.split(expanded)
        resolved_parent = os.path.realpath(parent_text or os.curdir)
        resolved = Path(os.path.normpath(os.path.join(resolved_parent, name)))
    except OSError:
        return False
    resolved_parts = [part for part in resolved.parts if part not in {"/", "", "."}]
    if any(part in PROTECTED_NAMES or part in PROTECTED_PARTS for part in resolved_parts):
        return True
    for target in configured_secret_targets():
        if resolved == target or target in resolved.parents:
            return True
    return False


def display_tool_path(path: Path) -> str:
    """Show a project-relative path when possible, otherwise the absolute path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def ensure_safe_command_token(token: str) -> None:
    """Reject command arguments that point outside the project or at protected files."""
    normalized = token.replace("\\", "/").strip()
    if not normalized or normalized.startswith("-"):
        return
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if normalized.startswith(("/", "~")) or ".." in parts:
        raise ValueError("The command must reference paths inside the project only")
    if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in parts):
        raise ValueError("Access to files or folders holding secrets is not allowed")


SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log"}
SAFE_GIT_OPTIONS = {
    "-p", "-n", "--oneline", "--stat", "--shortstat", "--name-only", "--name-status",
    "--no-color", "--no-pager", "--graph", "--decorate", "--all", "--cached",
}
SAFE_LS_OPTIONS = {"-a", "-l", "-la", "-al", "-lh", "-lah", "-R", "-t", "-r", "-1", "-h"}


def parse_command(command: str) -> list[str]:
    """Parse one whitelisted command into argv without ever invoking a shell."""
    if any(character in command for character in ("\n", "\r", ";", "|", "&", ">", "<", "`", "$(")):
        raise ValueError("The command uses syntax that is not allowed")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError("Invalid command format") from exc
    if not argv:
        raise ValueError("A command is required")
    binary, rest = argv[0], argv[1:]
    if binary == "pwd":
        if rest:
            raise ValueError("pwd takes no arguments")
    elif binary == "ls":
        for token in rest:
            if token.startswith("-"):
                if token not in SAFE_LS_OPTIONS:
                    raise ValueError(f"ls option {token} is not allowed")
            else:
                ensure_safe_command_token(token)
    elif binary == "git":
        if not rest or rest[0] not in SAFE_GIT_SUBCOMMANDS:
            raise ValueError("Only git status, git diff and git log are allowed")
        for token in rest[1:]:
            if token.startswith("-"):
                if token not in SAFE_GIT_OPTIONS and not token.lstrip("-").isdigit():
                    raise ValueError(f"git option {token} is not allowed")
            else:
                ensure_safe_command_token(token)
        # .git/config and .gitattributes can point at external programs or
        # textconv filters; neither may run while inspecting the repository.
        argv = ["git", "-c", "diff.external=", "--no-pager", *rest]
        if rest[0] in {"diff", "log"}:
            argv.extend(["--no-ext-diff", "--no-textconv"])
    elif binary in {"python", "python3"}:
        if rest != ["-m", "py_compile", "app.py"]:
            raise ValueError("Only the app.py syntax check is allowed")
    else:
        raise ValueError("Only the defined project check commands are allowed")
    return argv


def request_tool_approval(name: str, arguments: dict[str, Any]) -> tuple[str, int]:
    """Create a short-lived approval token for a sensitive tool call.

    Returns the token and the unix timestamp it expires at. The expiry is
    derived from the same clock reading that is stored as ``created_at``, so
    the deadline the client shows matches what ``consume_tool_approval``
    accepts even when this call waits on the lock.
    """
    approval_id = secrets.token_urlsafe(24)
    now = time.time()
    with PENDING_APPROVAL_LOCK:
        for key, item in list(PENDING_TOOL_REQUESTS.items()):
            if now - item.get("created_at", 0) > APPROVAL_TTL_SECONDS:
                PENDING_TOOL_REQUESTS.pop(key, None)
        while len(PENDING_TOOL_REQUESTS) >= MAX_PENDING_APPROVALS:
            PENDING_TOOL_REQUESTS.pop(next(iter(PENDING_TOOL_REQUESTS)))
        PENDING_TOOL_REQUESTS[approval_id] = {"name": name, "arguments": arguments, "created_at": now}
    return approval_id, int(now) + APPROVAL_TTL_SECONDS


def consume_tool_approval(approval_id: Any, name: str, arguments: dict[str, Any]) -> bool:
    """Validate and consume a pending tool approval exactly once."""
    if not isinstance(approval_id, str) or not approval_id:
        return False
    now = time.time()
    with PENDING_APPROVAL_LOCK:
        pending = PENDING_TOOL_REQUESTS.pop(approval_id, None)
    if not pending:
        return False
    if now - pending.get("created_at", 0) > APPROVAL_TTL_SECONDS:
        return False
    return pending.get("name") == name and pending.get("arguments") == arguments


def run_local_tool(name: str, arguments: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    """Execute one local tool call after checking approvals and arguments."""
    requested_name = name
    name = TOOL_ALIASES.get(name, name)
    if requested_name != name:
        log_event("tool.alias", f"Mapped tool name {requested_name} to {name}", requested=requested_name, tool=name)
    log_event("tool.start", f"Starting {name}", tool=name, approved=approved)
    if name == "create_skill":
        if not approved:
            raise PermissionError("Creating a skill needs approval first")
        skill_name = arguments.get("name", "")
        content = arguments.get("content", "")
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("The skill content is invalid or larger than allowed")
        path = skill_path(skill_name)
        skill_text = os.path.normpath(str(path))
        if not skill_text.startswith(SKILLS_ROOT_TEXT + os.sep):
            raise PermissionError("The skill path is outside the allowed folder")
        path = Path(skill_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        try:
            display_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            # AI_WEB_SKILLS_DIR may point outside the project; report it as is.
            display_path = str(path)
        result = {"tool": name, "name": path.parent.name, "path": display_path}
        log_event("tool.success", f"Created skill {path.parent.name}", tool=name, path=result["path"])
        return result
    if name == "create_schedule":
        if not approved:
            raise PermissionError("Creating a scheduled job needs approval first")
        job_name = str(arguments.get("name", "")).strip()
        prompt = str(arguments.get("prompt", "")).strip()
        if not job_name or not prompt:
            raise ValueError("A job name and prompt are required")
        schedule = validate_cron(arguments.get("schedule", ""))
        discord_channel_id = str(arguments.get("discord_channel_id", "")).strip()[:30]
        if discord_channel_id and not discord_channel_id.isdigit():
            raise ValueError("The Discord Channel ID must be a number")
        job = {
            "id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "name": job_name[:100],
            "schedule": schedule,
            "prompt": prompt[:10_000],
            "model": str(arguments.get("model", "")).strip()[:200],
            "discord_channel_id": discord_channel_id,
            "enabled": bool(arguments.get("enabled", True)),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "last_run_at": None,
            "last_status": None,
            "last_error": "",
        }
        with SCHEDULE_LOCK:
            jobs = load_schedules()
            jobs.append(job)
            save_schedules(jobs)
        log_event("schedule.created", f"Created scheduled job {job['name']}", job=job["id"], schedule=schedule)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "update_schedule":
        if not approved:
            raise PermissionError("Editing a scheduled job needs approval first")
        job_id = str(arguments.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("job_id is required")
        with SCHEDULE_LOCK:
            jobs = load_schedules()
            job = next((item for item in jobs if item.get("id") == job_id), None)
            if not job:
                raise ValueError("Scheduled job not found")
            if "schedule" in arguments:
                job["schedule"] = validate_cron(arguments["schedule"])
            if "name" in arguments:
                job["name"] = str(arguments["name"]).strip()[:100] or job["name"]
            if "prompt" in arguments:
                job["prompt"] = str(arguments["prompt"]).strip()[:10_000]
            if "model" in arguments:
                job["model"] = str(arguments["model"]).strip()[:200]
            if "discord_channel_id" in arguments:
                channel_id = str(arguments["discord_channel_id"]).strip()[:30]
                if channel_id and not channel_id.isdigit():
                    raise ValueError("The Discord Channel ID must be a number")
                job["discord_channel_id"] = channel_id
            if "enabled" in arguments:
                job["enabled"] = bool(arguments["enabled"])
            save_schedules(jobs)
        log_event("schedule.updated", f"Updated scheduled job {job['name']}", job=job_id)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "list_files":
        machine_access = machine_access_enabled()
        requested_path = str(workspace_tool_path(arguments.get("path", ".")))
        if machine_access:
            root = resolve_machine_path(requested_path, must_exist=True)
        else:
            root = resolve_tool_path(requested_path, must_exist=True)
            root_text = os.path.normpath(str(root))
            if root_text == PROJECT_ROOT_TEXT:
                root_text = PROJECT_ROOT_TEXT + os.sep
            if not root_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            root = Path(root_text)
        if not root.is_dir():
            raise ValueError("This path is not a folder")
        files: list[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            if not machine_access:
                dirnames[:] = sorted(directory for directory in dirnames if directory not in PROTECTED_PARTS)
            for filename in sorted(filenames):
                if not machine_access and filename in PROTECTED_NAMES:
                    continue
                if len(files) >= 500:
                    truncated = True
                    break
                files.append(display_tool_path(Path(dirpath, filename)))
            if truncated:
                break
        result = {"tool": name, "files": files, "truncated": truncated, "scope": "machine" if machine_access else "project"}
        log_event("tool.success", f"Used {name}", tool=name, count=len(files))
        return result

    if name == "read_file":
        machine_access = machine_access_enabled()
        if not str(arguments.get("path") or "").strip():
            raise ValueError("A file path is required (relative paths resolve inside the workspace folder)")
        requested_path = str(workspace_tool_path(arguments.get("path", "")))
        if machine_access:
            # Same scope as list_files and write_file: any path on the machine,
            # including a workspace folder configured outside the project.
            path = resolve_machine_path(requested_path, must_exist=True)
        else:
            path = resolve_project_path(requested_path, must_exist=True)
            file_text = os.path.normpath(str(path))
            if not file_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            path = Path(file_text)
        if not path.is_file():
            raise ValueError("This path is not a file")
        if path.stat().st_size > TOOL_MAX_READ_BYTES:
            raise ValueError("The file is larger than the allowed read size")
        if machine_access:
            # Whole-machine reads must not copy stored credentials into the chat
            # transcript or the saved conversation history. The snapshot, the
            # read and the redaction share SETTINGS_LOCK with the settings
            # writers: a save that lands mid-read would otherwise add a key
            # that neither the snapshot nor the redaction knows.
            with SETTINGS_LOCK:
                try:
                    secrets_before_read = secret_values()
                except (OSError, ValueError):
                    secrets_before_read = []
                content = path.read_text(encoding="utf-8", errors="replace")
                content = redact_secrets(content)
                content = redact_command_output(content, secrets_before_read)
        else:
            content = path.read_text(encoding="utf-8", errors="replace")
        result = {"tool": name, "path": display_tool_path(path), "content": content, "scope": "machine" if machine_access else "project"}
        log_event("tool.success", f"Used {name}", tool=name, path=result["path"])
        return result

    if name == "write_file":
        if not approved:
            raise PermissionError("Writing a file needs approval first")
        machine_access = machine_access_enabled()
        if not str(arguments.get("path") or "").strip():
            raise ValueError("A file path is required (relative paths resolve inside the workspace folder)")
        requested_path = str(workspace_tool_path(arguments.get("path", "")))
        if machine_access:
            path = resolve_machine_path(requested_path)
        else:
            path = resolve_tool_path(requested_path)
            write_text = os.path.normpath(str(path))
            if not write_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            path = Path(write_text)
        content = arguments.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("The file content is larger than allowed")
        if protected_write_target(path):
            raise PermissionError("Writing files that hold secrets, certificates or history is not allowed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result = {"tool": name, "path": display_tool_path(path), "bytes": len(content.encode("utf-8"))}
        log_event("tool.success", f"Used {name}", tool=name, path=result["path"], bytes=result["bytes"])
        return result

    if name == "run_command":
        if not approved:
            raise PermissionError("Running a command needs approval first")
        command = arguments.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A command is required")
        command = command.strip()
        if len(command) > 4000:
            raise ValueError("The command is too long (4000 characters max)")
        if machine_access_enabled():
            # A real shell with the app user's privileges: any binary, pipes,
            # sudo (when the user may run it without a password prompt), and
            # any path on the machine. The approval click is the boundary.
            returncode, stdout, stderr, timed_out, truncated, duration_ms, launch_secrets = run_shell_process(command, workspace_directory())
            if timed_out:
                returncode = 124
            secrets_found = secret_values(launch_secrets)
            result = {
                "tool": name,
                "command": redact_command_output(command, secrets_found),
                "returncode": returncode,
                "stdout": redact_command_output(stdout, secrets_found),
                "stderr": redact_command_output(stderr, secrets_found),
                "timed_out": timed_out,
                "truncated": truncated,
                "duration_ms": duration_ms,
                "scope": "machine",
            }
            log_event(
                "tool.success" if returncode == 0 else "tool.failed",
                f"Command finished ({returncode})",
                tool=name,
                command=redact_command_output(command, secrets_found)[:300],
                duration_ms=duration_ms,
            )
            return result
        argv = parse_command(command)
        completed = subprocess.run(argv, cwd=PROJECT_ROOT, shell=False, capture_output=True, text=True, timeout=30)
        result = {"tool": name, "command": command, "returncode": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:], "scope": "project"}
        log_event("tool.success" if completed.returncode == 0 else "tool.failed", f"Command finished ({completed.returncode})", tool=name, command=command)
        return result

    raise ValueError("Unknown tool")


def command_shell() -> str:
    """Pick an available POSIX shell, including Termux where /bin/sh may not exist."""
    for candidate in (os.getenv("SHELL"), shutil.which("bash"), shutil.which("sh"), "/system/bin/sh", "/bin/sh"):
        if candidate and Path(candidate).exists():
            return candidate
    return "sh"


def command_environment() -> tuple[dict[str, str], list[str]]:
    """Inherit the server environment without exposing credentials to commands.

    Returns the child environment plus the custom key values injected into it,
    so a command's output can still be redacted when a key is deleted or
    replaced while that command is still running.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(part in name.upper() for part in SENSITIVE_ENV_PARTS)
    }
    # Extra keys saved in Settings are exposed by name so a skill or command
    # can use e.g. "$WEATHER_API_KEY" without the value ever reaching the chat.
    injected: list[str] = []
    try:
        for name, value in stored_custom_api_keys(load_settings()).items():
            if name in env:
                continue
            env[name] = value
            injected.append(value)
    except (OSError, ValueError):
        pass
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("LANG", "C.UTF-8")
    env["PYTHONUNBUFFERED"] = "1"
    return env, injected


def secret_values(extra: list[str] | None = None) -> list[str]:
    """Collect secret values that command output must never expose."""
    settings = load_settings()
    values = {value for value in stored_api_keys(settings).values() if value}
    values.update(stored_custom_api_keys(settings).values())
    if extra:
        values.update(value for value in extra if value)
    discord_token = get_discord_token(settings)
    if discord_token:
        values.add(discord_token)
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(part in name.upper() for part in SENSITIVE_ENV_PARTS):
            values.add(value)
    return sorted(values, key=len, reverse=True)


PEM_REDACTED_MARKER = "•••••••• (private key hidden)"
PEM_MARKER_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
# How far before a truncated capture tail to look for an opening BEGIN line.
PEM_LOOKBACK_BYTES = 8192


def pem_state(text: str, inside: bool = False) -> bool:
    """Report whether the text ends inside a private key block."""
    for match in PEM_MARKER_PATTERN.finditer(text):
        inside = match.group(0).startswith("-----BEGIN")
    return inside


def mask_unterminated_pem(text: str, starts_inside: bool = False) -> str:
    """Mask private key blocks, including one cut in half by the read boundary."""
    if not text:
        return text
    ranges: list[tuple[int, int]] = []
    inside = starts_inside
    opened_at = 0
    for match in PEM_MARKER_PATTERN.finditer(text):
        if match.group(0).startswith("-----BEGIN"):
            if not inside:
                inside = True
                opened_at = match.start()
        elif inside:
            inside = False
            ranges.append((opened_at, match.end()))
    if inside:
        ranges.append((opened_at, len(text)))
    for start, end in reversed(ranges):
        text = text[:start] + PEM_REDACTED_MARKER + text[end:]
    return text


def redact_command_output(text: str, secrets_found: list[str]) -> str:
    """Replace known secrets and any private key block in command output."""
    for secret in secrets_found:
        text = text.replace(secret, "••••••••")
    # mask_unterminated_pem walks the BEGIN/END markers instead of running a
    # DOTALL regex over the whole capture, so large output cannot go quadratic.
    return mask_unterminated_pem(text)


SECRET_QUERY_PATTERN = re.compile(r"([?&](?:key|api_key|api-key|token|access_token)=)[^&\s\"'<>]+", re.IGNORECASE)


def redact_secrets(text: str, api_key: str | None = None) -> str:
    """Remove API keys and tokens from text before it is returned or logged."""
    value = SECRET_QUERY_PATTERN.sub(r"\1••••••••", str(text))
    # Redact the submitted request's API key if provided
    if api_key:
        value = value.replace(api_key, "••••••••")
    try:
        secrets_found = secret_values()
    except (OSError, ValueError):
        secrets_found = []
    return redact_command_output(value, secrets_found)


def read_command_capture(handle: Any) -> tuple[str, bool]:
    """Read at most the tail of a captured stream so runaway output cannot exhaust memory."""
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    start = max(0, size - COMMAND_MAX_OUTPUT_BYTES)
    cut = start > 0
    # A private key block may open before the tail starts, so derive the
    # redaction state from a bounded window in front of it instead of relying on
    # the BEGIN line being inside the returned text.
    starts_inside = False
    if cut:
        lookback_start = max(0, start - PEM_LOOKBACK_BYTES)
        handle.seek(lookback_start)
        starts_inside = pem_state(
            handle.read(start - lookback_start).decode("utf-8", errors="replace")
        )
    handle.seek(start)
    text = mask_unterminated_pem(
        handle.read().decode("utf-8", errors="replace"), starts_inside
    )
    if cut:
        text = "… (start of the output trimmed because there is a lot of it)\n" + text
    return text, cut


def process_group_alive(pgid: int) -> bool:
    """Report whether any process of a command's group still runs."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_process_group(pgid: int) -> None:
    """Kill every process left in a command's group."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_shell_process(command: str, cwd: Path) -> tuple[int, str, str, bool, bool, int, list[str]]:
    """Run a command with capped output and a hard timeout for the whole process group."""
    started_at = time.perf_counter()
    timed_out = False
    env, injected_secrets = command_environment()
    if not command.strip():
        raise ValueError("Type a command")
    # Agent commands run through the real shell so pipes, redirections, globs
    # and variables behave as typed; approval is the boundary.
    argv = [command_shell(), "-c", command]
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=out_file,
            stderr=err_file,
            env=env,
            start_new_session=True,
        )
        # The group is its own session, so its id is the leader's pid.
        pgid = process.pid
        deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
        try:
            process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_group(pgid)
            process.wait()
        # A shell that exits still leaves `cmd &` jobs running in the group, and
        # they keep the capture files open. They get the same deadline, then the
        # group is killed so nothing outlives the timeout.
        while process_group_alive(pgid):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # The shell already exited, so the job outlived the deadline:
                # report it as a timeout instead of the shell's status 0.
                kill_process_group(pgid)
                timed_out = True
                break
            time.sleep(min(0.05, remaining))
        stdout, stdout_cut = read_command_capture(out_file)
        stderr, stderr_cut = read_command_capture(err_file)
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    return process.returncode, stdout, stderr, timed_out, stdout_cut or stderr_cut, duration_ms, injected_secrets


def parse_tool_request(answer: str) -> dict[str, Any] | None:
    """Return the first tool call found in an AI answer, if any."""
    requests = parse_tool_requests(answer)
    return requests[0] if requests else None


ASCII_LOWERCASE_TABLE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)


def tool_call_bodies(answer: str) -> list[str]:
    """Return the body of every <tool_call> block in *answer*.

    Plain marker scanning keeps the work linear, so a reply that repeats
    "<tool_call>" many times cannot make the parser backtrack. Only ASCII
    letters are lowercased: str.lower() can lengthen a character (for example
    U+0130 becomes two characters), which would shift the marker offsets that
    slice *answer*.
    """
    bodies: list[str] = []
    lowered = answer.translate(ASCII_LOWERCASE_TABLE)
    start = 0
    while True:
        open_at = lowered.find("<tool_call>", start)
        if open_at < 0:
            return bodies
        body_start = open_at + len("<tool_call>")
        close_at = lowered.find("</tool_call>", body_start)
        if close_at < 0:
            return bodies
        bodies.append(answer[body_start:close_at])
        start = close_at + len("</tool_call>")


def parse_tool_requests(answer: str) -> list[dict[str, Any]]:
    """Parse every tool call so multiple Skill files can be inspected in one turn."""
    if not isinstance(answer, str):
        return []
    # A marker scan instead of a DOTALL regular expression: the answer is shared
    # with the model, so a pathological reply must not be able to backtrack.
    matches = tool_call_bodies(answer)
    if not matches:
        return []
    requests = []
    for raw_request in matches:
        try:
            request = json.loads(raw_request.strip())
        except json.JSONDecodeError as exc:
            log_event("tool.parse_failed", "Could not parse the tool_call", error=str(exc))
            raise ValueError("Invalid tool_call format") from exc
        if not isinstance(request, dict) or not isinstance(request.get("name"), str) or not isinstance(request.get("arguments", {}), dict):
            raise ValueError("Invalid tool_call payload")
        tool_request = {"name": request["name"], "arguments": request.get("arguments", {})}
        log_event("tool.request", f"The AI requested {tool_request['name']}", tool=tool_request["name"])
        requests.append(tool_request)
    return requests


def find_history_file(conversation_id: str) -> Path | None:
    """Find the history file that stores one conversation id.

    The same conversation can exist more than once when an older build wrote a
    relative path under ``history/history``. The newest copy holds the latest
    writes, so pick that one instead of relying on directory order.
    """
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    matches = list(HISTORY_ROOT.rglob(f"*_{conversation_id}.json"))
    if len(matches) <= 1:
        return matches[0] if matches else None

    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(matches, key=modified)


class HistoryConflict(Exception):
    """Raised when an append targets a conversation record that was replaced."""


class HistoryLocked(Exception):
    """Raised when a write tries to replace a locked conversation record."""


@contextmanager
def history_mutation_lock():
    """Serialize history mutations in this process and across processes.

    HISTORY_LOCK keeps threads in this process apart; the file lock extends the
    same guarantee to other worker processes that share HISTORY_ROOT.
    """
    with HISTORY_LOCK:
        HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(HISTORY_LOCK_FILE, "a+", encoding="utf-8")
        except OSError as exc:
            # Without the cross-process lock a mutation could race another
            # writer, so fail the request instead of proceeding unlocked.
            log_event("history.error", "Could not open the history lock file", error=str(exc))
            raise
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def history_generation(record: dict[str, Any]) -> str | None:
    """Return the identity token callers use to bind appends to a record."""
    value = record.get("generation") or record.get("created_at")
    return value if isinstance(value, str) and value else None


def save_history(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a conversation history file and return its record."""
    with history_mutation_lock():
        return _save_history_unlocked(payload)


def history_record_path(path: Path) -> Path:
    """Return *path* normalized and confirmed inside the history folder.

    The path is made absolute first: a path read back from disk by
    ``find_history_file`` is relative (``history/<date>/<file>.json``), and
    ``normalized_path_under`` joins its input to the root, so passing it as is
    would write ``history/history/<date>/<file>.json`` and leave every read
    looking at a stale copy.
    """
    return normalized_path_under(os.path.abspath(str(path)), HISTORY_ROOT, "Invalid history path")


def _write_history_record(path: Path, record: dict[str, Any]) -> None:
    """Write one history record atomically so readers never see a partial file."""
    path = history_record_path(path)
    record_text = os.path.normpath(str(path))
    if not record_text.startswith(HISTORY_ROOT_TEXT + os.sep):
        raise ValueError("Invalid history path")
    path = Path(record_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _save_history_unlocked(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or replace a history record while HISTORY_LOCK is held."""
    conversation_id = payload.get("id") or ""
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        conversation_id = str(uuid.uuid4())
    now = datetime.now().astimezone()
    existing = find_history_file(conversation_id)
    existing_record = {}
    if existing and existing.exists():
        try:
            parsed = json.loads(existing.read_text(encoding="utf-8"))
            existing_record = parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError):
            existing_record = {}
    if existing_record.get("locked"):
        # The lock must protect the stored messages too, not only rename/delete.
        raise HistoryLocked("This conversation is locked; unlock it before saving over it")
    messages = list(payload.get("messages") or [])
    existing_messages = existing_record.get("messages") if isinstance(existing_record.get("messages"), list) else []
    base_count = payload.get("base_message_count")
    if isinstance(base_count, int) and not isinstance(base_count, bool) and 0 <= base_count <= len(existing_messages):
        # The caller built its snapshot from the first base_count messages. Keep any
        # messages appended or saved after that snapshot instead of overwriting them.
        if len(messages) <= len(existing_messages) and all(
            left == right for left, right in zip(messages, existing_messages)
        ):
            # A retry of an already-merged snapshot must not append the tail twice.
            messages = list(existing_messages)
        else:
            known_ids = {
                message.get("message_id")
                for message in messages
                if isinstance(message, dict) and message.get("message_id")
            }
            for message in existing_messages[base_count:]:
                message_id = message.get("message_id") if isinstance(message, dict) else None
                if message_id and message_id in known_ids:
                    continue
                if message in messages:
                    continue
                messages.append(message)
                if message_id:
                    known_ids.add(message_id)
    created_at = (
        payload.get("created_at")
        or existing_record.get("created_at")
        or now.isoformat(timespec="seconds")
    )
    # New records (no existing file) get a generation; legacy records keep theirs.
    if not existing_record:
        record_generation = str(uuid.uuid4())
    else:
        # Preserve the existing generation so appends that were started against
        # the old record still validate against it.
        record_generation = existing_record.get("generation")
    path = existing or HISTORY_ROOT / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_{conversation_id}.json"
    path = history_record_path(path)
    raw_title = payload.get("title")
    existing_title = (
        existing_record.get("title") if isinstance(existing_record.get("title"), str) else ""
    )
    title = (
        raw_title.strip()[:100]
        if isinstance(raw_title, str) and raw_title.strip()
        else existing_title.strip()[:100] or "New conversation"
    )
    record = {
        "id": conversation_id,
        "title": title,
        "created_at": created_at,
        "updated_at": now.isoformat(timespec="seconds"),
        "locked": bool(existing_record.get("locked", False)),
        "pinned": bool(existing_record.get("pinned", False)),
        "messages": messages,
        "generation": record_generation,
    }
    _write_history_record(path, record)
    return record


def append_history_messages(conversation_id: str, new_messages: list[dict[str, Any]], generation: str | None = None) -> dict[str, Any] | None:
    """Append messages to an existing conversation, or return None if it is gone.

    The read-modify-write happens under HISTORY_LOCK, so an append can never
    recreate a conversation deleted at the same time. Messages carrying a
    message_id are appended idempotently. The optional *generation* parameter
    must match the generation stored in the record; otherwise HistoryConflict
    is raised so the caller can retry or stop instead of appending to stale data.
    """
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if path is None or not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        if record.get("locked"):
            # Locked conversations reject edits and deletes; appending must not
            # become a way around that protection.
            raise HistoryLocked("This conversation is locked")
        record_generation = history_generation(record)
        if generation is not None and record_generation != generation:
            raise HistoryConflict(
                f"Record generation {record_generation!r} does not match append generation {generation!r}"
            )
        record_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        known_ids = {
            message.get("message_id")
            for message in record_messages
            if isinstance(message, dict) and message.get("message_id")
        }
        added = False
        for message in new_messages:
            if not isinstance(message, dict):
                continue
            message_id = message.get("message_id")
            if message_id and message_id in known_ids:
                continue
            record_messages.append(message)
            if message_id:
                known_ids.add(message_id)
            added = True
        if added:
            record["messages"] = record_messages
            record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _write_history_record(path, record)
        return record


def save_discord_turn(conversation_id: str, title: str, context_messages: list[dict[str, Any]]) -> None:
    """Persist only the newest Discord exchange so earlier history survives.

    The Discord context is a bounded deque, so saving the whole deque would
    truncate the conversation record on every reply.
    """
    turn = [
        message for message in context_messages[-2:]
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
    ]
    if not turn:
        return
    if load_history_record(conversation_id):
        try:
            append_history_messages(conversation_id, turn)
        except HistoryLocked:
            # A locked conversation must not be written by an automated turn.
            log_event("discord.locked", "Skipped a turn for a locked conversation", conversation=conversation_id)
        return
    save_history({"id": conversation_id, "title": title, "messages": list(context_messages)})


def load_history_record(conversation_id: str) -> dict[str, Any]:
    """Read one conversation history record, or an empty dict if missing."""
    path = find_history_file(conversation_id)
    if path is None or not path.exists():
        return {}
    return read_history_file(path) or {}


def read_history_file(path: Path) -> dict[str, Any] | None:
    """Read one history file, or None when it is unreadable or malformed."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        # Only the file name is logged: conversation content must stay private.
        LOGGER.warning("Could not read a history file (%s): %s", path.name, exc)
        return None
    return record if isinstance(record, dict) else None


def find_schedule_conversation_id(job_id: str) -> str:
    """Find the newest history conversation that a scheduled job already wrote."""
    if not job_id or not HISTORY_ROOT.exists():
        return ""
    best: tuple[str, str] | None = None
    for path in HISTORY_ROOT.rglob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("messages"), list):
            continue
        if not any(isinstance(message, dict) and message.get("schedule_id") == job_id for message in record["messages"]):
            continue
        conversation_id = record.get("id")
        if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
            continue
        updated_at = str(record.get("updated_at") or "")
        if best is None or updated_at > best[1]:
            best = (conversation_id, updated_at)
    return best[0] if best else ""


def schedule_conversation_id(job: dict[str, Any]) -> str:
    """Resolve one stable history conversation per scheduled job and persist it."""
    conversation_id = str(job.get("conversation_id") or "").strip()
    if re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return conversation_id
    conversation_id = find_schedule_conversation_id(str(job.get("id") or "")) or str(uuid.uuid4())
    job["conversation_id"] = conversation_id
    job_id = str(job.get("id") or "").strip()
    if job_id:
        update_schedule(job_id, conversation_id=conversation_id)
    return conversation_id


# A provider key must not travel in clear text to a remote host. Loopback stays
# allowed for local OpenAI-compatible servers, and an operator can opt in to
# plain HTTP for the rest of a self-hosted network.
ALLOW_INSECURE_PROVIDER_HTTP = os.getenv("AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP", "").strip().lower() in {
    "1", "true", "yes", "on",
}


def endpoint_is_loopback(url: str) -> bool:
    """Return whether a URL points at this machine (where plain HTTP is fine)."""
    try:
        host = (urlsplit(url).hostname or "").strip().lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_secure_model_endpoint(url: str) -> None:
    """Refuse a model request that would send the provider key over plain HTTP."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        # An unmatched IPv6 bracket makes urlsplit raise; report a configuration
        # error the endpoint can localize instead of an opaque HTTP 500.
        raise RuntimeError("The provider Base URL is invalid — check the value in Settings") from None
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if scheme != "http":
        raise RuntimeError(f"The provider endpoint must be http/https (found {scheme or 'no scheme'})")
    host = (parsed.hostname or "").strip().lower()
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    if ALLOW_INSECURE_PROVIDER_HTTP:
        log_event("provider.insecure_http", "Sending the API key over http because AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP is set", host=host)
        return
    raise RuntimeError(
        f"Refused to send the API key over http to {host or 'an unknown host'} "
        "— use https, or set AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP=1 for a trusted server"
    )


def provider_models_get(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> requests.Response:
    """GET a provider model list without following redirects.

    requests drops the Authorization header on a cross-host redirect but keeps
    custom headers such as x-api-key, so a redirecting endpoint could hand the
    key to another origin. A 3xx answer is treated as a failed fetch instead.
    """
    ensure_secure_model_endpoint(url)
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=timeout,
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise RuntimeError(
            f"The endpoint answered HTTP {response.status_code} (redirect) — the API key is not forwarded across the redirect"
        )
    response.raise_for_status()
    return response


def list_models(provider: str, settings: dict[str, Any], timeout: float = 30) -> list[dict[str, str]]:
    """Fetch the available models for a provider, using its API key."""
    provider = normalize_provider(provider)
    key = get_api_key(provider, settings)
    if not key:
        raise RuntimeError("No API key is configured, so the model list cannot be fetched")
    if provider == "gemini":
        response = provider_models_get(
            f"{get_base_url('gemini', settings)}/models",
            params={"key": key},
            timeout=timeout,
        )
        models = response.json().get("models", [])
        return [{"id": item["name"].removeprefix("models/"), "name": item.get("displayName", item["name"])} for item in models if "generateContent" in item.get("supportedGenerationMethods", [])]
    if provider == "anthropic":
        try:
            response = provider_models_get(
                f"{get_base_url('anthropic', settings)}/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            raise RuntimeError(f"Anthropic answered HTTP {status} — check the API key again") from exc
        data = response.json().get("data", [])
        models = [
            {"id": item["id"], "name": item.get("display_name") or item["id"]}
            for item in data
            if isinstance(item, dict) and item.get("id")
        ]
        if models:
            return models
        raise RuntimeError("Anthropic returned no model list")
    base_url = get_base_url(provider, settings)
    response = provider_models_get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    models = response.json().get("data", [])
    return [{"id": item["id"], "name": item["id"]} for item in sorted(models, key=lambda item: item.get("id", ""))]


MODEL_LIST_CACHE_TTL = 600
MODEL_LIST_CACHE: dict[str, tuple[float, list[str]]] = {}
MODEL_LIST_ERROR_LOGGED: dict[str, float] = {}
# An autocomplete never waits on the provider API: it answers from the cache or
# the static list and lets a daemon thread refresh the real list.
MODEL_LIST_REFRESH_TIMEOUT = 8
MODEL_LIST_REFRESH_INTERVAL = 15
MODEL_LIST_REFRESH_LOCK = threading.Lock()
MODEL_LIST_REFRESH_STARTED: dict[str, float] = {}


def remember_model_names(provider: str, names: list[str]) -> None:
    """Cache a provider's model ids so Discord autocomplete can answer instantly."""
    names = [name for name in names if name]
    if names:
        MODEL_LIST_CACHE[normalize_provider(provider)] = (time.time(), list(names))


def forget_model_names() -> None:
    """Drop the cached model ids and the refresh throttle for every provider.

    Clearing the throttle too lets the first autocomplete after a settings
    change refresh at once instead of waiting out the interval.
    """
    with MODEL_LIST_REFRESH_LOCK:
        MODEL_LIST_CACHE.clear()
        MODEL_LIST_REFRESH_STARTED.clear()


def static_model_names(provider: str, settings: dict[str, Any]) -> list[str]:
    """Return the fallback model ids, with the model in use listed first."""
    names = list(FALLBACK_MODELS.get(provider, []))
    active_provider = normalize_provider(settings.get("provider", "openai"))
    active_model = str(settings.get("model") or "").strip()
    if active_provider == provider and active_model and active_model not in names:
        names.insert(0, active_model)
    return names


def refresh_model_names(provider: str, settings: dict[str, Any]) -> None:
    """Fetch a provider's model ids so the next autocomplete has the real list."""
    provider = normalize_provider(provider)
    names: list[str] = []
    try:
        names = [
            str(item.get("id", ""))
            for item in list_models(provider, settings, timeout=MODEL_LIST_REFRESH_TIMEOUT)
            if item.get("id")
        ]
    except (requests.RequestException, RuntimeError, KeyError, TypeError, ValueError) as exc:
        last_logged = MODEL_LIST_ERROR_LOGGED.get(provider, 0)
        if time.time() - last_logged > 60:
            MODEL_LIST_ERROR_LOGGED[provider] = time.time()
            log_event(
                "discord.models",
                "Could not fetch the model list in the background; using the fallback list",
                provider=provider,
                error=str(exc)[:200],
            )
    if names:
        remember_model_names(provider, names)


def schedule_model_list_refresh(provider: str, settings: dict[str, Any]) -> None:
    """Refresh one provider's model ids in a daemon thread, at most every 15s."""
    provider = normalize_provider(provider)
    now = time.time()
    with MODEL_LIST_REFRESH_LOCK:
        started = MODEL_LIST_REFRESH_STARTED.get(provider)
        if started is not None and now - started < MODEL_LIST_REFRESH_INTERVAL:
            return
        MODEL_LIST_REFRESH_STARTED[provider] = now
    threading.Thread(
        target=refresh_model_names,
        args=(provider, settings),
        name=f"model-refresh-{provider}",
        daemon=True,
    ).start()


def model_names_for_autocomplete(provider: str, settings: dict[str, Any]) -> list[str]:
    """Return model ids immediately, refreshing a missing or stale list in the background.

    Discord closes an autocomplete request after about three seconds, so this
    never calls the provider API itself: it answers from the cache, then from a
    stale cache, then from the static list, and the real list arrives through
    :func:`schedule_model_list_refresh` for the next keystroke.
    """
    provider = normalize_provider(provider)
    cached = MODEL_LIST_CACHE.get(provider)
    if cached and time.time() - cached[0] < MODEL_LIST_CACHE_TTL:
        return list(cached[1])
    schedule_model_list_refresh(provider, settings)
    if cached:
        # A stale list still beats the static one while the refresh runs.
        return list(cached[1])
    return static_model_names(provider, settings)


def get_api_key(provider: str, settings: dict[str, Any] | None = None) -> str:
    """Return the provider API key from settings or the environment."""
    provider = normalize_provider(provider)
    settings = settings if settings is not None else load_settings()
    key = stored_api_keys(settings).get(provider, "")
    if not key:
        key = str(os.getenv(PROVIDER_ENV_KEYS.get(provider, "OPENAI_API_KEY"), "")).strip()
    return key


def safe_stored_api_key(provider: str, settings: dict[str, Any] | None) -> str:
    """Read an API key defensively so a settings failure cannot mask the real error."""
    try:
        return get_api_key(provider, settings or {})
    except (OSError, TypeError, ValueError, KeyError):
        return ""


def key_is_configured(provider: str, settings: dict[str, Any] | None = None) -> bool:
    """Return whether a provider has any usable API key."""
    return bool(get_api_key(provider, settings))


def get_base_url(provider: str, settings: dict[str, Any] | None = None) -> str:
    """Get the appropriate base URL for a provider, using stored setting or default."""
    provider = normalize_provider(provider)
    if settings is None:
        settings = load_settings()
    stored_base = str(settings.get("base_url") or "").strip()
    if stored_base:
        return stored_base.rstrip("/")
    # Return provider-specific default if no custom base URL set
    return PROVIDER_BASE_URLS.get(provider, "https://api.openai.com/v1").rstrip("/")


def key_looks_plausible(key: str, provider: str = "openai", base_url: str = "") -> bool:
    """Reject placeholders such as '000' or a leftover masked value."""
    key = str(key or "").strip()
    if not key or "•" in key or " " in key:
        return False
    if provider in {"gemini", "anthropic"}:
        return len(key) >= 20
    official = base_url.rstrip("/") in {"https://api.openai.com/v1", "https://api.openai.com"}
    # Self-hosted OpenAI-compatible servers may accept short local keys.
    return len(key) >= 20 if official else True


def same_secret(left: str, right: str) -> bool:
    """Compare two secrets in constant time.

    The comparison uses the value itself instead of a hash: a hash of an API
    key or token would be a weak password-style digest, and a derived
    identifier would have to be cached, which can lose its identity when the
    cache is trimmed.
    """
    return secrets.compare_digest(str(left).encode("utf-8"), str(right).encode("utf-8"))


STATUS_MESSAGES = {
    "th": {
        "invalid_key": "API key ของ {label} ไม่ถูกต้องหรือหมดสิทธิ์ใช้งาน",
        "endpoint_missing": "ตรวจไม่พบ endpoint ของ {label} — ตรวจสอบ Base URL อีกครั้ง",
        "anthropic_model_missing": "ไม่พบโมเดล Anthropic ที่เลือก หรือโมเดลนี้ไม่เปิดให้ใช้งาน",
        "anthropic_model_error": "Anthropic เรียกโมเดลที่เลือกไม่ได้ (HTTP {status})",
        "http_error": "{label} ตอบกลับ HTTP {status}",
        "connection_failed": "เชื่อมต่อ {label} ไม่ได้: {error}",
        "missing_key": "ยังไม่ได้ตั้งค่า API key ของ {label}",
        "missing_model": "ยังไม่ได้เลือกโมเดลของ {label}",
        "invalid_key_shape": "API key ของ {label} ดูไม่ถูกต้อง (สั้นเกินไปหรือเป็นค่าตัวอย่าง)",
        "tls_invalid_mode": "โหมดการเชื่อมต่อไม่ถูกต้อง",
        "tls_cert_missing": "ไม่พบไฟล์ใบรับรอง — สร้างด้วย ./start_web.sh --make-cert <ip> หรือตั้ง AI_WEB_TLS_CERT และ AI_WEB_TLS_KEY ใน .env ให้ชี้ไฟล์ที่มีอยู่",
        "env_write_failed": "บันทึกไฟล์ .env ไม่สำเร็จ: {error}",
        "server_action_invalid": "คำสั่งควบคุมเซิร์ฟเวอร์ไม่ถูกต้อง",
        "server_script_missing": "ไม่พบสคริปต์ start_web.sh ในโฟลเดอร์โปรเจกต์",
        "server_busy": "มีคำสั่งควบคุมเซิร์ฟเวอร์กำลังทำงานอยู่",
        "server_action_failed": "เริ่มคำสั่งควบคุมเซิร์ฟเวอร์ไม่สำเร็จ: {error}",
        "gemini_key_missing": "ยังไม่ได้ตั้งค่า Gemini API key — เพิ่มคีย์ใน Settings ก่อนใช้ความสามารถนี้",
        "gemini_capability_failed": "ตรวจสอบความสามารถของคีย์ Gemini ไม่สำเร็จ ({error})",
        "gemini_decisions_invalid": "ข้อมูล Decisions API ไม่ถูกต้อง: ต้องมี input และ questions อย่างน้อย 1 ข้อ (noul, choice หรือ score)",
        "gemini_agents_invalid": "ข้อมูล Agents ไม่ถูกต้อง: ต้องระบุ agent และ input",
        "gemini_live_failed": "สร้าง Live API token ไม่สำเร็จ: {detail}",
        "gemini_request_failed": "เรียก Gemini API ไม่สำเร็จ: {detail}",
        "memory_schedule_invalid": "รูปแบบ cron ของ Memory ไม่ถูกต้อง",
        "memory_busy": "ระบบความจำกำลังทำงานอยู่ กรุณารอสักครู่",
        "memory_run_failed": "รันระบบความจำไม่สำเร็จ: {error}",
        "memory_not_found": "ไม่พบรายการความจำนี้",
        "memory_forget_failed": "ลบรายการความจำไม่สำเร็จ",
        "memory_reindex_failed": "สร้างดัชนีความจำใหม่ไม่สำเร็จ: {error}",
        "invalid_body": "รูปแบบข้อมูลไม่ถูกต้อง: ต้องเป็น JSON object",
        "attachment_unsupported": "ไฟล์ {name} ({mime}) เป็นชนิดที่ผู้ให้บริการนี้ส่งไม่ได้ — ไฟล์เสียงและวิดีโอใช้ได้กับ Gemini ส่วน PDF ใช้ได้กับ Gemini หรือ Anthropic",
        "pairing_required": "อุปกรณ์นี้ยังไม่ได้จับคู่ — กรุณาใส่ Pairing Key",
        "pairing_rate_limited": "พยายามจับคู่มากเกินไป กรุณารอสักครู่แล้วลองใหม่",
        "pairing_key_invalid": "Pairing Key นี้ไม่ถูกต้อง หมดอายุ หรือถูกใช้ไปแล้ว",
        "auth_disabled": "ระบบจับคู่อุปกรณ์ปิดอยู่ — ตั้ง AI_WEB_AUTH=on เพื่อใช้ Pairing Key",
        "device_not_found": "ไม่พบอุปกรณ์",
        "cross_origin": "คำขอจากเว็บอื่นถูกปฏิเสธ",
        "body_too_large": "ข้อมูลที่ส่งมีขนาดใหญ่เกินกว่าที่อนุญาต",
        "tool_invalid_payload": "ข้อมูลเครื่องมือไม่ถูกต้อง",
        "tool_approval_invalid": "คำขออนุมัติไม่ถูกต้องหรือหมดอายุ กรุณาขอใหม่อีกครั้ง",
        "tool_failed": "ใช้เครื่องมือไม่สำเร็จ กรุณาตรวจสอบพารามิเตอร์แล้วลองใหม่",
        "log_clear_failed": "ลบ log ไม่สำเร็จ",
        "schedule_name_required": "กรุณาระบุชื่องานและ prompt",
        "schedule_invalid": "รูปแบบ schedule ไม่ถูกต้อง (ต้องเป็น cron 5 ช่อง)",
        "schedule_channel_invalid": "Discord Channel ID ต้องเป็นตัวเลข",
        "schedule_not_found": "ไม่พบงานตามเวลา",
        "schedule_running": "งานนี้กำลังทำงานอยู่",
        "skill_not_found": "ไม่พบ Skill",
        "skill_read_failed": "อ่าน Skill ไม่สำเร็จ",
        "skill_create_failed": "สร้าง Skill ไม่สำเร็จ",
        "skill_content_invalid": "เนื้อหา Skill ไม่ถูกต้องหรือใหญ่เกินขนาดที่อนุญาต",
        "skill_save_failed": "บันทึก Skill ไม่สำเร็จ",
        "skill_delete_failed": "ลบ Skill ไม่สำเร็จ",
        "history_not_found": "ไม่พบประวัติการสนทนา",
        "history_corrupt": "ไฟล์ประวัติเสียหายหรืออ่านไม่ได้ กรุณาตรวจสอบไฟล์ในโฟลเดอร์ history",
        "history_message_id_required": "ต้องระบุ message_id",
        "history_locked_edit": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนแก้ไข",
        "history_invalid": "รูปแบบประวัติไม่ถูกต้อง",
        "history_too_many_messages": "จำนวนข้อความมากเกินไป",
        "history_invalid_message": "รูปแบบข้อความไม่ถูกต้อง",
        "history_unsupported_role": "พบ role ที่ไม่อนุญาตในประวัติ",
        "history_locked_delete": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนลบ",
        "history_conflict": "เกิดความขัดแย้งข้อมูล: บันทึกถูกปรับปรุงโดยผู้อื่น กรุณาโหลดใหม่",
        "history_locked_save": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนบันทึกทับ",
        "models_fallback": "ดึงรายการโมเดลจาก API ไม่สำเร็จ ใช้รายการสำรองแทน",
        "discord_ids_invalid": "Discord ID ต้องเป็นตัวเลขเท่านั้น: {ids}",
        "custom_key_name_invalid": "ชื่อ Custom API key ไม่ถูกต้อง",
        "custom_key_nul": "ค่า Custom API key ต้องไม่มีอักขระ NUL",
        "update_mode_invalid": "โหมดอัปเดตไม่ถูกต้อง",
        "update_script_missing": "ไม่พบสคริปต์ update.sh ที่รันได้ในโฟลเดอร์โปรเจกต์",
        "update_busy": "มีการอัปเดตกำลังทำงานอยู่",
        "update_start_failed": "เริ่มอัปเดตไม่สำเร็จ กรุณาดู log ของระบบ",
        "chat_message_required": "กรุณาส่งข้อความ",
        "chat_failed": "ประมวลผลข้อความไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        "test_connection_failed": "{label}: เชื่อมต่อไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        "test_connection_hint": "ตรวจสอบ API key, โมเดล และ Base URL อีกครั้ง",
        "chat_busy": "{label} กำลังมีผู้ใช้หนาแน่นหรือถูกจำกัดอัตราการเรียก กรุณาลองใหม่อีกครั้ง หรือเลือกโมเดลอื่น",
        "chat_provider_error": "ผู้ให้บริการตอบกลับข้อผิดพลาด กรุณาตรวจสอบ API key และโมเดล",
        "chat_api_failed": "เรียก API ไม่สำเร็จ: {detail}",
        "rate_limited": "ทำรายการถี่เกินไป กรุณารอสักครู่แล้วลองใหม่",
    },
    "en": {
        "invalid_key": "{label} API key is invalid or unauthorized",
        "endpoint_missing": "{label} endpoint not found — check the Base URL",
        "anthropic_model_missing": "The selected Anthropic model was not found or is not available",
        "anthropic_model_error": "Anthropic could not call the selected model (HTTP {status})",
        "http_error": "{label} returned HTTP {status}",
        "connection_failed": "Could not connect to {label}: {error}",
        "missing_key": "{label} API key is not configured",
        "missing_model": "No {label} model is selected",
        "invalid_key_shape": "The {label} API key looks invalid (too short or a placeholder)",
        "tls_invalid_mode": "Invalid connection mode",
        "tls_cert_missing": "No certificate files found — create them with ./start_web.sh --make-cert <ip>, or point AI_WEB_TLS_CERT and AI_WEB_TLS_KEY in .env at existing files",
        "env_write_failed": "Could not write the .env file: {error}",
        "server_action_invalid": "Invalid server action",
        "server_script_missing": "start_web.sh was not found in the project folder",
        "server_busy": "A server control command is already running",
        "memory_schedule_invalid": "The memory cron expression is invalid",
        "memory_busy": "A memory consolidation run is already in progress",
        "memory_run_failed": "The memory run failed: {error}",
        "memory_not_found": "That memory entry does not exist",
        "memory_forget_failed": "Could not forget that memory entry",
        "memory_reindex_failed": "Could not rebuild the memory index: {error}",
        "server_action_failed": "Could not start the server control command: {error}",
        "gemini_key_missing": "No Gemini API key is configured — add one in Settings before using this feature",
        "gemini_capability_failed": "Could not check the Gemini key capabilities ({error})",
        "gemini_decisions_invalid": "Invalid Decisions API payload: input and at least one question (noul, choice, or score) are required",
        "gemini_agents_invalid": "Invalid Agents payload: agent and input are required",
        "gemini_live_failed": "Could not create a Live API token: {detail}",
        "gemini_request_failed": "Gemini API request failed: {detail}",
        "invalid_body": "Invalid request body: expected a JSON object",
        "attachment_unsupported": "{name} ({mime}) cannot be sent to this provider — audio and video files work with Gemini, and PDF files work with Gemini or Anthropic",
        "pairing_required": "This device is not paired yet. Enter a Pairing Key.",
        "pairing_rate_limited": "Too many pairing attempts. Please wait a few minutes and try again.",
        "pairing_key_invalid": "This Pairing Key is invalid, expired, or already used.",
        "auth_disabled": "Web auth is disabled. Set AI_WEB_AUTH=on to use pairing keys.",
        "device_not_found": "Device not found",
        "cross_origin": "A request from another origin was rejected",
        "body_too_large": "The request body is larger than allowed",
        "tool_invalid_payload": "Invalid tool payload",
        "tool_approval_invalid": "The approval request is invalid or expired; request it again",
        "tool_failed": "The tool could not run; check the parameters and try again",
        "log_clear_failed": "Could not clear the log",
        "schedule_name_required": "Provide a job name and prompt",
        "schedule_invalid": "Invalid schedule (a 5-field cron expression is required)",
        "schedule_channel_invalid": "The Discord Channel ID must be a number",
        "schedule_not_found": "Scheduled job not found",
        "schedule_running": "This job is already running",
        "skill_not_found": "Skill not found",
        "skill_read_failed": "Could not read the skill",
        "skill_create_failed": "Could not create the skill",
        "skill_content_invalid": "The skill content is invalid or larger than allowed",
        "skill_save_failed": "Could not save the skill",
        "skill_delete_failed": "Could not delete the skill",
        "history_not_found": "Conversation not found",
        "history_corrupt": "The history file is corrupt or unreadable; check the files in the history folder",
        "history_message_id_required": "message_id is required",
        "history_locked_edit": "This conversation is locked; unlock it before editing",
        "history_invalid": "Invalid conversation payload",
        "history_too_many_messages": "Too many messages",
        "history_invalid_message": "Invalid message format",
        "history_unsupported_role": "An unsupported role was found in the history",
        "history_locked_delete": "This conversation is locked; unlock it before deleting",
        "history_conflict": "Conflict: the record was updated elsewhere; reload it",
        "history_locked_save": "This conversation is locked; unlock it before saving over it",
        "models_fallback": "Could not fetch the model list from the API; using the fallback list",
        "discord_ids_invalid": "Discord IDs must be numbers only: {ids}",
        "custom_key_name_invalid": "Invalid Custom API key name",
        "custom_key_nul": "A Custom API key value must not contain NUL characters",
        "update_mode_invalid": "Invalid update mode",
        "update_script_missing": "No runnable update.sh script was found in the project folder",
        "update_busy": "An update is already running",
        "update_start_failed": "Could not start the update; check the system log",
        "chat_message_required": "Send a message",
        "chat_failed": "Could not process the message; try again",
        "test_connection_failed": "{label}: connection failed; try again",
        "test_connection_hint": "Check the API key, the model and the Base URL again",
        "chat_busy": "{label} is busy or rate-limited; try again or choose another model",
        "chat_provider_error": "The provider returned an error; check the API key and the model",
        "chat_api_failed": "API request failed: {detail}",
        "rate_limited": "Too many requests; wait a moment and try again",
    },
}


def normalize_language(value: Any) -> str:
    """Normalize a requested UI language to 'th' or 'en', defaulting to English."""
    return "th" if str(value or "").strip().lower().startswith("th") else "en"


def status_message(language: str, key: str, **kwargs: Any) -> str:
    """Format a localized readiness message from the shared status table."""
    messages = STATUS_MESSAGES.get(language) or STATUS_MESSAGES["en"]
    template = messages.get(key) or STATUS_MESSAGES["en"].get(key, key)
    return template.format(**kwargs)


# A simple in-process limiter for the expensive, state-changing endpoints.
# Pairing already has its own failure limiter; this keeps a paired device (or a
# script that got hold of a session) from hammering the provider API.
API_RATE_LIMITS: dict[str, list[float]] = {}
API_RATE_LOCK = threading.Lock()


def api_rate_limited(bucket: str, client: str, limit: int, window: float = 60.0) -> bool:
    """Return True when *client* already used its budget for *bucket*."""
    now = time.time()
    key = f"{bucket}|{client}"
    with API_RATE_LOCK:
        if len(API_RATE_LIMITS) > 2000:
            API_RATE_LIMITS.clear()
        stamps = [stamp for stamp in API_RATE_LIMITS.get(key, []) if now - stamp < window]
        if len(stamps) >= limit:
            API_RATE_LIMITS[key] = stamps
            return True
        stamps.append(now)
        API_RATE_LIMITS[key] = stamps
    return False


# Per-minute budgets for the endpoints that cost money or touch the machine.
API_RATE_BUDGETS = {"chat": 30, "tools": 60, "test": 10}


def rate_limit_response(bucket: str):
    """Answer 429 when the caller exceeded the budget for *bucket*.

    A paired device is identified by its session id, so a spoofed
    X-Forwarded-For cannot hand one caller a fresh budget on every request.
    """
    session = current_auth_session() or {}
    client = str(session.get("id") or request.remote_addr or "unknown")
    if not api_rate_limited(bucket, client, API_RATE_BUDGETS[bucket]):
        return None
    log_event("security.rate_limited", "Rejected a request over the rate budget", bucket=bucket)
    return jsonify({"ok": False, "error": status_message(request_language(), "rate_limited")}), 429


def request_language(allow_body: bool = True) -> str:
    """Pick the response language the current page asked for."""
    value = request.headers.get("X-Interface-Language")
    if not value:
        value = request.args.get("lang")
    if not value and allow_body:
        # Reading an oversized body raises RequestEntityTooLarge again, which
        # would turn the 413 handler (or a rejection made while handling one)
        # into a 500, so the body is only parsed when it fits and cannot raise.
        limit = app.config.get("MAX_CONTENT_LENGTH")
        length = request.content_length
        if not (limit and length and length > limit):
            try:
                body = request.get_json(silent=True)
            except HTTPException:
                body = None
            if isinstance(body, dict):
                value = body.get("lang")
    return normalize_language(value)


def provider_key_check(provider: str, settings: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Check credentials and, for Anthropic, the selected model's real usability."""
    provider = normalize_provider(provider)
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base_url = get_base_url(provider, settings)
    model = str(settings.get("model") or "").strip()
    cache_key = f"{provider}|{base_url}|{model}|{language}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < STATUS_CACHE_TTL and same_secret(cached[1], key):
        return {**cached[2], "cached": True}
    result: dict[str, Any]
    try:
        # The key must not travel in clear text or follow a redirect here either;
        # the same guard protects the model-list fetch.
        ensure_secure_model_endpoint(base_url or "https://api.openai.com/v1")
        if provider == "gemini":
            response = requests.get(
                f"{base_url}/models",
                params={"key": key},
                timeout=20,
                allow_redirects=False,
            )
        elif provider == "anthropic":
            response = requests.get(
                f"{base_url}/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=20,
                allow_redirects=False,
            )
        else:
            response = requests.get(
                f"{base_url or 'https://api.openai.com/v1'}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=20,
                allow_redirects=False,
            )
        if 300 <= response.status_code < 400:
            raise RuntimeError("The endpoint answered with a redirect; the API key is not forwarded across it")
        if response.status_code in {401, 403}:
            result = {"ready": False, "reason": status_message(language, "invalid_key", label=label), "status": response.status_code}
        elif response.status_code == 404:
            result = {"ready": False, "reason": status_message(language, "endpoint_missing", label=label), "status": 404}
        elif response.ok and provider == "anthropic":
            probe = requests.post(
                f"{base_url}/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "OK"}],
                },
                timeout=20,
                allow_redirects=False,
            )
            if 300 <= probe.status_code < 400:
                raise RuntimeError("The endpoint answered with a redirect; the API key is not forwarded across it")
            if probe.status_code in {401, 403}:
                result = {"ready": False, "reason": status_message(language, "invalid_key", label=label), "status": probe.status_code}
            elif probe.status_code == 404:
                result = {"ready": False, "reason": status_message(language, "anthropic_model_missing"), "status": 404}
            elif probe.ok:
                result = {"ready": True, "reason": "", "status": probe.status_code}
            else:
                result = {"ready": False, "reason": status_message(language, "anthropic_model_error", status=probe.status_code), "status": probe.status_code}
        elif response.ok:
            result = {"ready": True, "reason": "", "status": response.status_code}
        else:
            result = {"ready": False, "reason": status_message(language, "http_error", label=label, status=response.status_code), "status": response.status_code}
    except RuntimeError as exc:
        # A refused insecure endpoint or a redirect is a configuration result,
        # not a connection failure.
        result = {"ready": False, "reason": str(exc)[:300], "status": None}
    except requests.RequestException as exc:
        result = {"ready": False, "reason": status_message(language, "connection_failed", label=label, error=exc.__class__.__name__), "status": None}
    STATUS_CACHE[cache_key] = (time.time(), key, result)
    return {**result, "cached": False}


def provider_readiness(settings: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Check locally, then remotely, whether the selected provider and model are usable."""
    provider = normalize_provider(settings.get("provider"))
    model = str(settings.get("model") or "").strip()
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base = {"provider": provider, "model": model}
    if not key:
        return {**base, "ready": False, "reason": status_message(language, "missing_key", label=label), "checked": "local"}
    if not model:
        return {**base, "ready": False, "reason": status_message(language, "missing_model", label=label), "checked": "local"}
    if not key_looks_plausible(key, provider, get_base_url(provider, settings)):
        return {**base, "ready": False, "reason": status_message(language, "invalid_key_shape", label=label), "checked": "local"}
    check = provider_key_check(provider, settings, language)
    return {**base, "ready": check["ready"], "reason": check["reason"], "checked": "api", "cached": check.get("cached", False)}


def gemini_base_url(settings: dict[str, Any]) -> str:
    """Return the Gemini endpoint used by discovery and the Gemini tools.

    ``base_url`` belongs to the active chat provider, so it is only reused when
    Gemini itself is that provider. Otherwise the saved Gemini key would travel
    to an unrelated OpenAI-compatible endpoint.
    """
    stored = str(settings.get("base_url") or "").strip().rstrip("/")
    if stored and normalize_provider(settings.get("provider")) == "gemini":
        return stored
    return PROVIDER_BASE_URLS["gemini"].rstrip("/")


def gemini_post(
    path: str,
    settings: dict[str, Any],
    key: str,
    payload: dict[str, Any],
    timeout: float,
) -> requests.Response:
    """POST to the Gemini API without handing the key to a redirect target.

    The key travels in ``x-goog-api-key``, which requests keeps on a
    cross-origin redirect, so the call must be HTTPS and a 3xx answer is a
    failure instead of a new destination.
    """
    url = f"{gemini_base_url(settings)}{path}"
    ensure_secure_model_endpoint(url)
    response = requests.post(
        url,
        headers={"x-goog-api-key": key},
        json=payload,
        timeout=timeout,
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise RuntimeError(
            f"The endpoint answered HTTP {response.status_code} (redirect) — the API key is not forwarded across the redirect"
        )
    response.raise_for_status()
    return response


def gemini_model_metadata(settings: dict[str, Any], timeout: float = 30) -> list[dict[str, Any]]:
    """Fetch full Gemini model metadata, including supported generation methods."""
    key = get_api_key("gemini", settings)
    if not key:
        raise RuntimeError("No Gemini API key is configured")
    models: list[dict[str, Any]] = []
    params = {"key": key, "pageSize": "1000"}
    seen_tokens: set[str] = set()
    # pageSize only bounds a single page, so follow nextPageToken until the
    # catalog ends; a repeated token would otherwise loop forever.
    for _ in range(20):
        response = provider_models_get(
            f"{gemini_base_url(settings)}/models",
            params=params,
            timeout=timeout,
        )
        payload = response.json()
        page = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(page, list):
            models.extend(item for item in page if isinstance(item, dict))
        token = payload.get("nextPageToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token or token in seen_tokens:
            break
        seen_tokens.add(token)
        params = {**params, "pageToken": token}
    return models


def gemini_feature_groups(models: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Split Gemini models into the feature groups shown in Settings."""
    groups: dict[str, list[str]] = {name: [] for name in ("multimodal", "live", "decisions", "other")}
    for item in models:
        name = str(item.get("name") or "").removeprefix("models/")
        if not name:
            continue
        methods = {str(method) for method in item.get("supportedGenerationMethods") or []}
        lowered = name.lower()
        if "generateContent" in methods:
            groups["multimodal"].append(name)
        if "bidiGenerateContent" in methods:
            groups["live"].append(name)
        if "decision" in lowered or {"decide", "generateDecision"} & methods:
            groups["decisions"].append(name)
        remaining = methods - {
            "generateContent",
            "bidiGenerateContent",
            "countTokens",
            "createCachedContent",
            "batchGenerateContent",
        }
        if remaining or any(tag in lowered for tag in ("embedding", "imagen", "veo", "lyria", "tts")):
            groups["other"].append(name)
    return groups


def gemini_agent_presets(settings: dict[str, Any]) -> tuple[list[str], bool]:
    """Return managed agent ids, using the live list when the API exposes one."""
    key = get_api_key("gemini", settings)
    names = list(GEMINI_AGENT_PRESETS)
    if not key:
        return names, False
    try:
        response = provider_models_get(
            f"{gemini_base_url(settings)}/agents",
            headers={"x-goog-api-key": key},
            timeout=15,
        )
        payload = response.json()
        items = None
        if isinstance(payload, dict):
            items = payload.get("agents") or payload.get("data")
        listed = [
            str(item.get("id") or item.get("name") or "").removeprefix("agents/")
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        ]
        listed = [name for name in listed if name]
        # Presets stay suggestions: only a non-empty /agents answer proves the
        # key can reach managed agents.
        return (listed or names), bool(listed)
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        return names, False


def gemini_capabilities(settings: dict[str, Any], language: str = "en", force: bool = False) -> dict[str, Any]:
    """Report which Gemini feature groups the configured key can reach."""
    global GEMINI_CAPABILITY_PROBE
    key = get_api_key("gemini", settings)
    if not key:
        return {"ready": False, "error": status_message(language, "gemini_key_missing"), "groups": {}}
    cache_key = gemini_base_url(settings)
    now = time.time()
    with GEMINI_CAPABILITY_LOCK:
        cached = GEMINI_CAPABILITY_CACHE.get(cache_key)
        if (
            cached
            and not force
            and now - cached[0] < GEMINI_CAPABILITY_CACHE_TTL
            and same_secret(cached[1], key)
        ):
            # The probe runs once in one language, so a cached failure is
            # re-rendered for this request instead of showing the other one.
            if cached[2].get("error_key"):
                return {
                    **cached[2],
                    "error": status_message(
                        language, cached[2]["error_key"], error=cached[2].get("error_arg", "")
                    ),
                }
            return cached[2]
        # Claim the probe so a slow, older probe cannot publish over this one.
        GEMINI_CAPABILITY_PROBE += 1
        probe_id = GEMINI_CAPABILITY_PROBE
    try:
        models = gemini_model_metadata(settings)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        result = {
            "ready": False,
            "error": status_message(language, "gemini_capability_failed", error=exc.__class__.__name__),
            "error_key": "gemini_capability_failed",
            "error_arg": exc.__class__.__name__,
            "groups": {},
        }
        with GEMINI_CAPABILITY_LOCK:
            if probe_id == GEMINI_CAPABILITY_PROBE:
                GEMINI_CAPABILITY_CACHE[cache_key] = (now, key, result)
        return result
    raw_groups = gemini_feature_groups(models)
    agent_names, agents_verified = gemini_agent_presets(settings)
    groups = {
        name: {
            "ready": bool(raw_groups.get(name)),
            "models": raw_groups.get(name, [])[:12],
            "count": len(raw_groups.get(name, [])),
        }
        for name in ("multimodal", "live", "decisions", "other")
    }
    groups["agents"] = {
        # Managed agents use the same key; the probe only discovers saved agent
        # ids, so an unreachable /agents route does not mean the feature is off.
        "ready": bool(key),
        "verified": agents_verified,
        "models": agent_names[:12],
        "count": len(agent_names),
    }
    live_models = raw_groups.get("live", [])
    # Transcription and translation Live models cannot hold a voice chat, so
    # prefer a plain conversational ``*-live`` model for the default.
    conversation_live = [
        name for name in live_models
        if "transcribe" not in name.lower() and "translate" not in name.lower()
    ]
    live_default = next(
        (name for name in conversation_live if name.lower().endswith("-live")),
        next(
            (name for name in conversation_live if "native-audio" in name.lower()),
            conversation_live[0] if conversation_live else "",
        ),
    )
    if live_models and not conversation_live:
        # Only transcription/translation Live models are reachable, so voice
        # chat is unavailable instead of silently using one of them.
        groups["live"] = {"ready": False, "models": [], "count": 0}
    result = {
        "ready": bool(models),
        "groups": groups,
        "live_default": live_default,
        "decision_default": next(
            (name for name in raw_groups.get("decisions", []) if "decision" in name.lower()),
            GEMINI_DECISION_MODEL,
        ),
    }
    with GEMINI_CAPABILITY_LOCK:
        if probe_id == GEMINI_CAPABILITY_PROBE:
            GEMINI_CAPABILITY_CACHE[cache_key] = (now, key, result)
    return result


def attachment_payload(value: Any) -> dict[str, str] | None:
    """Validate an inline multimodal attachment sent by the browser."""
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()[:200]
    mime_type = str(value.get("mime_type") or "").strip().lower()[:120]
    data = value.get("data")
    if not name or not mime_type or not isinstance(data, str) or not data:
        return None
    if mime_type not in MULTIMODAL_MIME_TYPES and not mime_type.startswith(MULTIMODAL_MIME_PREFIXES):
        return None
    if len(data) > MULTIMODAL_MAX_BYTES * 2:
        return None
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return None
    if not 0 < len(decoded) <= MULTIMODAL_MAX_BYTES:
        return None
    return {"name": name, "mime_type": mime_type, "data": data}


def clean_messages(messages: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep text and validated inline attachments, then prepend the system prompt."""
    result: list[dict[str, Any]] = [{"role": "system", "content": settings.get("system_prompt", "")}] if settings.get("system_prompt") else []
    for item in messages:
        content = item.get("content", "")
        attachment = attachment_payload(item.get("attachment"))
        if attachment:
            result.append({"role": item.get("role", "user"), "content": content, "attachment": attachment})
            continue
        legacy = item.get("attachment")
        if isinstance(legacy, dict) and legacy.get("name") and legacy.get("content"):
            content = f"{content}\n\n[Attachment: {legacy['name']}]\n```\n{legacy['content']}\n```"
        result.append({"role": item.get("role", "user"), "content": content})
    return result


def gemini_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Gemini content parts, sending binary attachments inline."""
    parts: list[dict[str, Any]] = []
    text = str(message.get("content") or "")
    attachment = message.get("attachment")
    if text:
        parts.append({"text": text})
    if isinstance(attachment, dict) and attachment.get("data"):
        if not text:
            parts.append({"text": f"[Attachment: {attachment['name']}]"})
        parts.append({"inlineData": {"mimeType": attachment["mime_type"], "data": attachment["data"]}})
    return parts or [{"text": ""}]


def openai_content(message: dict[str, Any]) -> Any:
    """Map an attachment to an OpenAI image part; other binaries stay text-only."""
    attachment = message.get("attachment")
    text = str(message.get("content") or "")
    if isinstance(attachment, dict) and str(attachment.get("mime_type") or "").startswith("image/"):
        parts: list[dict[str, Any]] = []
        if text:
            parts.append({"type": "text", "text": text})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{attachment['mime_type']};base64,{attachment['data']}"}})
        return parts
    return text


def anthropic_content(message: dict[str, Any]) -> Any:
    """Map an attachment to an Anthropic image/document block."""
    attachment = message.get("attachment")
    text = str(message.get("content") or "")
    if not isinstance(attachment, dict) or not attachment.get("data"):
        return text
    mime_type = attachment["mime_type"]
    if mime_type.startswith("image/"):
        block: dict[str, Any] = {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": attachment["data"]}}
    elif mime_type == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": mime_type, "data": attachment["data"]}}
    else:
        return f"{text}\n\n[Attachment: {attachment['name']}]\n({mime_type} files work with Gemini only)"
    blocks: list[dict[str, Any]] = [block]
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def agent_profile_prompt(settings: dict[str, Any]) -> str:
    """Turn the user-configured agent profile into stable runtime guidance."""
    language = {"auto": "Reply in the user's language", "th": "Reply in Thai", "en": "Reply in English"}.get(str(settings.get("response_language", "auto")), "Reply in the user's language")
    questions = "Ask back when the information is missing or the request is ambiguous" if settings.get("ask_clarifying_questions", True) else "Avoid asking back and state the assumptions used"
    markdown = "Use Markdown when it improves readability" if settings.get("use_markdown", True) else "Do not use complex Markdown"
    return "Agent profile guidance:\n" + "\n".join((
        f"- Name to introduce yourself with: {str(settings.get('agent_name') or 'Mux')[:80]}",
        f"- Role: {str(settings.get('agent_role') or '')[:500]}",
        f"- Response tone: {str(settings.get('response_style') or '')[:500]}",
        f"- Language: {language}", f"- Format: {markdown}", f"- Asking for more information: {questions}",
    ))


def normalize_usage(usage: dict[str, Any] | None, input_key: str, output_key: str, total_key: str | None) -> dict[str, int] | None:
    """Map provider-specific usage fields to the fields shown in the UI."""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get(input_key)
    output_tokens = usage.get(output_key)
    total_tokens = usage.get(total_key) if total_key else None
    if not isinstance(input_tokens, int) and not isinstance(output_tokens, int) and not isinstance(total_tokens, int):
        return None
    result = {}
    if isinstance(input_tokens, int):
        result["input_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        result["output_tokens"] = output_tokens
    if isinstance(total_tokens, int):
        result["total_tokens"] = total_tokens
    elif result:
        result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
    return result


def is_openai_reasoning_model(provider: str, model: str) -> bool:
    """Return whether a model on an OpenAI-compatible endpoint takes reasoning_effort.

    OpenRouter, Groq and the Hugging Face router all speak the OpenAI chat
    completions shape, and their reasoning models accept reasoning_effort too.
    Routers prefix the owner (``openai/gpt-5``, ``openai/gpt-oss-120b``), so the
    check looks at the part after the last slash.
    """
    if normalize_provider(provider) not in {"openai", "or", "groq", "hf"}:
        return False
    name = str(model or "").strip().lower().rsplit("/", 1)[-1]
    return bool(re.match(r"^(?:o[1-9](?:-|$)|gpt-5|gpt-oss)", name))


def rejects_sampling_params(provider: str, model: str) -> bool:
    """Return whether the endpoint rejects temperature/top_p for this model.

    Only the native OpenAI endpoint's reasoning models reject the sampling
    fields. The same model names served by OpenRouter, Groq, or the Hugging
    Face router accept them (Groq's gpt-oss examples send a temperature), so
    this is decided by exact model id on the native provider instead of
    reusing the reasoning-effort classifier.
    """
    if normalize_provider(provider) != "openai":
        return False
    name = str(model or "").strip().lower()
    return bool(re.match(r"^(?:o[1-9](?:-|$)|gpt-5)", name))


def call_openai(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one chat completion request to an OpenAI-compatible endpoint."""
    key = get_api_key(settings["provider"], settings)
    base_url = get_base_url(settings["provider"], settings)
    ensure_secure_model_endpoint(f"{base_url}/chat/completions")
    # A local model server (llama.cpp's llama-server, Ollama) usually needs no
    # key. Only a loopback endpoint may run without one: a remote endpoint that
    # silently accepted an empty key would fail anyway, and this keeps the rest
    # of the app honest about needing credentials.
    if not key and not endpoint_is_loopback(base_url):
        raise RuntimeError("No API key is configured")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    model = str(settings["model"])
    reasoning_model = is_openai_reasoning_model(settings["provider"], model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": item.get("role", "user"), "content": openai_content(item)} for item in messages],
    }
    if reasoning_model and normalize_provider(settings["provider"]) == "openai":
        # Only the native OpenAI endpoint renamed the output cap to
        # max_completion_tokens; OpenAI-compatible routers still expect
        # max_tokens.
        payload["max_completion_tokens"] = settings["max_tokens"]
    else:
        payload["max_tokens"] = settings["max_tokens"]
    # Sampling support is a different question from reasoning-effort support:
    # Groq's gpt-oss models take reasoning_effort and still accept the
    # configured temperature/top_p, while native OpenAI reasoning models reject
    # both fields.
    if not rejects_sampling_params(settings["provider"], model):
        payload["temperature"] = settings["temperature"]
        payload["top_p"] = settings["top_p"]
    if reasoning_model and settings.get("thinking_level") in {"low", "medium", "high"}:
        payload["reasoning_effort"] = settings["thinking_level"]
    response = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=90,
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise RuntimeError("The endpoint answered with a redirect; the API key is not forwarded across it")
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"], normalize_usage(data.get("usage"), "prompt_tokens", "completion_tokens", "total_tokens")


def call_gemini(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one generateContent request to Gemini with thinking options."""
    key = get_api_key("gemini", settings)
    if not key:
        raise RuntimeError("No Gemini API key is configured")

    contents: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "system":
            continue
        role = "model" if message["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": gemini_parts(message)})

    model = settings["model"]
    generation_config = {
        "temperature": settings["temperature"],
        "topP": settings["top_p"],
        "maxOutputTokens": settings["max_tokens"],
    }
    thinking_level = settings.get("thinking_level", "off")
    if thinking_level in {"low", "medium", "high"}:
        # Gemini 2.5 takes a token budget, Gemini 3 takes a named level, and
        # anything older has no thinking support at all. Sending the wrong
        # field makes the API reject the whole request.
        if model.startswith("gemini-2.5"):
            generation_config["thinkingConfig"] = {"thinkingBudget": {"low": 1024, "medium": 4096, "high": 8192}[thinking_level]}
        elif model.startswith("gemini-3"):
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    request_url = f"{get_base_url('gemini', settings)}/models/{model}:generateContent"
    ensure_secure_model_endpoint(request_url)
    request_payload = {"contents": contents, "generationConfig": generation_config}
    system_instruction = next((message["content"] for message in messages if message["role"] == "system"), "")
    if system_instruction:
        request_payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    for attempt in range(3):
        response = requests.post(
            request_url,
            params={"key": key},
            json=request_payload,
            timeout=90,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise RuntimeError("The endpoint answered with a redirect; the API key is not forwarded across it")
        if response.status_code not in {429, 503} or attempt == 2:
            break
        time.sleep(1.5 * (2**attempt))
    response.raise_for_status()
    data = response.json()
    usage = data.get("usageMetadata", {})
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    content_parts = (candidate.get("content") or {}).get("parts") or []
    # A blocked or truncated candidate can come back without a text part; read
    # the first text block instead of assuming parts[0]["text"] exists.
    text = next(
        (
            str(part.get("text") or "")
            for part in content_parts
            if isinstance(part, dict) and part.get("text")
        ),
        "",
    )
    if not text:
        finish_reason = str(candidate.get("finishReason") or "unknown")
        raise RuntimeError(f"Gemini response contained no text (finishReason={finish_reason})")
    return text, normalize_usage(
        usage, "promptTokenCount", "candidatesTokenCount", "totalTokenCount"
    )


def anthropic_model_version(model: str) -> tuple[int, int] | None:
    """Return the Claude version encoded in a model id, or None."""
    match = re.search(
        r"claude-(?:[a-z]+-)?(\d+)(?:-(\d+))?", str(model or "").strip().lower()
    )
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def anthropic_adaptive_thinking_supported(model: str) -> bool:
    """Return whether the model takes adaptive thinking (Claude 4.7 and later)."""
    version = anthropic_model_version(model)
    return version is not None and version >= (4, 7)


def anthropic_thinking_supported(model: str) -> bool:
    """Return whether an Anthropic model accepts manual extended thinking.

    Claude 4.7 and later reject ``thinking.type: "enabled"`` with a 400 error
    and use adaptive thinking instead, so they are excluded here.
    """
    version = anthropic_model_version(model)
    return version is not None and (3, 7) <= version < (4, 7)


def call_anthropic(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one messages request to Anthropic with the configured settings."""
    key = get_api_key("anthropic", settings)
    if not key:
        raise RuntimeError("No Anthropic API key is configured")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    payload: dict[str, Any] = {
        "model": settings["model"],
        "system": system,
        "messages": [
            {"role": item.get("role", "user"), "content": anthropic_content(item)}
            for item in messages
            if item.get("role") != "system"
        ],
        "max_tokens": settings["max_tokens"],
        "temperature": settings["temperature"],
    }
    thinking_level = settings.get("thinking_level", "off")
    if thinking_level in {"low", "medium", "high"}:
        if anthropic_adaptive_thinking_supported(settings["model"]):
            # Claude 4.7 and later reject a manual budget with a 400 error; they
            # take adaptive thinking with the depth steered by effort instead.
            payload["thinking"] = {"type": "adaptive"}
            payload["output_config"] = {"effort": thinking_level}
            payload.pop("temperature", None)
        elif anthropic_thinking_supported(settings["model"]):
            budget = {"low": 1024, "medium": 4096, "high": 8192}[thinking_level]
            # Extended thinking requires max_tokens > budget_tokens and rejects a
            # custom temperature, so leave temperature unset and grow the cap.
            payload["max_tokens"] = max(int(settings["max_tokens"]), budget + 1024)
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload.pop("temperature", None)
    anthropic_url = f"{get_base_url('anthropic', settings)}/messages"
    ensure_secure_model_endpoint(anthropic_url)
    response = requests.post(
        anthropic_url,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json=payload,
        timeout=90,
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise RuntimeError("The endpoint answered with a redirect; the API key is not forwarded across it")
    response.raise_for_status()
    data = response.json()
    usage = data.get("usage", {})
    # With thinking enabled the first content block is a thinking block, so
    # read the first text block instead of assuming content[0] is the answer.
    text = next(
        (
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ),
        "",
    )
    if not text:
        # An end_turn response with no text block is valid for the API but
        # useless here: returning an empty string would surface a blank reply.
        raise RuntimeError("Anthropic response contained no text block")
    return text, normalize_usage(usage, "input_tokens", "output_tokens", None)


def call_provider(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Dispatch one chat turn to the provider selected in settings."""
    provider = settings["provider"].lower()
    if provider == "gemini":
        return call_gemini(messages, settings)
    if provider == "anthropic":
        return call_anthropic(messages, settings)
    return call_openai(messages, settings)


def get_discord_token(settings: dict[str, Any] | None = None) -> str:
    """Return the Discord bot token from settings or the environment."""
    settings = settings if settings is not None else load_settings()
    configured = str(settings.get("discord_token") or "").strip()
    return configured or os.getenv("DISCORD_BOT_TOKEN", "").strip()


def discord_status() -> dict[str, Any]:
    """Report whether the Discord bot is enabled, configured, and connected."""
    token = get_discord_token()
    return {
        "enabled": bool(load_settings().get("discord_enabled")),
        "configured": bool(token),
        "connected": bool(DISCORD_BOT and getattr(DISCORD_BOT, "is_ready", lambda: False)()),
    }


def split_discord_message(text: str, limit: int = 2000) -> list[str]:
    """Split a long reply into Discord-sized message chunks."""
    text = str(text or "")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or ["(No response text)"]


def stop_discord_bot() -> None:
    """Ask the running Discord client to close, if it is connected."""
    if DISCORD_BOT is not None and DISCORD_LOOP is not None and not DISCORD_LOOP.is_closed():
        try:
            DISCORD_LOOP.call_soon_threadsafe(lambda: __import__("asyncio").create_task(DISCORD_BOT.close()))
        except RuntimeError:
            pass


def start_discord_bot() -> None:
    """Run the optional Discord client in a daemon thread beside Flask."""
    global DISCORD_BOT, DISCORD_THREAD, DISCORD_LOOP, DISCORD_ACTIVE_TOKEN
    settings = load_settings()
    token = get_discord_token(settings)
    if not settings.get("discord_enabled") or not token:
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive() and same_secret(DISCORD_ACTIVE_TOKEN, token):
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive():
        stop_discord_bot()
    try:
        import discord
    except ImportError:
        log_event("discord.error", "discord.py is not installed")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    prefix = str(settings.get("discord_prefix") or "!ai").strip() or "!ai"
    commands_synced = False
    # A reconnect fires READY again, so the pass is serialised and records each
    # guild only after its own cleanup returned.
    sync_state_lock = asyncio.Lock()
    cleared_guilds: set[int] = set()
    GUILD_CLEAR_ATTEMPTS = 3

    class AccessControlledCommandTree(discord.app_commands.CommandTree):
        """Reject slash commands from channels or users outside the allowlists."""

        async def interaction_check(self, interaction: Any) -> bool:
            if discord_access_allowed(
                load_settings(),
                getattr(interaction, "channel_id", ""),
                getattr(getattr(interaction, "user", None), "id", ""),
            ):
                return True
            await interaction.response.send_message(
                "This bot is limited to specific users or channels.",
                ephemeral=True,
            )
            return False

    class AIClient(discord.Client):
        async def on_ready(self) -> None:
            """Register the global commands and remove legacy guild copies."""
            nonlocal commands_synced
            uncleared = 0
            # Overlapping READY events must not write the same guild twice, so
            # the whole pass runs under one lock and rechecks the per-guild state.
            async with sync_state_lock:
                if not commands_synced:
                    try:
                        await command_tree.sync()
                        commands_synced = True
                        log_event("discord.commands", "Registered the Discord slash commands")
                    except Exception as exc:
                        log_event("discord.error", "Could not register the Discord slash commands", error=str(exc))
                # Global commands are the only registration, so the guild-scoped
                # copies left by older versions must go. If the global sync
                # failed, keep them: no commands is worse than duplicates.
                if commands_synced:
                    pending = [guild for guild in self.guilds if guild.id not in cleared_guilds]
                    failures: list[str] = []
                    cleared_now = 0
                    for guild in pending:
                        last_error = ""
                        for attempt in range(1, GUILD_CLEAR_ATTEMPTS + 1):
                            try:
                                await remove_legacy_guild_commands(guild)
                            except Exception as exc:
                                last_error = f"{guild.id}: {exc}"
                                if attempt < GUILD_CLEAR_ATTEMPTS:
                                    await asyncio.sleep(2 ** (attempt - 1))
                            else:
                                cleared_guilds.add(guild.id)
                                cleared_now += 1
                                break
                        else:
                            failures.append(last_error)
                    if pending:
                        details: dict[str, Any] = {"servers": len(self.guilds), "cleared_now": cleared_now}
                        if failures:
                            details["failed"] = "; ".join(failures)[:300]
                        log_event("discord.commands", "Cleared duplicate guild slash commands", **details)
                    # A guild that never succeeded is retried on the next READY event.
                    uncleared = sum(1 for guild in self.guilds if guild.id not in cleared_guilds)
            if uncleared:
                log_event(
                    "discord.error",
                    "Could not clear guild slash commands on some guilds; retrying on the next connection",
                    uncleared=uncleared,
                )
            settings = load_settings()
            schedule_model_list_refresh(settings.get("provider", "openai"), settings)
            log_event("discord.connected", "Discord bot connected", user=str(self.user))

        async def on_message(self, message: Any) -> None:
            """Reply to mentions, prefixed messages, and DMs through the agent."""
            if message.author == self.user or getattr(message.author, "bot", False):
                return
            if not discord_access_allowed(
                load_settings(),
                getattr(message.channel, "id", ""),
                getattr(message.author, "id", ""),
            ):
                log_event(
                    "discord.ignored",
                    "Ignored a Discord message outside the allowed users or channels",
                    channel=str(getattr(message.channel, "id", "")),
                    user=str(getattr(message.author, "id", "")),
                )
                return
            content = str(message.content or "").strip()
            mentioned = self.user and self.user in message.mentions
            if mentioned:
                content = re.sub(rf"<@!?{self.user.id}>", "", content).strip()
            elif content.lower().startswith(prefix.lower()):
                content = content[len(prefix):].strip()
            elif message.guild is not None:
                return
            if not content:
                await message.reply(f"Type a message after {prefix} or mention the bot to start chatting.")
                return

            answer = await ask_agent(
                str(message.channel.id),
                content,
                getattr(message.channel, "name", "Discord"),
                allow_schedule_tools=member_is_admin(message.author),
            )
            for chunk in split_discord_message(answer):
                await message.reply(chunk, mention_author=False)

    client = AIClient(intents=intents)
    command_tree = AccessControlledCommandTree(client)

    async def remove_legacy_guild_commands(guild: Any) -> None:
        """Remove the guild-scoped copies left by older versions."""
        command_tree.clear_commands(guild=guild)
        await command_tree.sync(guild=guild)

    def member_is_admin(member: Any) -> bool:
        """Return whether a guild member has server administrator rights."""
        permissions = getattr(member, "guild_permissions", None)
        return bool(getattr(permissions, "administrator", False))

    def is_server_admin(interaction: Any) -> bool:
        """Return whether the interaction author has server administrator rights."""
        return member_is_admin(getattr(interaction, "user", None))

    async def require_server_admin(interaction: Any) -> bool:
        """Reject an interaction unless the author is a server administrator."""
        if is_server_admin(interaction):
            return True
        await interaction.response.send_message("This command is available to server administrators only.", ephemeral=True)
        return False

    async def check_model_availability(provider: str, model: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Check a provider and model off the event loop without saving settings."""
        probe_settings = dict(settings)
        probe_settings["provider"] = provider
        probe_settings["model"] = model
        return await asyncio.to_thread(provider_readiness, probe_settings, "en")

    async def ask_agent(
        context_key: str,
        content: str,
        channel_title: str = "Discord",
        allow_schedule_tools: bool = False,
    ) -> str:
        """Run one agent turn while keeping a short per-channel conversation.

        Schedule tools change what the server runs on a timer, so they are only
        auto-approved for a member who can already administer the server.
        """
        with DISCORD_CONTEXT_LOCK:
            context = DISCORD_CONTEXTS.setdefault(context_key, deque(maxlen=12))
            context.append({"role": "user", "content": content, "message_id": str(uuid.uuid4())})
            messages = list(context)
        try:
            settings_for_chat = load_settings()
            settings_for_chat["system_prompt"] = "\n\n".join(
                part for part in (
                    settings_for_chat.get("system_prompt", ""),
                    agent_profile_prompt(settings_for_chat),
                    selected_skill_prompt(settings_for_chat),
                    TOOL_INSTRUCTIONS,
                ) if part
            )
            messages = clean_messages(messages, settings_for_chat)
            fallback_used = ""
            try:
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
            except requests.HTTPError as primary_error:
                channel_fallbacks = settings_for_chat.get("discord_fallback_models")
                channel_fallback = channel_fallbacks.get(context_key) if isinstance(channel_fallbacks, dict) else ""
                fallback_model = str(channel_fallback or settings_for_chat.get("fallback_model") or "").strip()
                fallback_provider = normalize_provider(settings_for_chat.get("fallback_provider"))
                primary_provider = normalize_provider(settings_for_chat.get("provider"))
                status_code = primary_error.response.status_code if primary_error.response is not None else None
                same_target = fallback_model == settings_for_chat.get("model") and (
                    bool(channel_fallback) or fallback_provider == primary_provider
                )
                can_fallback = (
                    bool(settings_for_chat.get("fallback_enabled"))
                    and fallback_model
                    and not same_target
                    and status_code in {400, 404, 429, 500, 502, 503, 504}
                )
                if not can_fallback:
                    raise
                if not channel_fallback:
                    if fallback_provider != primary_provider:
                        settings_for_chat["base_url"] = ""
                    settings_for_chat["provider"] = fallback_provider
                settings_for_chat["model"] = fallback_model
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
                fallback_used = fallback_model
            for _ in range(3):
                try:
                    tool_request = parse_tool_request(answer)
                except ValueError:
                    tool_request = None
                if not tool_request:
                    break
                if tool_request["name"] not in {"create_schedule", "update_schedule"}:
                    break
                if not allow_schedule_tools:
                    log_event(
                        "discord.schedule_denied",
                        "Rejected a scheduled job created by a user without administrator rights",
                        channel=context_key,
                    )
                    stripped = TOOL_CALL_BLOCK_PATTERN.sub("", answer).strip()
                    answer = stripped or "Creating or editing scheduled jobs is available to server administrators only."
                    break
                result = await asyncio.to_thread(
                    run_local_tool,
                    tool_request["name"],
                    tool_request["arguments"],
                    True,
                )
                messages.extend([
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": f"Scheduled job result:\n{json.dumps(result, ensure_ascii=False)}\n\nReply in plain text, confirming the name, the time, the Cron expression and what the AI will do. Never show a tool_call or JSON."},
                ])
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
            with DISCORD_CONTEXT_LOCK:
                DISCORD_CONTEXTS[context_key].append({
                    "role": "assistant",
                    "content": answer,
                    "message_id": str(uuid.uuid4()),
                })
                conversation_id = DISCORD_CONVERSATION_IDS.setdefault(context_key, str(uuid.uuid4()))
                history_messages = list(DISCORD_CONTEXTS[context_key])
            save_discord_turn(
                conversation_id,
                f"Discord · {channel_title}"[:100],
                history_messages,
            )
            log_event("discord.message", "Replied to a Discord message", channel=context_key)
            if fallback_used:
                log_event("discord.fallback", "Used the fallback model for Discord", model=fallback_used, channel=context_key)
            return answer
        except Exception as exc:
            log_event("discord.error", "Could not reply to the Discord message", error=str(exc))
            return "Sorry, the AI could not be reached right now. Check the settings on the web page."

    @command_tree.command(name="ai", description="Send a task to or chat with the AI agent")
    async def ai_command(interaction: Any, prompt: str) -> None:
        """Handle the /ai slash command."""
        await interaction.response.defer()
        answer = await ask_agent(
            str(interaction.channel_id),
            prompt,
            getattr(interaction.channel, "name", "Discord"),
            allow_schedule_tools=is_server_admin(interaction),
        )
        for chunk in split_discord_message(answer):
            await interaction.followup.send(chunk)

    @command_tree.command(name="clear", description="Clear this channel's conversation context")
    async def clear_command(interaction: Any) -> None:
        """Handle the /clear slash command."""
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(str(interaction.channel_id), None)
            DISCORD_CONVERSATION_IDS.pop(str(interaction.channel_id), None)
        await interaction.response.send_message("This channel's conversation context has been cleared.")

    @command_tree.command(name="new", description="Start a new chat and create a new history entry on the web")
    async def new_command(interaction: Any) -> None:
        """Handle the /new slash command."""
        context_key = str(interaction.channel_id)
        channel_title = getattr(interaction.channel, "name", "Discord")
        conversation_id = str(uuid.uuid4())
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(context_key, None)
            DISCORD_CONVERSATION_IDS[context_key] = conversation_id
        record = save_history({
            "id": conversation_id,
            "title": f"Discord · {channel_title}"[:100],
            "messages": [],
        })
        await interaction.response.send_message(
            f"Started a new chat; the history appears on the web immediately (ID: `{record['id'][:8]}`)"
        )

    async def model_autocomplete(interaction: Any, current_text: str) -> list[Any]:
        """Provide model id autocomplete choices for Discord commands."""
        settings = load_settings()
        selected = getattr(getattr(interaction, "namespace", None), "provider", None)
        # Namespace returns None for an option the user has not filled in yet.
        selected = getattr(selected, "value", selected) or settings.get("provider", "openai")
        selected_provider = normalize_provider(selected)
        try:
            # Answers from memory: a provider fetch would risk Discord's 3s limit.
            names = model_names_for_autocomplete(selected_provider, settings)
        except Exception as exc:
            log_event("discord.models", "Model autocomplete failed", error=str(exc)[:200])
            names = list(FALLBACK_MODELS.get(selected_provider, []))
        query = str(current_text or "").strip().lower()
        return [
            discord.app_commands.Choice(name=name[:100], value=name[:100])
            for name in names
            if not query or query in name.lower()
        ][:25]

    @command_tree.command(name="models", description="Change the AI agent's provider and model")
    @discord.app_commands.autocomplete(model=model_autocomplete)
    @discord.app_commands.choices(provider=[
        discord.app_commands.Choice(name="OpenAI / compatible", value="openai"),
        discord.app_commands.Choice(name="Google Gemini", value="gemini"),
        discord.app_commands.Choice(name="Anthropic Claude", value="anthropic"),
        discord.app_commands.Choice(name="Hugging Face", value="hf"),
        discord.app_commands.Choice(name="OpenRouter", value="or"),
        discord.app_commands.Choice(name="Groq", value="groq"),
    ])
    async def models_command(interaction: Any, provider: discord.app_commands.Choice[str], model: str | None = None) -> None:
        """Handle the /models slash command."""
        selected_provider = normalize_provider(provider.value)
        if model and not await require_server_admin(interaction):
            return
        await interaction.response.defer()
        if not model or not model.strip():
            try:
                current = load_settings()
                available = await asyncio.to_thread(list_models, selected_provider, current)
                remember_model_names(selected_provider, [item["id"] for item in available])
                current_model = current.get("model") if current.get("provider") == selected_provider else ""
                names = [item["id"] for item in available[:25]]
                listing = "\n".join(
                    f"• `{name}`{' ← in use' if name == current_model else ''} · ready"
                    for name in names
                ) or "No models found"
                await interaction.followup.send(
                    f"{PROVIDER_LABELS[selected_provider]} models (checked against the API):\n{listing}"
                )
            except Exception as exc:
                names = FALLBACK_MODELS.get(selected_provider, [])
                listing = "\n".join(f"• `{name}` · unverified" for name in names) or "No fallback list"
                await interaction.followup.send(
                    f"The {PROVIDER_LABELS[selected_provider]} API is unavailable: {str(exc)[:220]}\nFallback list:\n{listing}"
                )
            return
        # Read-modify-write under the same lock as /api/settings and /fallback,
        # so a concurrent settings change is not overwritten.
        with SETTINGS_LOCK:
            current = load_settings()
            # A base URL belongs to one provider; clearing it keeps the new
            # provider's key from being sent to the previous endpoint (the same
            # rule /api/settings applies).
            if normalize_provider(current.get("provider")) != selected_provider:
                current["base_url"] = ""
            current["provider"] = selected_provider
            current["model"] = model.strip()[:200]
            save_settings(current)
        STATUS_CACHE.clear()
        availability = await check_model_availability(selected_provider, current["model"], current)
        state = "ready" if availability.get("ready") else f"not available yet: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Agent changed to `{PROVIDER_LABELS[selected_provider]}` / `{current['model']}` · {state}"
        )

    @command_tree.command(name="ping", description="Check the Discord bot latency")
    async def ping_command(interaction: Any) -> None:
        """Handle the /ping slash command."""
        latency_ms = round(client.latency * 1000)
        await interaction.response.send_message(f"Pong! Discord latency: `{latency_ms} ms`")

    @command_tree.command(name="fallback", description="Set a fallback model for this Discord channel")
    @discord.app_commands.autocomplete(model=model_autocomplete)
    async def fallback_command(interaction: Any, model: str | None = None) -> None:
        """Handle the /fallback slash command for a channel."""
        current = load_settings()
        channel_key = str(interaction.channel_id)
        channel_fallbacks = current.get("discord_fallback_models")
        if not isinstance(channel_fallbacks, dict):
            channel_fallbacks = {}
        if not model or not model.strip():
            await interaction.response.defer()
            selected = channel_fallbacks.get(channel_key) or current.get("fallback_model") or "not set"
            if selected == "not set":
                await interaction.followup.send("Fallback model for this channel: not set")
                return
            availability = await check_model_availability(current.get("provider", "openai"), selected, current)
            state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
            await interaction.followup.send(f"Fallback model for this channel: `{selected}` · {state}")
            return
        if not await require_server_admin(interaction):
            return
        await interaction.response.defer()
        # Reload after the defer and change only this key, so a concurrent
        # /api/settings save (allowlists etc.) is not overwritten by the stale
        # snapshot captured before the awaits.
        with SETTINGS_LOCK:
            latest = load_settings()
            latest_fallbacks = latest.get("discord_fallback_models")
            if not isinstance(latest_fallbacks, dict):
                latest_fallbacks = {}
            if model.strip().lower() in {"off", "none", "disabled"}:
                latest_fallbacks.pop(channel_key, None)
                message = "Fallback is off for this channel (the main fallback is used if one is set)."
            else:
                latest_fallbacks[channel_key] = model.strip()[:200]
                message = f"Fallback model for this channel set to `{latest_fallbacks[channel_key]}`."
            latest["discord_fallback_models"] = latest_fallbacks
            save_settings(latest)
        if channel_key in latest_fallbacks:
            availability = await check_model_availability(latest.get("provider", "openai"), latest_fallbacks[channel_key], latest)
            state = "ready" if availability.get("ready") else f"not available yet: {availability.get('reason', 'check failed')}"
            message += f" · {state}"
        await interaction.followup.send(message)

    @command_tree.command(name="thread", description="Create a thread for a new topic")
    async def thread_command(interaction: Any, name: str) -> None:
        """Handle the /thread slash command."""
        channel = interaction.channel
        if not hasattr(channel, "create_thread"):
            await interaction.response.send_message("This command only works in a server text channel.", ephemeral=True)
            return
        try:
            thread = await channel.create_thread(
                name=name.strip()[:100] or "New topic",
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )
            await interaction.response.send_message(f"Created the thread: {thread.mention}")
        except Exception as exc:
            await interaction.response.send_message(f"Could not create the thread: {str(exc)[:300]}", ephemeral=True)

    @command_tree.command(name="status", description="Check the AI agent status")
    async def status_command(interaction: Any) -> None:
        """Handle the /status slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Discord: connected\nProvider: {current.get('provider', 'openai')}\nModel: {current.get('model', 'not selected')}\nAI status: {state}"
        )

    @command_tree.command(name="model", description="Show the provider and model the agent uses")
    async def model_command(interaction: Any) -> None:
        """Handle the /model slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Provider: `{current.get('provider', 'openai')}` · Model: `{current.get('model', 'not selected')}` · {state}"
        )

    @command_tree.command(name="invite", description="Create a bot invite link with Administrator permission")
    async def invite_command(interaction: Any) -> None:
        """Handle the /invite slash command."""
        if not await require_server_admin(interaction):
            return
        permissions = discord.Permissions(administrator=True)
        url = discord.utils.oauth_url(
            client.user.id,
            permissions=permissions,
            scopes=("bot", "applications.commands"),
        )
        await interaction.response.send_message(
            "This link invites or adds the bot to a new server with Administrator permission. "
            "Whoever opens the link needs permission to manage that server:\n" + url,
            ephemeral=True,
        )

    @command_tree.command(name="help", description="Show the AI agent commands")
    async def help_command(interaction: Any) -> None:
        """Handle the /help slash command."""
        await interaction.response.send_message(
            "AI agent commands:\n"
            "`/ai prompt` sends a task to or chats with the AI\n"
            "`/new` starts a new chat and creates a history entry on the web\n"
            "`/clear` clears the channel context\n"
            "`/models` changes the provider/model\n"
            "`/ping` checks the bot latency\n"
            "`/thread` creates a thread for a topic\n"
            "`/fallback model` sets a per-channel fallback\n"
            "`/invite` creates an invite link with Administrator permission (admins only)\n"
            "`/status` checks the bot status\n"
            "`/model` shows the current model\n"
            "`/help` shows this list\n\n"
            f"You can also mention the bot or type `{prefix} message`."
        )

    DISCORD_BOT = client
    DISCORD_ACTIVE_TOKEN = token

    def run_client() -> None:
        """Run the Discord client in its own event loop for the bot thread."""
        global DISCORD_LOOP
        import asyncio
        DISCORD_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(DISCORD_LOOP)
        try:
            DISCORD_LOOP.run_until_complete(client.start(token))
        except Exception as exc:
            log_event("discord.error", "Discord bot stopped", error=str(exc))
        finally:
            DISCORD_LOOP.close()

    DISCORD_THREAD = threading.Thread(target=run_client, name="discord-bot", daemon=True)
    DISCORD_THREAD.start()


def empty_auth_state() -> dict[str, Any]:
    """Return the empty shape of the pairing/session store."""
    return {"version": 1, "pairing_keys": [], "sessions": []}


def load_auth_state() -> dict[str, Any]:
    """Load the pairing/session store, tolerating a missing or broken file."""
    if not AUTH_FILE.exists():
        return empty_auth_state()
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_auth_state()
    state = empty_auth_state()
    if not isinstance(data, dict):
        return state
    for field in ("pairing_keys", "sessions"):
        raw = data.get(field)
        if isinstance(raw, list):
            state[field] = [item for item in raw if isinstance(item, dict)]
    return state


def save_auth_state(state: dict[str, Any]) -> None:
    """Persist the pairing/session store atomically with owner-only permissions."""
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = AUTH_FILE.with_suffix(".tmp")
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(temp_path, AUTH_FILE)


def hash_auth_token(value: str) -> str:
    """Hash a pairing key or session token before it is stored on disk."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def no_store(response):
    """Mark an identity-dependent response so proxies and browsers never cache it."""
    response.headers["Cache-Control"] = "no-store"
    return response


def auth_now() -> datetime:
    """Return the current local time used for pairing/session timestamps."""
    return datetime.now().astimezone()


def auth_timestamp(moment: datetime) -> str:
    """Serialize a timestamp in the same ISO shape used elsewhere in the app."""
    return moment.isoformat(timespec="seconds")


def auth_expired(record: dict[str, Any], now: datetime) -> bool:
    """Report whether a stored key or session record has passed its expiry."""
    try:
        return datetime.fromisoformat(str(record.get("expires_at") or "")) <= now
    except (TypeError, ValueError):
        return True


def prune_auth_state(state: dict[str, Any], now: datetime) -> None:
    """Drop expired keys and sessions so the store does not grow forever."""
    state["pairing_keys"] = [item for item in state["pairing_keys"] if not auth_expired(item, now)]
    state["sessions"] = [item for item in state["sessions"] if not auth_expired(item, now)]


def normalize_pairing_key(raw_key: Any) -> str:
    """Normalize a client-supplied key by stripping separators and case."""
    cleaned = re.sub(r"[^0-9A-Za-z]", "", str(raw_key or "")).upper()
    return cleaned if len(cleaned) == AUTH_KEY_LENGTH else ""


def format_pairing_key(key: str) -> str:
    """Group a pairing key into readable blocks, e.g. ABCD-EFGH-JKLM."""
    return "-".join(key[index:index + 4] for index in range(0, len(key), 4))


def generate_pairing_key(label: str = "") -> dict[str, Any]:
    """Create a single-use pairing key; only its hash is written to disk."""
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        while True:
            key = "".join(secrets.choice(AUTH_KEY_ALPHABET) for _ in range(AUTH_KEY_LENGTH))
            digest = hash_auth_token(key)
            if not any(hmac.compare_digest(str(item.get("hash") or ""), digest) for item in state["pairing_keys"]):
                break
        record = {
            "id": secrets.token_hex(8),
            "hash": digest,
            "label": str(label or "").strip()[:60],
            "created_at": auth_timestamp(now),
            "expires_at": auth_timestamp(now + timedelta(minutes=AUTH_PAIRING_TTL_MINUTES)),
        }
        state["pairing_keys"].append(record)
        save_auth_state(state)
    return {"key": format_pairing_key(key), "id": record["id"], "expires_at": record["expires_at"], "ttl_minutes": AUTH_PAIRING_TTL_MINUTES}


def consume_pairing_key(raw_key: Any) -> bool:
    """Validate and burn one pairing key so it cannot be reused."""
    key = normalize_pairing_key(raw_key)
    if not key:
        return False
    digest = hash_auth_token(key)
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        matched = False
        remaining = []
        for item in state["pairing_keys"]:
            if not matched and hmac.compare_digest(str(item.get("hash") or ""), digest):
                matched = True
                continue
            remaining.append(item)
        state["pairing_keys"] = remaining
        save_auth_state(state)
    return matched


def pairing_attempt_allowed(client_ip: str) -> bool:
    """Rate-limit pairing attempts per client address."""
    now = time.time()
    with AUTH_LOCK:
        recent = [stamp for stamp in AUTH_PAIRING_FAILURES.get(client_ip, []) if now - stamp < AUTH_PAIRING_FAILURE_WINDOW]
        AUTH_PAIRING_FAILURES[client_ip] = recent
        return len(recent) < AUTH_PAIRING_MAX_FAILURES


def record_pairing_failure(client_ip: str) -> None:
    """Remember a failed pairing attempt for rate limiting."""
    with AUTH_LOCK:
        AUTH_PAIRING_FAILURES.setdefault(client_ip, []).append(time.time())
        if len(AUTH_PAIRING_FAILURES) > 500:
            for stale_ip in [ip for ip, stamps in AUTH_PAIRING_FAILURES.items() if not stamps]:
                AUTH_PAIRING_FAILURES.pop(stale_ip, None)


def create_auth_session(label: str = "", user_agent: str = "", client_ip: str = "") -> str:
    """Create a paired-device session and return its raw cookie token once."""
    token = secrets.token_urlsafe(32)
    now = auth_now()
    record = {
        "id": secrets.token_hex(8),
        "token_hash": hash_auth_token(token),
        "label": str(label or "").strip()[:60] or "Connected device",
        "user_agent": str(user_agent or "")[:200],
        "ip": str(client_ip or "")[:80],
        "created_at": auth_timestamp(now),
        "last_seen_at": auth_timestamp(now),
        "expires_at": auth_timestamp(now + timedelta(days=AUTH_SESSION_DAYS)),
    }
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        state["sessions"].append(record)
        save_auth_state(state)
    return token


def auth_session_tokens() -> list[str]:
    """Return the session tokens this request carries, one per cookie name."""
    return [
        token
        for name in AUTH_SESSION_COOKIE_NAMES
        if (token := request.cookies.get(name, ""))
    ]


def current_auth_session() -> dict[str, Any] | None:
    """Resolve one of the request cookies to a live paired-device session."""
    tokens = auth_session_tokens()
    if not tokens:
        return None
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        for token in tokens:
            digest = hash_auth_token(token)
            for item in state["sessions"]:
                if not hmac.compare_digest(str(item.get("token_hash") or ""), digest):
                    continue
                if auth_expired(item, now):
                    continue
                try:
                    recently_seen = (now - datetime.fromisoformat(str(item.get("last_seen_at") or ""))).total_seconds() <= 60
                except (TypeError, ValueError):
                    recently_seen = False
                if not recently_seen:
                    item["last_seen_at"] = auth_timestamp(now)
                    save_auth_state(state)
                return dict(item)
    return None


def revoke_auth_session(session_id: str) -> bool:
    """Revoke one paired device by its session id."""
    with AUTH_LOCK:
        state = load_auth_state()
        remaining = [item for item in state["sessions"] if item.get("id") != session_id]
        if len(remaining) == len(state["sessions"]):
            return False
        state["sessions"] = remaining
        save_auth_state(state)
    return True


def revoke_all_auth_sessions() -> int:
    """Revoke every paired device and return how many were removed."""
    with AUTH_LOCK:
        state = load_auth_state()
        count = len(state["sessions"])
        state["sessions"] = []
        save_auth_state(state)
    return count


def active_auth_session_count() -> int:
    """Count sessions that are still valid, pruning expired records."""
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        save_auth_state(state)
        return len(state["sessions"])


def bootstrap_pairing_key() -> dict[str, Any] | None:
    """Create the first-run key when no device has been paired yet."""
    if not AUTH_ENABLED or active_auth_session_count():
        return None
    return generate_pairing_key("server")


def print_pairing_banner(record: dict[str, Any] | None) -> None:
    """Print a pairing key to the server console, never to the app log file."""
    if not record:
        return
    print(
        "\n" + "=" * 62 + "\n"
        f"  Pairing Key: {record['key']}\n"
        f"  valid until {record['expires_at']} and single use\n"
        "  on the client, open /pair and enter this key\n"
        + "=" * 62 + "\n",
        flush=True,
    )


@app.before_request
def reject_cross_site_mutation():
    """Refuse state-changing requests that a browser sent from another site."""
    if request.method not in MUTATING_METHODS:
        return None
    # Any real change from the page or a client means someone is using the app,
    # so the nightly memory run only starts once the machine has been quiet.
    memory_engine.touch_activity()
    # Sec-Fetch-Site is set by the browser and cannot be forged by page script,
    # so it catches a cross-site request even when the Origin comparison is
    # defeated by a spoofed or proxy-supplied Host / X-Forwarded-Host.
    fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if fetch_site in {"cross-site", "same-site"}:
        log_event("security.cross_site", "Rejected a cross-site request", path=request.path, method=request.method, site=fetch_site)
        return jsonify({"error": status_message(request_language(), "cross_origin")}), 403
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        # Non-browser clients (curl, scripts) do not send Origin.
        return None
    parsed = urlsplit(origin)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request.host.lower():
        return None
    log_event("security.cross_origin", "Rejected a request from another origin", path=request.path, method=request.method)
    return jsonify({"error": status_message(request_language(), "cross_origin")}), 403


@app.errorhandler(413)
def request_too_large(_error):
    """Answer an oversized upload with JSON instead of Werkzeug's HTML page."""
    return jsonify({"error": status_message(request_language(allow_body=False), "body_too_large")}), 413


@app.before_request
def require_web_auth():
    """Gate every page and API behind a paired device unless auth is disabled."""
    if not AUTH_ENABLED:
        return None
    path = request.path or ""
    if path in AUTH_PUBLIC_PATHS or path.startswith(AUTH_PUBLIC_PREFIXES):
        return None
    if current_auth_session():
        return None
    if path.startswith("/api/"):
        return jsonify({"error": status_message(request_language(), "pairing_required"), "auth_required": True}), 401
    return redirect("/pair", code=302)


def asset_url(page: str, filename: str) -> str:
    """Return a cache-busting URL for a page asset.

    The mtime in the query lets the asset be cached for a year: editing the
    file changes the URL, so the browser fetches the new version on reload.
    """
    try:
        version = (TEMPLATES_ROOT / page / filename).stat().st_mtime_ns
    except OSError:
        version = 0
    return f"/templates/{page}/{filename}?v={version}"


app.jinja_env.globals["asset_url"] = asset_url


def accepts_gzip() -> bool:
    """Report whether the client advertised gzip support."""
    return "gzip" in (request.headers.get("Accept-Encoding") or "").lower()


def gzip_body(data: bytes, cache_key: tuple[str, int, int] | None = None) -> bytes:
    """Gzip a text body, reusing the result while the source file is unchanged."""
    if cache_key is not None:
        with ASSET_GZIP_LOCK:
            cached = ASSET_GZIP_CACHE.get(cache_key)
        if cached is not None:
            return cached
    compressed = gzip.compress(data, 6, mtime=0)
    if cache_key is not None:
        with ASSET_GZIP_LOCK:
            if len(ASSET_GZIP_CACHE) >= ASSET_GZIP_CACHE_LIMIT:
                ASSET_GZIP_CACHE.clear()
            ASSET_GZIP_CACHE[cache_key] = compressed
    return compressed


def representation_etag(base_etag: str, gzipped: bool) -> str:
    """Return an ETag that identifies one representation of the same resource.

    Caches match entries by ETag, so the gzip and identity bodies must not share
    one: a client that did not ask for gzip could be handed a gzip body, or a
    revalidation could accept a body in the wrong encoding.
    """
    token = base_etag.strip()
    if token.startswith("W/"):
        token = token[2:].strip()
    token = token.strip('"')
    return f'"{token}-gzip"' if gzipped else f'"{token}"'


def compress_response(
    response,
    cache_key: tuple[str, int, int] | None = None,
    accept_ranges: bool = False,
):
    """Gzip a text response and answer preconditions for the chosen representation.

    A gzip and an identity body of the same file are different representations:
    they get different ETags, and validators, date preconditions, and byte ranges
    are judged only once the representation is known.  A conditional request is
    answered with 304 only when it names the representation this request would
    receive, so the identity ETag can never confirm a gzip body.
    """
    if response.status_code != 200 or response.headers.get("Content-Encoding"):
        return response
    if (response.mimetype or "").lower() not in GZIP_MIMETYPES:
        return response
    body = response.get_data()
    size = len(body)
    if not size:
        # A HEAD response has no body; judge the size from the declared length.
        try:
            size = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            size = 0
    gzipped = accepts_gzip() and size >= GZIP_MIN_BYTES
    base_etag = response.get_etag()[0] or hashlib.sha1(body).hexdigest()
    response.headers.add("Vary", "Accept-Encoding")
    # The value is already quoted; set_etag() would reject it as invalid.
    response.headers["ETag"] = representation_etag(base_etag, gzipped)
    if gzipped and body:
        response.set_data(gzip_body(body, cache_key))
        response.headers["Content-Encoding"] = "gzip"
    # Preconditions and ranges belong to the representation chosen above; letting
    # them run earlier would let the file's identity validators answer for gzip.
    response.make_conditional(
        request,
        accept_ranges=accept_ranges,
        complete_length=len(response.get_data()),
    )
    return response


@app.after_request
def gzip_rendered_pages(response):
    """Gzip rendered HTML so the chat page needs fewer round trips on a slow link."""
    if (response.mimetype or "").lower() == "text/html":
        return compress_response(response)
    return response


def models_response(provider: str, settings: dict[str, Any]):
    """Build the model list response shared by the GET and POST model endpoints."""
    try:
        models = list_models(provider, settings)
        remember_model_names(provider, [str(item.get("id", "")) for item in models])
        return jsonify({"provider": provider, "models": models, "source": "api"})
    except (requests.RequestException, RuntimeError, KeyError, TypeError):
        fallback = [{"id": name, "name": name} for name in FALLBACK_MODELS.get(provider, [])]
        return jsonify({"provider": provider, "models": fallback, "source": "fallback", "error": status_message(request_language(), "models_fallback")}), 502


def apply_settings_update():
    """Apply a settings PUT body; call with SETTINGS_LOCK held."""
    body = request.get_json(silent=True) or {}
    current = load_settings()
    previous_provider = normalize_provider(current.get("provider"))
    allowed = {"memory", "agent_name", "agent_role", "response_language", "response_style", "use_markdown", "ask_clarifying_questions", "provider", "model", "base_url", "system_prompt", "memory_review", "skills", "temperature", "max_tokens", "top_p", "thinking_level", "stream", "fallback_enabled", "fallback_provider", "fallback_model", "gemini_live_model", "gemini_agent", "gemini_decision_model", "discord_enabled", "discord_prefix", "discord_allowed_users", "discord_allowed_channels", "machine_access"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    current["provider"] = normalize_provider(current.get("provider"))
    if current["provider"] != previous_provider and "base_url" not in body:
        # A base URL belongs to one provider. Dropping it on a provider switch
        # stops hf/or/groq requests from being sent to the previous endpoint.
        current["base_url"] = ""
    current["agent_name"] = str(current.get("agent_name") or "Mux").strip()[:80]
    current["agent_role"] = str(current.get("agent_role") or "A versatile AI assistant").strip()[:500]
    language = str(current.get("response_language") or "auto").strip().lower()
    current["response_language"] = language if language in {"auto", "th", "en"} else "auto"
    current["response_style"] = str(current.get("response_style") or "Friendly, concise, and clear").strip()[:500]
    current["use_markdown"] = bool(current.get("use_markdown", True))
    current["ask_clarifying_questions"] = bool(current.get("ask_clarifying_questions", True))
    thinking_level = str(current.get("thinking_level") or "off").strip().lower()
    current["thinking_level"] = thinking_level if thinking_level in {"off", "low", "medium", "high"} else "off"
    current["fallback_enabled"] = bool(current.get("fallback_enabled"))
    current["fallback_provider"] = normalize_provider(current.get("fallback_provider"))
    current["fallback_model"] = str(current.get("fallback_model") or "")[:200]
    current["gemini_live_model"] = str(current.get("gemini_live_model") or "").strip()[:120]
    current["gemini_agent"] = str(current.get("gemini_agent") or "").strip()[:100]
    current["gemini_decision_model"] = str(current.get("gemini_decision_model") or "").strip()[:100]
    current["discord_enabled"] = bool(current.get("discord_enabled"))
    current["discord_prefix"] = str(current.get("discord_prefix") or "!ai").strip()[:30] or "!ai"
    # Invalid allowlist entries reject the save instead of being skipped: a
    # dropped typo would empty the list and silently lift the restriction.
    allowed_users, invalid_users = parse_discord_ids(current.get("discord_allowed_users"))
    allowed_channels, invalid_channels = parse_discord_ids(current.get("discord_allowed_channels"))
    if invalid_users or invalid_channels:
        return jsonify({
            "error": status_message(request_language(), "discord_ids_invalid", ids=", ".join((invalid_users + invalid_channels)[:5])),
        }), 400
    current["discord_allowed_users"] = allowed_users
    current["discord_allowed_channels"] = allowed_channels
    current["machine_access"] = bool(current.get("machine_access", True))
    raw_skills = current.get("skills")
    available_skill_names = {item["name"] for item in list_skills()}
    current["skills"] = [
        str(name)
        for name in (raw_skills if isinstance(raw_skills, list) else [])
        if str(name) in available_skill_names
    ]
    discord_token = body.get("discord_token")
    if isinstance(discord_token, str) and discord_token.strip() and discord_token != "••••••••":
        current["discord_token"] = discord_token.strip()
    new_key = body.get("api_key")
    if isinstance(new_key, str) and new_key.strip() and new_key != "••••••••":
        keys = stored_api_keys(current)
        keys[current["provider"]] = new_key.strip()
        current["api_keys"] = keys
    custom_key = body.get("custom_api_key")
    if isinstance(custom_key, dict):
        try:
            custom_name = normalize_custom_key_name(custom_key.get("name"))
        except ValueError:
            return jsonify({"error": status_message(request_language(), "custom_key_name_invalid")}), 400
        custom_value = custom_key.get("value")
        if isinstance(custom_value, str) and "\x00" in custom_value:
            return jsonify({"error": status_message(request_language(), "custom_key_nul")}), 400
        if isinstance(custom_value, str) and custom_value.strip() and custom_value.strip() != "••••••••":
            keys = stored_custom_api_keys(current)
            keys[custom_name] = custom_value.strip()
            current["custom_api_keys"] = keys
    delete_custom_name = body.get("delete_custom_api_key")
    if isinstance(delete_custom_name, str) and delete_custom_name.strip():
        try:
            removed_name = normalize_custom_key_name(delete_custom_name)
        except ValueError:
            removed_name = ""
        if removed_name:
            keys = stored_custom_api_keys(current)
            keys.pop(removed_name, None)
            current["custom_api_keys"] = keys
    current.pop("api_key", None)
    try:
        current["memory"] = memory_engine.normalize_settings(current.get("memory"))
    except ValueError:
        return jsonify({"error": status_message(request_language(), "memory_schedule_invalid")}), 400
    save_settings(current)
    STATUS_CACHE.clear()
    if current.get("discord_enabled"):
        start_discord_bot()
    else:
        stop_discord_bot()
    return jsonify({"ok": True, "provider": current["provider"], "has_api_key": key_is_configured(current["provider"], current)})


def gemini_error_detail(response: Any, api_key: str) -> str:
    """Extract a safe, redacted error message from a Gemini API response."""
    detail = ""
    if response is not None:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
            elif isinstance(error, str):
                detail = error
            else:
                detail = str(payload.get("message") or "")
        if not detail:
            detail = str(getattr(response, "text", "") or "")
    if not detail:
        return "unknown error"
    # Redact the full text first: a truncated fragment of the key would slip
    # past the exact-match redactor and still reach the browser.
    return redact_secrets(detail, api_key=api_key)[:400]


def gemini_agent_answer(steps: Any) -> str:
    """Collect the visible reply from a REST interaction's model-output steps.

    ``output_text`` is an SDK convenience field; the REST payload returns the
    answer as content on ``model_output`` steps, so tool and thought steps stay
    out of the text shown to the user.
    """
    if not isinstance(steps, list):
        return ""
    chunks: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or str(step.get("type") or "") != "model_output":
            continue
        content = step.get("content")
        if isinstance(content, str):
            chunks.append(content)
            continue
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "".join(chunks)


# Self-update: the web page can run the project's own update.sh. Only the two
# fixed modes below are accepted, so no user input reaches the command line.
UPDATE_SCRIPT = PROJECT_ROOT / "update.sh"
UPDATE_LOG_FILE = Path(os.getenv("AI_WEB_UPDATE_LOG_FILE", "logs/update.log"))
UPDATE_LOG_TAIL_LINES = 160
UPDATE_MODES = {"check", "apply"}
UPDATE_JOB_LOCK = threading.Lock()
UPDATE_JOB: dict[str, Any] = {}
# A real update restarts this process, so the job is also persisted: the new
# server reads it back to report what happened before the restart.
UPDATE_STATUS_FILE = Path(os.getenv("AI_WEB_UPDATE_STATUS_FILE", "logs/update-status.json"))


def update_build_info() -> dict[str, Any]:
    """Describe the app files on disk; the updater keeps no version number."""
    try:
        stat = (PROJECT_ROOT / "app.py").stat()
    except OSError:
        return {"app_updated_at": "", "app_size": 0}
    return {
        "app_updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "app_size": stat.st_size,
    }


def update_script_ready() -> bool:
    """Return whether update.sh exists and can be executed."""
    return UPDATE_SCRIPT.is_file() and os.access(UPDATE_SCRIPT, os.X_OK)


def update_log_tail() -> tuple[str, bool]:
    """Return the end of the update log and whether older lines were dropped."""
    try:
        text = UPDATE_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return "", False
    lines = text.splitlines()
    return "\n".join(lines[-UPDATE_LOG_TAIL_LINES:]), len(lines) > UPDATE_LOG_TAIL_LINES


def save_update_status(payload: dict[str, Any]) -> None:
    """Persist the running update so the next server process can report it."""
    try:
        UPDATE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = UPDATE_STATUS_FILE.with_name(f".{UPDATE_STATUS_FILE.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, UPDATE_STATUS_FILE)
    except OSError:
        return


def load_update_status() -> dict[str, Any]:
    """Read the persisted update record, tolerating a missing or broken file."""
    try:
        data = json.loads(UPDATE_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def process_is_alive(pid: Any) -> bool:
    """Return whether the PID recorded for an update is still running."""
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def update_log_finished_at() -> str:
    """Use the log's timestamp as the finish time after a server restart."""
    try:
        return datetime.fromtimestamp(UPDATE_LOG_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def update_log_succeeded() -> bool | None:
    """Read the updater's own success/failure verdict from its log tail."""
    tail, _ = update_log_tail()
    if "✅" in tail:
        return True
    if "❌" in tail:
        return False
    return None


def update_job_snapshot() -> dict[str, Any]:
    """Report the current update job, falling back to the persisted record."""
    with UPDATE_JOB_LOCK:
        process = UPDATE_JOB.get("process")
        if process is not None:
            return {
                "running": process.poll() is None,
                "job": {
                    "mode": UPDATE_JOB.get("mode", ""),
                    "started_at": UPDATE_JOB.get("started_at", ""),
                    "finished_at": UPDATE_JOB.get("finished_at", ""),
                    "ok": UPDATE_JOB.get("ok"),
                    "exit_code": UPDATE_JOB.get("exit_code"),
                },
            }
    persisted = load_update_status()
    if not persisted:
        return {
            "running": False,
            "job": {"mode": "", "started_at": "", "finished_at": "", "ok": None, "exit_code": None},
        }
    # The updater runs in its own session, so it outlives the restart we just did.
    running = process_is_alive(persisted.get("pid"))
    return {
        "running": running,
        "job": {
            "mode": persisted.get("mode", ""),
            "started_at": persisted.get("started_at", ""),
            "finished_at": "" if running else update_log_finished_at(),
            "ok": None if running else update_log_succeeded(),
            "exit_code": None,
        },
    }


def watch_update_job(process: "subprocess.Popen[bytes]") -> None:
    """Record the updater's exit status after the detached process finishes."""
    code = process.wait()
    with UPDATE_JOB_LOCK:
        UPDATE_JOB["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UPDATE_JOB["exit_code"] = code
        UPDATE_JOB["ok"] = code == 0


def configured_certificate_pair() -> tuple[str, str] | None:
    """Return a usable certificate pair the server can actually serve.

    `certs/cert.pem` + `certs/key.pem` (what --make-cert writes) win. When they
    are absent, keep a pair that is already configured in .env instead of
    refusing to save the mode the server is running with right now.
    """
    default_cert = CERT_DIR / "cert.pem"
    default_key = CERT_DIR / "key.pem"
    if default_cert.is_file() and default_key.is_file():
        return str(default_cert), str(default_key)
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    if cert and key and Path(cert).is_file() and Path(key).is_file():
        return cert, key
    return None


def server_tls_state() -> dict[str, Any]:
    """Describe the TLS mode the server will use on its next start."""
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    adhoc = os.getenv("AI_WEB_TLS_ADHOC", "").strip().lower() in {"1", "true", "yes", "on"}
    # An explicit ad-hoc request wins, so the saved certificate pair can stay in
    # .env while ad-hoc mode runs and still be reused afterwards.
    if adhoc:
        kind = "adhoc"
    elif cert and key:
        kind = "cert"
    else:
        kind = "none"
    return {
        "mode": "https" if kind != "none" else "http",
        "kind": kind,
        "cert_exists": bool(cert) and Path(cert).is_file(),
        "key_exists": bool(key) and Path(key).is_file(),
        # True when saving "HTTPS with certificate files" would succeed: either
        # certs/cert.pem + certs/key.pem exist, or the pair in .env is usable.
        "pair_available": configured_certificate_pair() is not None,
        "adhoc": adhoc,
    }


TLS_ENV_KEYS = ("AI_WEB_TLS_CERT", "AI_WEB_TLS_KEY", "AI_WEB_TLS_ADHOC")
TLS_ENV_LOCK = threading.Lock()


def apply_tls_environment(values: dict[str, str]) -> None:
    """Mirror a saved TLS mode into this process environment.

    load_dotenv() only fills variables when the process starts, so without this
    the running server keeps the old AI_WEB_TLS_* values in its environment.
    A restart started from the web page inherits them, and because an exported
    variable wins over .env, switching back to HTTP would never take effect.

    The caller keeps the certificate pair in AI_WEB_TLS_CERT/KEY while ad-hoc
    mode runs, and tls_configuration() lets AI_WEB_TLS_ADHOC win over that
    pair, so re-selecting "HTTPS with certificate files" reuses the same paths
    instead of losing them.
    """
    for key in TLS_ENV_KEYS:
        value = values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def update_env_file(values: dict[str, str]) -> None:
    """Update keys in .env atomically; an empty value removes the key.

    Only the three AI_WEB_TLS_* keys are ever written, and the rest of the
    file (API keys included) is preserved byte for byte.
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OSError(f"Could not read the .env file: {exc}") from exc
    pending = dict(values)
    output: list[str] = []
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = pattern.match(line)
        key = match.group(1) if match else ""
        if key and key in pending:
            value = pending.pop(key)
            if value:
                output.append(f"{key}={value}")
            continue
        output.append(line)
    for key, value in pending.items():
        if value:
            output.append(f"{key}={value}")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ENV_FILE.with_name(f".{ENV_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output).strip("\n") + "\n")
        os.replace(temp_path, ENV_FILE)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def tls_configuration() -> Any:
    """Return a Werkzeug ssl_context for HTTPS, or None to serve plain HTTP.

    Precedence matches start_web.sh: an explicit ad-hoc request wins over a
    saved certificate pair, so the pair can be kept in .env while ad-hoc mode
    runs and be reused when the user switches back.
    """
    adhoc = os.getenv("AI_WEB_TLS_ADHOC", "").strip().lower() in {"1", "true", "yes", "on"}
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    if adhoc:
        return "adhoc"
    if cert or key:
        if not (cert and key):
            raise SystemExit("Set AI_WEB_TLS_CERT and AI_WEB_TLS_KEY together")
        missing = [path for path in (cert, key) if not Path(path).is_file()]
        if missing:
            raise SystemExit(f"Certificate/key files not found: {', '.join(missing)}")
        return (cert, key)
    return None


TLS_HANDSHAKE_TIMEOUT_SECONDS = 10

# Seconds close() may spend delivering a response that is still queued.
RESPONSE_LINGER_SECONDS = 5


class DrainingRequestHandler(WSGIRequestHandler):
    """Deliver the whole response before the connection is closed.

    Werkzeug always answers with ``Connection: close`` and then closes the
    socket. On Termux, closing a socket that still holds a large body that has
    not been acknowledged yet aborts delivery, so the browser waits forever on
    a half-loaded page (the chat page is ~248 KB). SO_LINGER makes close()
    block until the peer has the bytes, or the linger timeout expires.
    """

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_LINGER,
                struct.pack("ii", 1, RESPONSE_LINGER_SECONDS),
            )
        except OSError:
            pass


def adhoc_certificate() -> tuple[str, str]:
    """Create (once) and reuse a self-signed certificate for ad-hoc HTTPS.

    Werkzeug's ad-hoc context needs the optional `cryptography` package, which
    a Termux install does not have, so the server died on startup with
    "Using ad-hoc certificates requires the cryptography library". openssl is
    already required for --make-cert, so generate the pair with it instead and
    keep the files under certs/ so a restart hands the browser the same
    certificate instead of a new warning every time.
    """
    if ADHOC_CERT_FILE.is_file() and ADHOC_KEY_FILE.is_file():
        return str(ADHOC_CERT_FILE), str(ADHOC_KEY_FILE)
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "openssl was not found, so the ad-hoc certificate cannot be created — install it with pkg install openssl-tool "
            "or run ./start_web.sh --make-cert and choose the certificate mode"
        )
    names = ["localhost", "127.0.0.1"]
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    if hostname and hostname not in names:
        names.append(hostname)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            address = probe.getsockname()[0]
    except OSError:
        address = ""
    if address and address not in names:
        names.append(address)
    try:
        ipaddress.ip_address(names[0])
        common_name = hostname or "localhost"
    except ValueError:
        common_name = names[0]
    san = ",".join(
        f"IP:{name}" if _is_ip_address(name) else f"DNS:{name}" for name in names
    )
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    temp_key = ADHOC_KEY_FILE.with_name(f".{ADHOC_KEY_FILE.name}.{uuid.uuid4().hex}.tmp")
    temp_cert = ADHOC_CERT_FILE.with_name(f".{ADHOC_CERT_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        result = subprocess.run(
            [
                openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                "-days", "3650",
                "-keyout", str(temp_key), "-out", str(temp_cert),
                "-subj", f"/CN={common_name}",
                "-addext", f"subjectAltName={san}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not create the ad-hoc certificate: {result.stderr.strip()[:300]}"
            )
        os.chmod(temp_key, 0o600)
        os.replace(temp_cert, ADHOC_CERT_FILE)
        os.replace(temp_key, ADHOC_KEY_FILE)
    finally:
        for leftover in (temp_key, temp_cert):
            leftover.unlink(missing_ok=True)
    log_event("system.adhoc_cert", "Created an ad-hoc HTTPS certificate", names=", ".join(names))
    return str(ADHOC_CERT_FILE), str(ADHOC_KEY_FILE)


def _is_ip_address(value: str) -> bool:
    """Report whether a name is a literal IP address for the certificate SAN."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def build_tls_context(ssl_context: Any) -> Any:
    """Turn a tls_configuration() value into a ready ssl.SSLContext."""
    if isinstance(ssl_context, tuple):
        return load_ssl_context(*ssl_context)
    try:
        return load_ssl_context(*adhoc_certificate())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Could not create the ad-hoc HTTPS certificate: {exc}") from exc


class TLSServer(ThreadedWSGIServer):
    """Threaded WSGI server that performs the TLS handshake per connection.

    Werkzeug wraps the listening socket itself, so a client that connects and
    sends no handshake bytes blocks accept() and with it every other client.
    Accepting the plain socket and handshaking in the request thread keeps the
    accept loop free and lets a stalled handshake time out.
    """

    def __init__(self, host: str, port: int, wsgi_app: Any, ssl_context: Any) -> None:
        super().__init__(
            host, port, wsgi_app, handler=DrainingRequestHandler, ssl_context=None
        )
        self.tls_context = ssl_context
        # Werkzeug uses ssl_context to report requests as HTTPS.
        self.ssl_context = ssl_context

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            request.settimeout(TLS_HANDSHAKE_TIMEOUT_SECONDS)
            request = self.tls_context.wrap_socket(request, server_side=True)
            request.settimeout(None)
        except (ssl.SSLError, OSError) as exc:
            self.log("info", f"TLS handshake failed for {client_address}: {exc}")
            try:
                request.close()
            except OSError:
                pass
            return
        super().process_request_thread(request, client_address)


def auth_cli(argv: list[str]) -> bool:
    """Handle pairing-key CLI flags without starting the web server."""
    if "--pairing-key" not in argv and "--revoke-sessions" not in argv:
        return False
    if "--revoke-sessions" in argv:
        print(f"✅ Revoked every connected device ({revoke_all_auth_sessions()})", flush=True)
    if "--pairing-key" in argv:
        if not AUTH_ENABLED:
            print("Web auth is off — set AI_WEB_AUTH=on to create a Pairing Key", flush=True)
            return True
        label = "cli"
        if "--label" in argv:
            index = argv.index("--label")
            if index + 1 < len(argv):
                label = argv[index + 1]
        print_pairing_banner(generate_pairing_key(label))
    return True


if os.getenv("AI_WEB_ENABLE_SCHEDULER", "").strip().lower() in {"1", "true", "yes"}:
    start_scheduler()
    memory_engine.start_scheduler()


# Register the page blueprints only here, after the Flask app and every shared
# helper above exist. Running ``python app.py`` names this module ``__main__``,
# so alias it as ``app``; without that the route modules would import a second
# copy of this file and register on the wrong app.
sys.modules.setdefault("app", sys.modules[__name__])
from index_routes import index_bp  # noqa: E402  (must follow the definitions above)
from pair_routes import pair_bp  # noqa: E402

app.register_blueprint(pair_bp)
app.register_blueprint(index_bp)

if __name__ == "__main__":
    if auth_cli(sys.argv[1:]):
        raise SystemExit(0)
    start_scheduler()
    memory_engine.start_scheduler()
    start_discord_bot()
    print_pairing_banner(bootstrap_pairing_key())
    port = int(os.getenv("PORT", "5000"))
    ssl_context = tls_configuration()
    scheme = "https" if ssl_context else "http"
    print(f"🔒 Serving at {scheme}://<ip>:{port}" if ssl_context else f"🌐 Serving at http://<ip>:{port}", flush=True)
    if ssl_context:
        print("   Session cookies are marked Secure because request.is_secure is true", flush=True)
        # Handshake per connection so a client that never sends TLS data
        # cannot block the accept loop.
        server = TLSServer("0.0.0.0", port, app, build_tls_context(ssl_context))
        server.log_startup()
        server.serve_forever()
    else:
        server = ThreadedWSGIServer(
            "0.0.0.0", port, app, handler=DrainingRequestHandler
        )
        server.log_startup()
        server.serve_forever()

