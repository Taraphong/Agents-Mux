import os
import asyncio
import fcntl
import getpass
import hashlib
import hmac
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from collections import deque

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import (
    ThreadedWSGIServer,
    WSGIRequestHandler,
    generate_adhoc_ssl_context,
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
# Each page keeps its template and its CSS/JS together in templates/<page>/.
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
PAGE_ASSETS = {"index", "pair"}
SKILLS_ROOT = Path(os.getenv("AI_WEB_SKILLS_DIR", "skills"))
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
PROTECTED_NAMES = {".env", ".app-settings.json", ".app-auth.json"}
PROTECTED_PARTS = {"history", ".venv", ".git", "__pycache__", "certs"}
TERMINAL_TIMEOUT_SECONDS = 60
TERMINAL_MAX_OUTPUT_BYTES = 100_000
TERMINAL_SENSITIVE_ENV_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


# Device pairing: the server generates single-use keys, the client sends a key
# back and receives an HttpOnly cookie for a long-lived, revocable session.
AUTH_FILE = Path(os.getenv("AI_WEB_AUTH_FILE", ".app-auth.json"))
AUTH_ENABLED = os.getenv("AI_WEB_AUTH", "on").strip().lower() not in {"0", "false", "no", "off"}
AUTH_SESSION_COOKIE = "ai-web-session"
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
คุณใช้เครื่องมือกับเครื่องนี้ได้เต็มรูปแบบ: path แบบ absolute หรือ ~/... เข้าถึงได้ทุกที่ในเครื่อง และ run_command รันผ่าน shell จริง (รวมถึง sudo ถ้าผู้ใช้ที่รันแอปมีสิทธิ์) โดยเริ่มในโฟลเดอร์โปรเจกต์
ทุกครั้งที่เรียกเครื่องมือ ระบบจะหยุดรอให้ผู้ใช้อนุมัติในแชตก่อนเสมอ และอนุมัติได้ครั้งเดียวต่อหนึ่งคำขอ ห้ามถือว่าอนุมัติแล้วหรือข้ามการขออนุมัติ
รูปแบบการเรียก: <tool_call>{"name":"read_file","arguments":{"path":"/etc/hostname"}}</tool_call> หรือ <tool_call>{"name":"list_files","arguments":{"path":"~"}}</tool_call>
ใช้ write_file สำหรับเขียนไฟล์, run_command (ชื่อเดิม execute_command ก็ได้) สำหรับรันคำสั่ง, list_files/read_file สำหรับสำรวจเครื่อง
ระบบจะปิดบัง API key และ private key ที่รู้จักในผลลัพธ์ให้อัตโนมัติ
หากต้องสร้างหรือปรับปรุงสกิล ให้ใช้เครื่องมือ create_skill พร้อมชื่อไฟล์ .md และเนื้อหาสกิลที่ชัดเจน ระบบจะจำกัดการเขียนไว้ในโฟลเดอร์ skills เท่านั้น
เมื่อผู้ใช้สั่งให้สร้างหรือแก้ไขงานตามเวลา/Cron อย่างชัดเจน ให้ใช้ create_schedule หรือ update_schedule โดย create_schedule รับ arguments: name, schedule (Cron 5 ช่อง), prompt, model (ไม่บังคับ), enabled (ไม่บังคับ) และ discord_channel_id (ไม่บังคับ เป็น Channel ID ของ Discord); ส่วน update_schedule รับ job_id และฟิลด์ที่ต้องการแก้ไข โดยใช้ timezone ของ Server
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
        LOGGER.warning("อ่านไฟล์ log ถาวรไม่สำเร็จ: %s", exc)


def skill_dir(name: str) -> Path:
    """Resolve a skill name to its directory inside the skills root."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name).strip().lower()).strip("-")
    if not safe_name:
        raise ValueError("ชื่อสกิลไม่ถูกต้อง")
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    directory = (root / safe_name).resolve()
    if directory.parent != root:
        raise ValueError("ชื่อสกิลอยู่นอกโฟลเดอร์ที่อนุญาต")
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
    return "แนวทางจาก Skills ที่เลือก:\n\n" + "\n\n".join(blocks) if blocks else ""


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
        LOGGER.warning("บันทึก log ถาวรไม่สำเร็จ: %s", exc)
        with APP_LOG_LOCK:
            APP_LOGS.append(record)
    LOGGER.info("%s: %s", event, message)


load_persisted_logs()

DEFAULT_SETTINGS = {
    "agent_name": "Mux",
    "agent_role": "ผู้ช่วย AI อเนกประสงค์",
    "response_language": "auto",
    "response_style": "เป็นมิตร กระชับ และชัดเจน",
    "use_markdown": True,
    "ask_clarifying_questions": True,
    "provider": os.getenv("AI_PROVIDER", "openai"),
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "base_url": os.getenv("AI_BASE_URL", ""),
    "system_prompt": "คุณเป็นผู้ช่วย AI ที่สุภาพ ชัดเจน และช่วยผู้ใช้ให้บรรลุเป้าหมาย",
    "memory_review": "ก่อนตอบ ให้ทบทวนบทสนทนาก่อนหน้าเพื่อรักษาความต่อเนื่อง ตรวจสอบข้อเท็จจริงและงานที่ค้างอยู่ หากข้อมูลขัดแย้งกันให้ถามผู้ใช้ และอย่าเปิดเผยกระบวนการคิดภายใน",
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 1,
    "stream": False,
    "thinking_level": "off",
    "command_mode": "ask",
    "fallback_enabled": False,
    "fallback_provider": os.getenv("AI_FALLBACK_PROVIDER", "openai"),
    "fallback_model": os.getenv("AI_FALLBACK_MODEL", ""),
    "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN", "").strip()),
    "discord_prefix": os.getenv("DISCORD_BOT_PREFIX", "!ai"),
    "terminal_enabled": True,
    "machine_access": True,
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
STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

DISCORD_CONTEXTS: dict[str, deque[dict[str, str]]] = {}
DISCORD_CONVERSATION_IDS: dict[str, str] = {}
DISCORD_CONTEXT_LOCK = threading.Lock()
DISCORD_BOT: Any = None
DISCORD_THREAD: threading.Thread | None = None
DISCORD_LOOP: Any = None
DISCORD_TOKEN_FINGERPRINT = ""


def normalize_provider(value: Any) -> str:
    """Clamp an unknown provider name to a supported provider id."""
    provider = str(value or "openai").strip().lower()
    return provider if provider in PROVIDERS else "openai"


def stored_api_keys(settings: dict[str, Any]) -> dict[str, str]:
    """Return the per-provider API key map from settings."""
    raw = settings.get("api_keys")
    keys = raw if isinstance(raw, dict) else {}
    return {provider: str(keys.get(provider) or "").strip() for provider in PROVIDERS}


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
    return migrate_legacy_api_key(settings)


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
            raise ValueError(f"รูปแบบ cron ไม่ถูกต้อง: {part}")
        base, step_text = match.group(1), match.group(2)
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError("ค่า step ของ cron ต้องมากกว่า 0")
        if base == "*":
            start, end = minimum, upper
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError("ช่วงค่า cron ไม่ถูกต้อง (ค่าแรกต้องไม่มากกว่าค่าสุดท้าย)")
        else:
            start = int(base)
            # "N/step" (e.g. 0/5) starts at N and repeats every step, while a
            # bare "N" is a single value. Treating both as N silently turned
            # "0/5" into "minute 0 only".
            end = upper if step_text else start
        if start > end:
            raise ValueError("ช่วงค่า cron ไม่ถูกต้อง (ค่าแรกต้องไม่มากกว่าค่าสุดท้าย)")
        if start < minimum or end > upper:
            raise ValueError(f"ค่า cron ต้องอยู่ระหว่าง {minimum} ถึง {upper}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("ค่า cron ว่างเปล่า")
    if alias_max is not None:
        # Cron accepts both 0 and 7 for Sunday.
        values = {minimum if value == alias_max else value for value in values}
    if min(values) < minimum or max(values) > maximum:
        raise ValueError(f"ค่า cron ต้องอยู่ระหว่าง {minimum} ถึง {maximum}")
    return values


def validate_cron(expression: str) -> str:
    """Validate a five-field cron expression and return it normalized."""
    aliases = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *"}
    expression = aliases.get(str(expression).strip().lower(), str(expression).strip())
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron ต้องมี 5 ช่อง เช่น */5 * * * * หรือ 0 9 * * 1-5")
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
            log_event("schedule.discord_error", f"ส่งผลงานตามเวลา {job['name']} ไป Discord ไม่สำเร็จ", job=job["id"], error=str(exc))
        update_schedule(job["id"], last_status="สำเร็จ", last_error="", last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        log_event("schedule.success", f"งานตามเวลา {job['name']} สำเร็จ", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        log_event("schedule.error", f"งานตามเวลา {job.get('name', job.get('id', ''))} ล้มเหลว", error=str(exc))
        update_schedule(job["id"], last_status="ล้มเหลว", last_error=redact_secrets(str(exc))[:500], last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
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
                                log_event("schedule.skipped", "ข้ามงานที่ยังทำงานอยู่", job=job_id)
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
                        update_schedule(job.get("id", ""), last_status="ล้มเหลว", last_error="cron ไม่ถูกต้อง")
            except OSError as exc:
                log_event("schedule.error", "อ่านหรือบันทึกงานตามเวลาไม่สำเร็จ", error=str(exc))
        time.sleep(15)


def send_discord_schedule_result(job: dict[str, Any], answer: str) -> None:
    """Send a scheduled job result to its configured Discord channel."""
    channel_id = str(job.get("discord_channel_id") or "").strip()
    if not channel_id:
        return
    if not channel_id.isdigit():
        raise ValueError("Discord Channel ID ต้องเป็นตัวเลข")
    if DISCORD_BOT is None or DISCORD_LOOP is None or DISCORD_LOOP.is_closed():
        raise RuntimeError("Discord bot ยังไม่ได้เชื่อมต่อ")

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
            log_event("schedule.error", "เปิดไฟล์ lock ของ scheduler ไม่สำเร็จ", error=str(exc))
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return
        _SCHEDULER_LOCK_HANDLE = handle
        _SCHEDULER_STARTED = True
    threading.Thread(target=schedule_loop, name="scheduled-ai-jobs", daemon=True).start()


def resolve_project_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a user path inside the project while blocking protected files."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("ต้องระบุ path ภายในโปรเจกต์")
    candidate = (PROJECT_ROOT / raw_path).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise ValueError("อนุญาตเฉพาะ path ภายในโฟลเดอร์โปรเจกต์")
    relative_parts = candidate.relative_to(PROJECT_ROOT).parts
    if any(part in PROTECTED_PARTS for part in relative_parts) or candidate.name in PROTECTED_NAMES:
        raise ValueError("ไม่อนุญาตให้เข้าถึงไฟล์หรือโฟลเดอร์ที่มีข้อมูลลับ")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"ไม่พบ path: {raw_path}")
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
    """Resolve a tool path, reaching the whole machine when machine access is on.

    With machine access the path may be absolute, start with `~`, or be relative
    to the project folder. Without it the old project-only guard applies.
    """
    if not machine_access_enabled():
        return resolve_project_path(raw_path, must_exist)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("ต้องระบุ path")
    candidate = Path(os.path.expanduser(raw_path.strip()))
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = candidate.resolve()
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"ไม่พบ path: {raw_path}")
    return candidate


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
        raise ValueError("คำสั่งต้องอ้างอิงเฉพาะ path ภายในโปรเจกต์")
    if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in parts):
        raise ValueError("ไม่อนุญาตให้เข้าถึงไฟล์หรือโฟลเดอร์ที่มีข้อมูลลับ")


SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log"}
SAFE_GIT_OPTIONS = {
    "-p", "-n", "--oneline", "--stat", "--shortstat", "--name-only", "--name-status",
    "--no-color", "--no-pager", "--graph", "--decorate", "--all", "--cached",
}
SAFE_LS_OPTIONS = {"-a", "-l", "-la", "-al", "-lh", "-lah", "-R", "-t", "-r", "-1", "-h"}


def parse_command(command: str) -> list[str]:
    """Parse one whitelisted command into argv without ever invoking a shell."""
    if any(character in command for character in ("\n", "\r", ";", "|", "&", ">", "<", "`", "$(")):
        raise ValueError("คำสั่งมี syntax ที่ไม่อนุญาต")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError("รูปแบบคำสั่งไม่ถูกต้อง") from exc
    if not argv:
        raise ValueError("ต้องระบุคำสั่ง")
    binary, rest = argv[0], argv[1:]
    if binary == "pwd":
        if rest:
            raise ValueError("pwd ไม่รับ argument")
    elif binary == "ls":
        for token in rest:
            if token.startswith("-"):
                if token not in SAFE_LS_OPTIONS:
                    raise ValueError(f"ไม่อนุญาต ls option {token}")
            else:
                ensure_safe_command_token(token)
    elif binary == "git":
        if not rest or rest[0] not in SAFE_GIT_SUBCOMMANDS:
            raise ValueError("อนุญาตเฉพาะ git status, git diff และ git log")
        for token in rest[1:]:
            if token.startswith("-"):
                if token not in SAFE_GIT_OPTIONS and not token.lstrip("-").isdigit():
                    raise ValueError(f"ไม่อนุญาต git option {token}")
            else:
                ensure_safe_command_token(token)
        # .git/config and .gitattributes can point at external programs or
        # textconv filters; neither may run while inspecting the repository.
        argv = ["git", "-c", "diff.external=", "--no-pager", *rest]
        if rest[0] in {"diff", "log"}:
            argv.extend(["--no-ext-diff", "--no-textconv"])
    elif binary in {"python", "python3"}:
        if rest != ["-m", "py_compile", "app.py"]:
            raise ValueError("อนุญาตเฉพาะการตรวจ syntax ของ app.py")
    else:
        raise ValueError("อนุญาตเฉพาะคำสั่งตรวจสอบโปรเจกต์ที่กำหนดไว้")
    return argv


def request_tool_approval(name: str, arguments: dict[str, Any]) -> str:
    """Create a short-lived approval token for a sensitive tool call."""
    approval_id = secrets.token_urlsafe(24)
    now = time.time()
    with PENDING_APPROVAL_LOCK:
        for key, item in list(PENDING_TOOL_REQUESTS.items()):
            if now - item.get("created_at", 0) > APPROVAL_TTL_SECONDS:
                PENDING_TOOL_REQUESTS.pop(key, None)
        while len(PENDING_TOOL_REQUESTS) >= MAX_PENDING_APPROVALS:
            PENDING_TOOL_REQUESTS.pop(next(iter(PENDING_TOOL_REQUESTS)))
        PENDING_TOOL_REQUESTS[approval_id] = {"name": name, "arguments": arguments, "created_at": now}
    return approval_id


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
        log_event("tool.alias", f"แปลงชื่อ tool {requested_name} เป็น {name}", requested=requested_name, tool=name)
    log_event("tool.start", f"เริ่มใช้ {name}", tool=name, approved=approved)
    if name == "create_skill":
        if not approved:
            raise PermissionError("การสร้างสกิลต้องได้รับการอนุมัติก่อน")
        skill_name = arguments.get("name", "")
        content = arguments.get("content", "")
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("เนื้อหาสกิลไม่ถูกต้องหรือใหญ่เกินขนาดที่อนุญาต")
        path = skill_path(skill_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        try:
            display_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            # AI_WEB_SKILLS_DIR may point outside the project; report it as is.
            display_path = str(path)
        result = {"tool": name, "name": path.parent.name, "path": display_path}
        log_event("tool.success", f"สร้างสกิล {path.parent.name} สำเร็จ", tool=name, path=result["path"])
        return result
    if name == "create_schedule":
        if not approved:
            raise PermissionError("การสร้างงานตามเวลาต้องได้รับการอนุมัติก่อน")
        job_name = str(arguments.get("name", "")).strip()
        prompt = str(arguments.get("prompt", "")).strip()
        if not job_name or not prompt:
            raise ValueError("ต้องระบุชื่องานและ prompt")
        schedule = validate_cron(arguments.get("schedule", ""))
        discord_channel_id = str(arguments.get("discord_channel_id", "")).strip()[:30]
        if discord_channel_id and not discord_channel_id.isdigit():
            raise ValueError("Discord Channel ID ต้องเป็นตัวเลข")
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
        log_event("schedule.created", f"สร้างงานตามเวลา {job['name']} สำเร็จ", job=job["id"], schedule=schedule)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "update_schedule":
        if not approved:
            raise PermissionError("การแก้ไขงานตามเวลาต้องได้รับการอนุมัติก่อน")
        job_id = str(arguments.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("ต้องระบุ job_id")
        with SCHEDULE_LOCK:
            jobs = load_schedules()
            job = next((item for item in jobs if item.get("id") == job_id), None)
            if not job:
                raise ValueError("ไม่พบงานตามเวลา")
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
                    raise ValueError("Discord Channel ID ต้องเป็นตัวเลข")
                job["discord_channel_id"] = channel_id
            if "enabled" in arguments:
                job["enabled"] = bool(arguments["enabled"])
            save_schedules(jobs)
        log_event("schedule.updated", f"แก้ไขงานตามเวลา {job['name']} สำเร็จ", job=job_id)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "list_files":
        machine_access = machine_access_enabled()
        root = resolve_tool_path(arguments.get("path", "."), must_exist=True)
        if not root.is_dir():
            raise ValueError("path นี้ไม่ใช่โฟลเดอร์")
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
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, count=len(files))
        return result

    if name == "read_file":
        machine_access = machine_access_enabled()
        path = resolve_tool_path(arguments.get("path", ""), must_exist=True)
        if not path.is_file():
            raise ValueError("path นี้ไม่ใช่ไฟล์")
        if path.stat().st_size > TOOL_MAX_READ_BYTES:
            raise ValueError("ไฟล์ใหญ่เกินขนาดที่อนุญาตให้อ่าน")
        content = path.read_text(encoding="utf-8", errors="replace")
        if machine_access:
            # Whole-machine reads must not copy stored credentials into the chat
            # transcript or the saved conversation history.
            content = redact_secrets(content)
        result = {"tool": name, "path": display_tool_path(path), "content": content, "scope": "machine" if machine_access else "project"}
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, path=result["path"])
        return result

    if name == "write_file":
        if not approved:
            raise PermissionError("การเขียนไฟล์ต้องได้รับการอนุมัติก่อน")
        path = resolve_tool_path(arguments.get("path", ""))
        content = arguments.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("เนื้อหาไฟล์ใหญ่เกินขนาดที่อนุญาต")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result = {"tool": name, "path": display_tool_path(path), "bytes": len(content.encode("utf-8"))}
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, path=result["path"], bytes=result["bytes"])
        return result

    if name == "run_command":
        if not approved:
            raise PermissionError("การรันคำสั่งต้องได้รับการอนุมัติก่อน")
        command = arguments.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("ต้องระบุคำสั่ง")
        command = command.strip()
        if len(command) > 4000:
            raise ValueError("คำสั่งยาวเกินไป (สูงสุด 4000 ตัวอักษร)")
        if machine_access_enabled():
            # A real shell with the app user's privileges: any binary, pipes,
            # sudo (when the user may run it without a password prompt), and
            # any path on the machine. The approval click is the boundary.
            returncode, stdout, stderr, timed_out, truncated, duration_ms = run_terminal_process(command, PROJECT_ROOT)
            if timed_out:
                returncode = 124
            secrets_found = terminal_secret_values()
            result = {
                "tool": name,
                "command": redact_terminal_output(command, secrets_found),
                "returncode": returncode,
                "stdout": redact_terminal_output(stdout, secrets_found),
                "stderr": redact_terminal_output(stderr, secrets_found),
                "timed_out": timed_out,
                "truncated": truncated,
                "duration_ms": duration_ms,
                "scope": "machine",
            }
            log_event(
                "tool.success" if returncode == 0 else "tool.failed",
                f"รันคำสั่งเสร็จ ({returncode})",
                tool=name,
                command=redact_terminal_output(command, secrets_found)[:300],
                duration_ms=duration_ms,
            )
            return result
        argv = parse_command(command)
        completed = subprocess.run(argv, cwd=PROJECT_ROOT, shell=False, capture_output=True, text=True, timeout=30)
        result = {"tool": name, "command": command, "returncode": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:], "scope": "project"}
        log_event("tool.success" if completed.returncode == 0 else "tool.failed", f"รันคำสั่งเสร็จ ({completed.returncode})", tool=name, command=command)
        return result

    raise ValueError("ไม่รู้จักเครื่องมือนี้")


def terminal_settings() -> dict[str, Any]:
    """Return the settings used by the web terminal."""
    return load_settings()


def terminal_is_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return whether the web terminal is enabled in settings."""
    settings = settings if settings is not None else terminal_settings()
    return bool(settings.get("terminal_enabled", True))


def terminal_shell() -> str:
    """Pick an available POSIX shell, including Termux where /bin/sh may not exist."""
    for candidate in (os.getenv("SHELL"), shutil.which("bash"), shutil.which("sh"), "/system/bin/sh", "/bin/sh"):
        if candidate and Path(candidate).exists():
            return candidate
    return "sh"


def terminal_environment() -> dict[str, str]:
    """Inherit the server environment without exposing credentials to commands."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(part in name.upper() for part in TERMINAL_SENSITIVE_ENV_PARTS)
    }
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("LANG", "C.UTF-8")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def terminal_secret_values() -> list[str]:
    """Collect secret values that terminal output must never expose."""
    settings = terminal_settings()
    values = {value for value in stored_api_keys(settings).values() if value}
    discord_token = get_discord_token(settings)
    if discord_token:
        values.add(discord_token)
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(part in name.upper() for part in TERMINAL_SENSITIVE_ENV_PARTS):
            values.add(value)
    return sorted(values, key=len, reverse=True)


PEM_REDACTED_MARKER = "•••••••• (ซ่อน private key)"
PEM_BLOCK_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
PEM_MARKER_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
# How far before a truncated capture tail to look for an opening BEGIN line.
TERMINAL_PEM_LOOKBACK_BYTES = 8192


def terminal_pem_state(text: str, inside: bool = False) -> bool:
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


def redact_terminal_output(text: str, secrets_found: list[str]) -> str:
    """Replace known secrets and any private key block in terminal output."""
    for secret in secrets_found:
        text = text.replace(secret, "••••••••")
    return PEM_BLOCK_PATTERN.sub(PEM_REDACTED_MARKER, text)


SHELL_PATH_SEPARATOR_PATTERN = re.compile(r"[;&|<>()`$\s=]+")


def ensure_terminal_paths_allowed(command: str) -> None:
    """Reject terminal commands whose arguments point at protected project paths.

    The web terminal runs through a real shell, so each token is split on the
    shell operators (`;`, `|`, `&`, redirections, `$`, `=`) before the protected
    names are checked, so `cd .env; ls` is checked as `cd .env`. This is still a
    best-effort guard: a path assembled at runtime can slip past it, so the real
    boundary is running the server as an unprivileged user. Output is
    additionally scrubbed of API keys and PEM private keys before it leaves the
    server.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        for fragment in SHELL_PATH_SEPARATOR_PATTERN.split(token):
            candidate = fragment.replace("\\", "/").strip()
            if not candidate or candidate.startswith("-"):
                continue
            parts = [part for part in candidate.split("/") if part not in {"", "."}]
            if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in parts):
                raise PermissionError("Terminal ไม่อนุญาตให้เข้าถึงไฟล์หรือโฟลเดอร์ที่มีข้อมูลลับ")


SECRET_QUERY_PATTERN = re.compile(r"([?&](?:key|api_key|api-key|token|access_token)=)[^&\s\"'<>]+", re.IGNORECASE)


def redact_secrets(text: str, api_key: str | None = None) -> str:
    """Remove API keys and tokens from text before it is returned or logged."""
    value = SECRET_QUERY_PATTERN.sub(r"\1••••••••", str(text))
    # Redact the submitted request's API key if provided
    if api_key:
        value = value.replace(api_key, "••••••••")
    try:
        secrets_found = terminal_secret_values()
    except (OSError, ValueError):
        secrets_found = []
    return redact_terminal_output(value, secrets_found)


def read_terminal_capture(handle: Any) -> tuple[str, bool]:
    """Read at most the tail of a captured stream so runaway output cannot exhaust memory."""
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    start = max(0, size - TERMINAL_MAX_OUTPUT_BYTES)
    cut = start > 0
    # A private key block may open before the tail starts, so derive the
    # redaction state from a bounded window in front of it instead of relying on
    # the BEGIN line being inside the returned text.
    starts_inside = False
    if cut:
        lookback_start = max(0, start - TERMINAL_PEM_LOOKBACK_BYTES)
        handle.seek(lookback_start)
        starts_inside = terminal_pem_state(
            handle.read(start - lookback_start).decode("utf-8", errors="replace")
        )
    handle.seek(start)
    text = mask_unterminated_pem(
        handle.read().decode("utf-8", errors="replace"), starts_inside
    )
    if cut:
        text = "… (ตัดข้อความส่วนต้นออก เนื่องจากมีผลลัพธ์จำนวนมาก)\n" + text
    return text, cut


def resolve_terminal_cwd(raw_path: Any) -> Path:
    """Resolve a terminal working directory inside the project root."""
    value = str(raw_path or ".").strip() or "."
    if value in {"~", "~/"}:
        candidate = PROJECT_ROOT
    else:
        if value.startswith("~/"):
            value = value[2:]
        candidate = (PROJECT_ROOT / value).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise ValueError("Terminal ถูกจำกัดให้ทำงานภายในโฟลเดอร์โปรเจกต์")
    if any(part in PROTECTED_PARTS for part in candidate.relative_to(PROJECT_ROOT).parts):
        raise PermissionError("Terminal ถูกจำกัดไม่ให้เข้าโฟลเดอร์ที่มีข้อมูลลับ")
    if not candidate.exists():
        raise FileNotFoundError(f"ไม่พบโฟลเดอร์: {raw_path}")
    if not candidate.is_dir():
        raise ValueError("path นี้ไม่ใช่โฟลเดอร์")
    return candidate


def relative_terminal_cwd(path: Path) -> str:
    """Render a terminal working directory relative to the project root."""
    relative = path.relative_to(PROJECT_ROOT)
    return "." if str(relative) == "." else relative.as_posix()


def terminal_identity() -> tuple[str, str]:
    """Return the shell user and host name shown in the terminal header."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = str(os.getenv("USER") or "user")
    try:
        host = socket.gethostname() or "server"
    except OSError:
        host = "server"
    return user, host


def run_terminal_process(command: str, cwd: Path) -> tuple[int, str, str, bool, bool, int]:
    """Run a shell command with capped output and a hard timeout for the whole process group."""
    started_at = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        process = subprocess.Popen(
            command,
            shell=True,
            executable=terminal_shell(),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=out_file,
            stderr=err_file,
            env=terminal_environment(),
            start_new_session=True,
        )
        try:
            process.wait(timeout=TERMINAL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            process.wait()
        stdout, stdout_cut = read_terminal_capture(out_file)
        stderr, stderr_cut = read_terminal_capture(err_file)
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    return process.returncode, stdout, stderr, timed_out, stdout_cut or stderr_cut, duration_ms


def execute_terminal_command(command: str, cwd: Path) -> dict[str, Any]:
    """Run one web terminal command and return its output and new cwd."""
    settings = terminal_settings()
    if not terminal_is_enabled(settings):
        raise PermissionError("หน้า Terminal ถูกปิดใช้งานอยู่ใน Settings")
    stripped = command.strip()
    if not stripped:
        raise ValueError("กรุณาพิมพ์คำสั่ง")
    if len(stripped) > 4000:
        raise ValueError("คำสั่งยาวเกินไป (สูงสุด 4000 ตัวอักษร)")
    ensure_terminal_paths_allowed(stripped)

    changed_directory = False
    cd_match = re.fullmatch(r"cd(?:\s+(.*))?", stripped)
    if cd_match:
        target = (cd_match.group(1) or "").strip()
        if target in {"", "~"}:
            new_cwd = PROJECT_ROOT
        else:
            try:
                tokens = shlex.split(target)
            except ValueError as exc:
                raise ValueError("รูปแบบ path ของ cd ไม่ถูกต้อง") from exc
            if len(tokens) != 1:
                raise ValueError("cd รับ path ได้ครั้งละหนึ่งรายการ")
            new_cwd = resolve_terminal_cwd(tokens[0])
        cwd = new_cwd
        changed_directory = True
        result = {
            "command": stripped,
            "cwd": relative_terminal_cwd(cwd),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "truncated": False,
            "changed_directory": changed_directory,
            "duration_ms": 0,
        }
    else:
        returncode, stdout, stderr, timed_out, truncated, duration_ms = run_terminal_process(stripped, cwd)
        if timed_out:
            returncode = 124
        secrets_found = terminal_secret_values()
        result = {
            "command": stripped,
            "cwd": relative_terminal_cwd(cwd),
            "returncode": returncode,
            "stdout": redact_terminal_output(stdout, secrets_found),
            "stderr": redact_terminal_output(stderr, secrets_found),
            "timed_out": timed_out,
            "truncated": truncated,
            "changed_directory": changed_directory,
            "duration_ms": duration_ms,
        }
        log_event(
            "tool.terminal",
            f"Terminal รันคำสั่งเสร็จ ({returncode})",
            command=redact_terminal_output(stripped, secrets_found)[:300],
            returncode=returncode,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
    return result


def parse_tool_request(answer: str) -> dict[str, Any] | None:
    """Return the first tool call found in an AI answer, if any."""
    requests = parse_tool_requests(answer)
    return requests[0] if requests else None


def parse_tool_requests(answer: str) -> list[dict[str, Any]]:
    """Parse every tool call so multiple Skill files can be inspected in one turn."""
    if not isinstance(answer, str):
        return []
    matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", answer, re.IGNORECASE | re.DOTALL)
    if not matches:
        return []
    requests = []
    for raw_request in matches:
        try:
            request = json.loads(raw_request.strip())
        except json.JSONDecodeError as exc:
            log_event("tool.parse_failed", "อ่าน tool_call ไม่สำเร็จ", error=str(exc))
            raise ValueError("รูปแบบ tool_call ไม่ถูกต้อง") from exc
        if not isinstance(request, dict) or not isinstance(request.get("name"), str) or not isinstance(request.get("arguments", {}), dict):
            raise ValueError("ข้อมูล tool_call ไม่ถูกต้อง")
        tool_request = {"name": request["name"], "arguments": request.get("arguments", {})}
        log_event("tool.request", f"AI ขอใช้ {tool_request['name']}", tool=tool_request["name"])
        requests.append(tool_request)
    return requests


def find_history_file(conversation_id: str) -> Path | None:
    """Find the history file that stores one conversation id."""
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    for path in HISTORY_ROOT.rglob(f"*_{conversation_id}.json"):
        return path
    return None


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
            log_event("history.error", "เปิดไฟล์ lock ของประวัติไม่สำเร็จ", error=str(exc))
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


def _write_history_record(path: Path, record: dict[str, Any]) -> None:
    """Write one history record atomically so readers never see a partial file."""
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
        raise HistoryLocked("ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนบันทึกทับ")
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
    raw_title = payload.get("title")
    existing_title = (
        existing_record.get("title") if isinstance(existing_record.get("title"), str) else ""
    )
    title = (
        raw_title.strip()[:100]
        if isinstance(raw_title, str) and raw_title.strip()
        else existing_title.strip()[:100] or "บทสนทนาใหม่"
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
        append_history_messages(conversation_id, turn)
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
        LOGGER.warning("อ่านไฟล์ประวัติไม่สำเร็จ (%s): %s", path.name, exc)
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


def list_models(provider: str, settings: dict[str, Any]) -> list[dict[str, str]]:
    """Fetch the available models for a provider, using its API key."""
    provider = normalize_provider(provider)
    key = get_api_key(provider, settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key จึงดึงรายการโมเดลไม่ได้")
    if provider == "gemini":
        response = requests.get(f"{get_base_url('gemini', settings)}/models", params={"key": key}, timeout=30)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [{"id": item["name"].removeprefix("models/"), "name": item.get("displayName", item["name"])} for item in models if "generateContent" in item.get("supportedGenerationMethods", [])]
    if provider == "anthropic":
        try:
            response = requests.get(
                f"{get_base_url('anthropic', settings)}/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            raise RuntimeError(f"Anthropic ตอบกลับ HTTP {status} — ตรวจสอบ API key อีกครั้ง") from exc
        data = response.json().get("data", [])
        models = [
            {"id": item["id"], "name": item.get("display_name") or item["id"]}
            for item in data
            if isinstance(item, dict) and item.get("id")
        ]
        if models:
            return models
        raise RuntimeError("Anthropic ไม่ส่งรายการโมเดลกลับมา")
    base_url = get_base_url(provider, settings)
    response = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    response.raise_for_status()
    models = response.json().get("data", [])
    return [{"id": item["id"], "name": item["id"]} for item in sorted(models, key=lambda item: item.get("id", ""))]


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


def key_fingerprint(key: str) -> str:
    """Return a short stable fingerprint for a secret, safe to compare."""
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]


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


def provider_key_check(provider: str, settings: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Check credentials and, for Anthropic, the selected model's real usability."""
    provider = normalize_provider(provider)
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base_url = get_base_url(provider, settings)
    model = str(settings.get("model") or "").strip()
    cache_key = f"{provider}|{base_url}|{model}|{key_fingerprint(key)}|{language}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < STATUS_CACHE_TTL:
        return {**cached[1], "cached": True}
    result: dict[str, Any]
    try:
        if provider == "gemini":
            response = requests.get(
                f"{base_url}/models",
                params={"key": key},
                timeout=20,
            )
        elif provider == "anthropic":
            response = requests.get(
                f"{base_url}/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=20,
            )
        else:
            response = requests.get(
                f"{base_url or 'https://api.openai.com/v1'}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=20,
            )
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
            )
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
    except requests.RequestException as exc:
        result = {"ready": False, "reason": status_message(language, "connection_failed", label=label, error=exc.__class__.__name__), "status": None}
    STATUS_CACHE[cache_key] = (time.time(), result)
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


def clean_messages(messages: list[dict[str, str]], settings: dict[str, Any]) -> list[dict[str, str]]:
    """Merge attachments into message text and prepend the system prompt."""
    result = [{"role": "system", "content": settings.get("system_prompt", "")}] if settings.get("system_prompt") else []
    for item in messages:
        content = item.get("content", "")
        attachment = item.get("attachment")
        if isinstance(attachment, dict) and attachment.get("name") and attachment.get("content"):
            content = f"{content}\n\n[ไฟล์แนบ: {attachment['name']}]\n```\n{attachment['content']}\n```"
        result.append({"role": item.get("role", "user"), "content": content})
    return result


def agent_profile_prompt(settings: dict[str, Any]) -> str:
    """Turn the user-configured agent profile into stable runtime guidance."""
    language = {"auto": "ตอบตามภาษาของผู้ใช้", "th": "ตอบเป็นภาษาไทย", "en": "ตอบเป็นภาษาอังกฤษ"}.get(str(settings.get("response_language", "auto")), "ตอบตามภาษาของผู้ใช้")
    questions = "ถามกลับเมื่อข้อมูลไม่พอหรือคำสั่งกำกวม" if settings.get("ask_clarifying_questions", True) else "หลีกเลี่ยงการถามกลับและระบุสมมติฐานที่ใช้"
    markdown = "ใช้ Markdown เมื่อช่วยให้อ่านง่าย" if settings.get("use_markdown", True) else "ไม่ใช้ Markdown ที่ซับซ้อน"
    return "แนวทางโปรไฟล์ Agent:\n" + "\n".join((
        f"- ชื่อที่ใช้แนะนำตัว: {str(settings.get('agent_name') or 'Mux')[:80]}",
        f"- บทบาท: {str(settings.get('agent_role') or '')[:500]}",
        f"- โทนการตอบ: {str(settings.get('response_style') or '')[:500]}",
        f"- ภาษา: {language}", f"- รูปแบบ: {markdown}", f"- การขอข้อมูลเพิ่ม: {questions}",
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
    """Return whether an OpenAI model is a reasoning model (o-series or GPT-5)."""
    if normalize_provider(provider) != "openai":
        return False
    return bool(re.match(r"^(?:o[0-9]|gpt-5)", str(model or "").strip().lower()))


def call_openai(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one chat completion request to an OpenAI-compatible endpoint."""
    key = get_api_key(settings["provider"], settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key")

    base_url = get_base_url(settings["provider"], settings)
    model = str(settings["model"])
    reasoning_model = is_openai_reasoning_model(settings["provider"], model)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if reasoning_model:
        # Reasoning models reject max_tokens, temperature, and top_p.
        payload["max_completion_tokens"] = settings["max_tokens"]
    else:
        payload["temperature"] = settings["temperature"]
        payload["max_tokens"] = settings["max_tokens"]
        payload["top_p"] = settings["top_p"]
    if reasoning_model and settings.get("thinking_level") in {"low", "medium", "high"}:
        payload["reasoning_effort"] = settings["thinking_level"]
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"], normalize_usage(data.get("usage"), "prompt_tokens", "completion_tokens", "total_tokens")


def call_gemini(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one generateContent request to Gemini with thinking options."""
    key = get_api_key("gemini", settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Gemini API key")

    contents: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "system":
            continue
        role = "model" if message["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message["content"]}]})

    model = settings["model"]
    generation_config = {
        "temperature": settings["temperature"],
        "topP": settings["top_p"],
        "maxOutputTokens": settings["max_tokens"],
    }
    thinking_level = settings.get("thinking_level", "off")
    if thinking_level in {"low", "medium", "high"}:
        if settings["model"].startswith("gemini-2.5"):
            generation_config["thinkingConfig"] = {"thinkingBudget": {"low": 1024, "medium": 4096, "high": 8192}[thinking_level]}
        else:
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    request_url = f"{get_base_url('gemini', settings)}/models/{model}:generateContent"
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
        )
        if response.status_code not in {429, 503} or attempt == 2:
            break
        time.sleep(1.5 * (2**attempt))
    response.raise_for_status()
    data = response.json()
    usage = data.get("usageMetadata", {})
    return data["candidates"][0]["content"]["parts"][0]["text"], normalize_usage(
        usage, "promptTokenCount", "candidatesTokenCount", "totalTokenCount"
    )


def call_anthropic(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Send one messages request to Anthropic with the configured settings."""
    key = get_api_key("anthropic", settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Anthropic API key")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    response = requests.post(
        f"{get_base_url('anthropic', settings)}/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": settings["model"],
            "system": system,
            "messages": [m for m in messages if m["role"] != "system"],
            "max_tokens": settings["max_tokens"],
            "temperature": settings["temperature"],
        },
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    usage = data.get("usage", {})
    return data["content"][0]["text"], normalize_usage(usage, "input_tokens", "output_tokens", None)


def call_provider(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
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
    return [text[index:index + limit] for index in range(0, len(text), limit)] or ["(ไม่มีข้อความตอบกลับ)"]


def stop_discord_bot() -> None:
    """Ask the running Discord client to close, if it is connected."""
    if DISCORD_BOT is not None and DISCORD_LOOP is not None and not DISCORD_LOOP.is_closed():
        try:
            DISCORD_LOOP.call_soon_threadsafe(lambda: __import__("asyncio").create_task(DISCORD_BOT.close()))
        except RuntimeError:
            pass


def start_discord_bot() -> None:
    """Run the optional Discord client in a daemon thread beside Flask."""
    global DISCORD_BOT, DISCORD_THREAD, DISCORD_LOOP, DISCORD_TOKEN_FINGERPRINT
    settings = load_settings()
    token = get_discord_token(settings)
    if not settings.get("discord_enabled") or not token:
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive() and DISCORD_TOKEN_FINGERPRINT == key_fingerprint(token):
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive():
        stop_discord_bot()
    try:
        import discord
    except ImportError:
        log_event("discord.error", "ยังไม่ได้ติดตั้ง discord.py")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    prefix = str(settings.get("discord_prefix") or "!ai").strip() or "!ai"
    commands_synced = False

    class AIClient(discord.Client):
        async def on_ready(self) -> None:
            """Sync slash commands once and log the successful connection."""
            nonlocal commands_synced
            if not commands_synced:
                try:
                    await command_tree.sync()
                    commands_synced = True
                    log_event("discord.commands", "ลงทะเบียน Discord slash commands แล้ว")
                except Exception as exc:
                    log_event("discord.error", "ลงทะเบียน Discord slash commands ไม่สำเร็จ", error=str(exc))
            log_event("discord.connected", "เชื่อมต่อ Discord bot แล้ว", user=str(self.user))

        async def on_message(self, message: Any) -> None:
            """Reply to mentions, prefixed messages, and DMs through the agent."""
            if message.author == self.user:
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
                await message.reply(f"พิมพ์ข้อความหลัง {prefix} หรือ mention bot เพื่อเริ่มคุยได้เลยครับ")
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
    command_tree = discord.app_commands.CommandTree(client)

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
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะผู้ดูแล server เท่านั้นครับ", ephemeral=True)
        return False

    async def check_model_availability(provider: str, model: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Check a provider and model off the event loop without saving settings."""
        probe_settings = dict(settings)
        probe_settings["provider"] = provider
        probe_settings["model"] = model
        return await asyncio.to_thread(provider_readiness, probe_settings, "th")

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
                        "ปฏิเสธการสร้างงานตามเวลาจากผู้ใช้ที่ไม่มีสิทธิ์ผู้ดูแล",
                        channel=context_key,
                    )
                    stripped = TOOL_CALL_BLOCK_PATTERN.sub("", answer).strip()
                    answer = stripped or "การสร้างหรือแก้ไขงานตามเวลาใช้ได้เฉพาะผู้ดูแล server เท่านั้นครับ"
                    break
                result = await asyncio.to_thread(
                    run_local_tool,
                    tool_request["name"],
                    tool_request["arguments"],
                    True,
                )
                messages.extend([
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": f"ผลการสร้างงานตามเวลา:\n{json.dumps(result, ensure_ascii=False)}\n\nตอบเป็นข้อความธรรมดา ยืนยันชื่อ งาน เวลา Cron และสิ่งที่จะให้ AI ทำ ห้ามแสดง tool_call หรือ JSON"},
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
            log_event("discord.message", "ตอบข้อความจาก Discord แล้ว", channel=context_key)
            if fallback_used:
                log_event("discord.fallback", "ใช้ fallback model สำหรับ Discord", model=fallback_used, channel=context_key)
            return answer
        except Exception as exc:
            log_event("discord.error", "ตอบข้อความจาก Discord ไม่สำเร็จ", error=str(exc))
            return "ขออภัยครับ ตอนนี้เรียก AI ไม่สำเร็จ กรุณาตรวจสอบการตั้งค่าในเว็บ"

    @command_tree.command(name="ai", description="ส่งงานหรือพูดคุยกับ AI agent")
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

    @command_tree.command(name="clear", description="ล้างบริบทการสนทนาของห้องนี้")
    async def clear_command(interaction: Any) -> None:
        """Handle the /clear slash command."""
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(str(interaction.channel_id), None)
            DISCORD_CONVERSATION_IDS.pop(str(interaction.channel_id), None)
        await interaction.response.send_message("ล้างบริบทการสนทนาของห้องนี้แล้วครับ")

    @command_tree.command(name="new", description="เปิดแชทใหม่และสร้างประวัติใหม่บนเว็บ")
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
            f"เปิดแชทใหม่แล้วครับ ประวัติขึ้นบนเว็บทันที (ID: `{record['id'][:8]}`)"
        )

    async def model_autocomplete(interaction: Any, current_text: str) -> list[Any]:
        """Provide model id autocomplete choices for Discord commands."""
        settings = load_settings()
        selected = getattr(getattr(interaction, "namespace", None), "provider", settings.get("provider", "openai"))
        selected_provider = selected.value if hasattr(selected, "value") else selected
        selected_provider = normalize_provider(selected_provider)
        try:
            models = await asyncio.to_thread(list_models, selected_provider, settings)
            names = [str(item.get("id", "")) for item in models if item.get("id")]
        except Exception:
            names = FALLBACK_MODELS.get(selected_provider, [])
        query = str(current_text or "").strip().lower()
        return [
            discord.app_commands.Choice(name=name[:100], value=name[:100])
            for name in names
            if not query or query in name.lower()
        ][:25]

    @command_tree.command(name="models", description="เปลี่ยน provider และ model ของ AI agent")
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
                current_model = current.get("model") if current.get("provider") == selected_provider else ""
                names = [item["id"] for item in available[:25]]
                listing = "\n".join(
                    f"• `{name}`{' ← กำลังใช้งาน' if name == current_model else ''} · พร้อมใช้งาน"
                    for name in names
                ) or "ไม่พบรายการ model"
                await interaction.followup.send(
                    f"Models ของ {PROVIDER_LABELS[selected_provider]} (ตรวจจาก API แล้ว):\n{listing}"
                )
            except Exception as exc:
                names = FALLBACK_MODELS.get(selected_provider, [])
                listing = "\n".join(f"• `{name}` · ยังยืนยันไม่ได้" for name in names) or "ไม่มีรายการสำรอง"
                await interaction.followup.send(
                    f"API ของ {PROVIDER_LABELS[selected_provider]} ใช้งานไม่ได้: {str(exc)[:220]}\nรายการสำรอง:\n{listing}"
                )
            return
        current = load_settings()
        current["provider"] = selected_provider
        current["model"] = model.strip()[:200]
        save_settings(current)
        STATUS_CACHE.clear()
        availability = await check_model_availability(selected_provider, current["model"], current)
        state = "พร้อมใช้งาน" if availability.get("ready") else f"ยังใช้ไม่ได้: {availability.get('reason', 'ตรวจสอบไม่สำเร็จ')}"
        await interaction.followup.send(
            f"เปลี่ยน agent เป็น `{PROVIDER_LABELS[selected_provider]}` / `{current['model']}` แล้วครับ · {state}"
        )

    @command_tree.command(name="ping", description="ตรวจสอบความหน่วงของ Discord bot")
    async def ping_command(interaction: Any) -> None:
        """Handle the /ping slash command."""
        latency_ms = round(client.latency * 1000)
        await interaction.response.send_message(f"Pong! Discord latency: `{latency_ms} ms`")

    @command_tree.command(name="fallback", description="ตั้ง fallback model สำหรับห้อง Discord นี้")
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
            selected = channel_fallbacks.get(channel_key) or current.get("fallback_model") or "ไม่ได้ตั้งค่า"
            if selected == "ไม่ได้ตั้งค่า":
                await interaction.followup.send("Fallback model ของห้องนี้: ยังไม่ได้ตั้งค่า")
                return
            availability = await check_model_availability(current.get("provider", "openai"), selected, current)
            state = "พร้อมใช้งาน" if availability.get("ready") else f"ใช้ไม่ได้: {availability.get('reason', 'ตรวจสอบไม่สำเร็จ')}"
            await interaction.followup.send(f"Fallback model ของห้องนี้: `{selected}` · {state}")
            return
        if not await require_server_admin(interaction):
            return
        await interaction.response.defer()
        if model.strip().lower() in {"off", "none", "ปิด"}:
            channel_fallbacks.pop(channel_key, None)
            message = "ปิด fallback เฉพาะห้องแล้วครับ (จะใช้ค่า fallback หลักถ้ามี)"
        else:
            channel_fallbacks[channel_key] = model.strip()[:200]
            message = f"ตั้ง fallback model ของห้องนี้เป็น `{channel_fallbacks[channel_key]}` แล้วครับ"
        current["discord_fallback_models"] = channel_fallbacks
        save_settings(current)
        if channel_key in channel_fallbacks:
            availability = await check_model_availability(current.get("provider", "openai"), channel_fallbacks[channel_key], current)
            state = "พร้อมใช้งาน" if availability.get("ready") else f"ยังใช้ไม่ได้: {availability.get('reason', 'ตรวจสอบไม่สำเร็จ')}"
            message += f" · {state}"
        await interaction.followup.send(message)

    @command_tree.command(name="thread", description="สร้างห้องย่อยสำหรับหัวข้อใหม่")
    async def thread_command(interaction: Any, name: str) -> None:
        """Handle the /thread slash command."""
        channel = interaction.channel
        if not hasattr(channel, "create_thread"):
            await interaction.response.send_message("คำสั่งนี้ใช้ในห้องข้อความของ server เท่านั้นครับ", ephemeral=True)
            return
        try:
            thread = await channel.create_thread(
                name=name.strip()[:100] or "หัวข้อใหม่",
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )
            await interaction.response.send_message(f"สร้างห้องย่อยให้แล้วครับ: {thread.mention}")
        except Exception as exc:
            await interaction.response.send_message(f"สร้างห้องย่อยไม่สำเร็จ: {str(exc)[:300]}", ephemeral=True)

    @command_tree.command(name="status", description="ตรวจสอบสถานะ AI agent")
    async def status_command(interaction: Any) -> None:
        """Handle the /status slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "พร้อมใช้งาน" if availability.get("ready") else f"ใช้ไม่ได้: {availability.get('reason', 'ตรวจสอบไม่สำเร็จ')}"
        await interaction.followup.send(
            f"Discord: เชื่อมต่อแล้ว\nProvider: {current.get('provider', 'openai')}\nModel: {current.get('model', 'ยังไม่ได้เลือก')}\nสถานะ AI: {state}"
        )

    @command_tree.command(name="model", description="ดู provider และ model ที่ agent ใช้งาน")
    async def model_command(interaction: Any) -> None:
        """Handle the /model slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "พร้อมใช้งาน" if availability.get("ready") else f"ใช้ไม่ได้: {availability.get('reason', 'ตรวจสอบไม่สำเร็จ')}"
        await interaction.followup.send(
            f"Provider: `{current.get('provider', 'openai')}` · Model: `{current.get('model', 'ยังไม่ได้เลือก')}` · {state}"
        )

    @command_tree.command(name="invite", description="สร้างลิงก์เชิญ bot ด้วยสิทธิ Administrator")
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
            "ลิงก์นี้ใช้เชิญหรือเชิญ bot เข้า server ใหม่ด้วยสิทธิ Administrator "
            "ผู้กดลิงก์ต้องมีสิทธิ์จัดการ server เอง:\n" + url,
            ephemeral=True,
        )

    @command_tree.command(name="help", description="แสดงคำสั่งของ AI agent")
    async def help_command(interaction: Any) -> None:
        """Handle the /help slash command."""
        await interaction.response.send_message(
            "คำสั่งของ AI agent:\n"
            "`/ai prompt` ส่งงานหรือคุยกับ AI\n"
            "`/new` เปิดแชทใหม่และสร้างประวัติบนเว็บ\n"
            "`/clear` ล้างบริบทห้อง\n"
            "`/models` เปลี่ยน provider/model\n"
            "`/ping` ตรวจ latency ของ bot\n"
            "`/thread` สร้างห้องย่อยตามหัวข้อ\n"
            "`/fallback model` ตั้ง fallback เฉพาะห้อง\n"
            "`/invite` สร้างลิงก์เชิญด้วยสิทธิ Administrator (admin เท่านั้น)\n"
            "`/status` ตรวจสถานะ bot\n"
            "`/model` ดูโมเดลปัจจุบัน\n"
            "`/help` แสดงคำสั่งนี้\n\n"
            f"นอกจากนี้ mention bot หรือใช้ `{prefix} ข้อความ` ได้ด้วย"
        )

    DISCORD_BOT = client
    DISCORD_TOKEN_FINGERPRINT = key_fingerprint(token)

    def run_client() -> None:
        """Run the Discord client in its own event loop for the bot thread."""
        global DISCORD_LOOP
        import asyncio
        DISCORD_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(DISCORD_LOOP)
        try:
            DISCORD_LOOP.run_until_complete(client.start(token))
        except Exception as exc:
            log_event("discord.error", "Discord bot หยุดทำงาน", error=str(exc))
        finally:
            DISCORD_LOOP.close()

    DISCORD_THREAD = threading.Thread(target=run_client, name="discord-bot", daemon=True)
    DISCORD_THREAD.start()


@app.get("/api/tools")
def tools_get():
    """List the local tools, their scope, and which ones require approval."""
    settings = load_settings()
    required = approval_required_tools(settings)
    machine_access = machine_access_enabled(settings)
    return jsonify({
        "scope": "machine" if machine_access else str(PROJECT_ROOT),
        "machine_access": machine_access,
        "tools": [
            {"name": "list_files", "approval_required": "list_files" in required},
            {"name": "read_file", "approval_required": "read_file" in required},
            {"name": "write_file", "approval_required": "write_file" in required},
            {"name": "run_command", "approval_required": "run_command" in required},
            {"name": "create_skill", "approval_required": "create_skill" in required},
            {"name": "create_schedule", "approval_required": "create_schedule" in required},
            {"name": "update_schedule", "approval_required": "update_schedule" in required},
            {"name": "execute_command", "alias_for": "run_command", "approval_required": "run_command" in required},
        ],
    })


@app.post("/api/tools/execute")
def tools_execute():
    """Execute a local tool call after validating its approval token."""
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    arguments = body.get("arguments", {})
    approval_id = body.get("approval_id")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        log_event("tool.invalid", "ข้อมูลเครื่องมือไม่ถูกต้อง")
        return jsonify({"ok": False, "error": "ข้อมูลเครื่องมือไม่ถูกต้อง"}), 400
    canonical_name = TOOL_ALIASES.get(name, name)
    approved = False
    if canonical_name in approval_required_tools():
        approved = consume_tool_approval(approval_id, name, arguments)
        if not approved:
            log_event("tool.denied", f"ปฏิเสธ {name} เพราะไม่มีการอนุมัติที่ถูกต้อง", tool=name)
            return jsonify({"ok": False, "error": "คำขออนุมัติไม่ถูกต้องหรือหมดอายุ กรุณาขอใหม่อีกครั้ง"}), 403
    try:
        result = run_local_tool(name, arguments, approved=approved)
        return jsonify({"ok": True, "result": result})
    except (FileNotFoundError, PermissionError, ValueError, OSError, subprocess.SubprocessError) as exc:
        log_event("tool.error", f"ใช้ {name} ไม่สำเร็จ", tool=name, error=str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/terminal/info")
def terminal_info():
    """Report terminal availability, identity, shell, and working scope."""
    settings = terminal_settings()
    user, host = terminal_identity()
    return jsonify({
        "enabled": terminal_is_enabled(settings),
        "user": user,
        "host": host,
        "cwd": ".",
        "scope": f"~/{PROJECT_ROOT.name}",
        "shell": Path(terminal_shell()).name,
        "timeout_seconds": TERMINAL_TIMEOUT_SECONDS,
    })


@app.post("/api/terminal/exec")
def terminal_exec():
    """Run one terminal command submitted by the web UI."""
    body = request.get_json(silent=True) or {}
    command = body.get("command")
    if not isinstance(command, str):
        return jsonify({"ok": False, "error": "ต้องระบุคำสั่ง"}), 400
    try:
        cwd = resolve_terminal_cwd(body.get("cwd", "."))
        result = execute_terminal_command(command, cwd)
        return jsonify({"ok": True, **result})
    except (PermissionError, FileNotFoundError, ValueError, OSError, subprocess.SubprocessError) as exc:
        log_event("tool.terminal_error", "Terminal รันคำสั่งไม่สำเร็จ", error=str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/logs")
def logs_get():
    """Return the in-memory diagnostic log entries."""
    with APP_LOG_LOCK:
        items = list(APP_LOGS)
    return jsonify({"items": items})


@app.delete("/api/logs")
def logs_delete():
    """Delete the persisted log file and clear the in-memory view."""
    try:
        with APP_LOG_LOCK:
            deleted = len(APP_LOGS)
            APP_LOGS.clear()
            LOG_FILE.unlink(missing_ok=True)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"ลบ log ไม่สำเร็จ: {exc}"}), 500
    return jsonify({"ok": True, "deleted": deleted})


@app.get("/api/schedules")
def schedules_get():
    """List scheduled jobs and the server timezone."""
    return jsonify({"items": load_schedules(), "timezone": datetime.now().astimezone().tzname()})


@app.post("/api/schedules")
def schedules_create():
    """Create a scheduled job from the settings UI payload."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    prompt = str(body.get("prompt", "")).strip()
    if not name or not prompt:
        return jsonify({"error": "กรุณาระบุชื่องานและ prompt"}), 400
    try:
        schedule = validate_cron(body.get("schedule", ""))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    discord_channel_id = str(body.get("discord_channel_id", "")).strip()[:30]
    if discord_channel_id and not discord_channel_id.isdigit():
        return jsonify({"error": "Discord Channel ID ต้องเป็นตัวเลข"}), 400
    job = {"id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()), "name": name[:100], "schedule": schedule, "prompt": prompt[:10_000], "model": str(body.get("model", "")).strip()[:200], "discord_channel_id": discord_channel_id, "enabled": bool(body.get("enabled", True)), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "last_run_at": None, "last_status": None, "last_error": ""}
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        jobs.append(job)
        save_schedules(jobs)
    return jsonify(job), 201


@app.patch("/api/schedules/<job_id>")
def schedules_update(job_id: str):
    """Update fields of one scheduled job from the settings UI."""
    body = request.get_json(silent=True) or {}
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        job = next((item for item in jobs if item.get("id") == job_id), None)
        if not job:
            return jsonify({"error": "ไม่พบงานตามเวลา"}), 404
        if "schedule" in body:
            try:
                job["schedule"] = validate_cron(body["schedule"])
            except (TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400
        if "name" in body:
            job["name"] = str(body["name"]).strip()[:100] or job["name"]
        if "prompt" in body:
            job["prompt"] = str(body["prompt"]).strip()[:10_000]
        if "model" in body:
            job["model"] = str(body["model"]).strip()[:200]
        if "discord_channel_id" in body:
            discord_channel_id = str(body["discord_channel_id"]).strip()[:30]
            if discord_channel_id and not discord_channel_id.isdigit():
                return jsonify({"error": "Discord Channel ID ต้องเป็นตัวเลข"}), 400
            job["discord_channel_id"] = discord_channel_id
        if "enabled" in body:
            job["enabled"] = bool(body["enabled"])
        save_schedules(jobs)
    return jsonify(job)


@app.post("/api/schedules/<job_id>/run")
def schedules_run(job_id: str):
    """Start a scheduled job immediately in a background thread."""
    jobs = load_schedules()
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if not job:
        return jsonify({"error": "ไม่พบงานตามเวลา"}), 404
    with SCHEDULE_RUNNING_LOCK:
        if job_id in SCHEDULE_RUNNING:
            return jsonify({"error": "งานนี้กำลังทำงานอยู่"}), 409
        SCHEDULE_RUNNING.add(job_id)
    try:
        threading.Thread(target=execute_schedule, args=(job,), daemon=True).start()
    except Exception:
        with SCHEDULE_RUNNING_LOCK:
            SCHEDULE_RUNNING.discard(job_id)
        raise
    return jsonify({"ok": True, "job_id": job_id}), 202


@app.delete("/api/schedules/<job_id>")
def schedules_delete(job_id: str):
    """Delete one scheduled job by id."""
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        remaining = [job for job in jobs if job.get("id") != job_id]
        if len(remaining) == len(jobs):
            return jsonify({"error": "ไม่พบงานตามเวลา"}), 404
        save_schedules(remaining)
    return jsonify({"ok": True})


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
        "label": str(label or "").strip()[:60] or "อุปกรณ์ที่เชื่อมต่อ",
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


def current_auth_session() -> dict[str, Any] | None:
    """Resolve the request cookie to a live paired-device session."""
    token = request.cookies.get(AUTH_SESSION_COOKIE, "")
    if not token:
        return None
    digest = hash_auth_token(token)
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        for item in state["sessions"]:
            if not hmac.compare_digest(str(item.get("token_hash") or ""), digest):
                continue
            if auth_expired(item, now):
                return None
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
        f"  ใช้ได้ถึง {record['expires_at']} และใช้ได้ครั้งเดียว\n"
        "  ฝั่ง client เปิด /pair แล้วใส่คีย์นี้\n"
        + "=" * 62 + "\n",
        flush=True,
    )


@app.before_request
def reject_cross_site_mutation():
    """Refuse state-changing requests that a browser sent from another site."""
    if request.method not in MUTATING_METHODS:
        return None
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        # Non-browser clients (curl, scripts) do not send Origin.
        return None
    parsed = urlsplit(origin)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request.host.lower():
        return None
    log_event("security.cross_origin", "ปฏิเสธคำขอที่มาจากเว็บอื่น", path=request.path, method=request.method)
    return jsonify({"error": "คำขอจากเว็บอื่นถูกปฏิเสธ"}), 403


@app.errorhandler(413)
def request_too_large(_error):
    """Answer an oversized upload with JSON instead of Werkzeug's HTML page."""
    return jsonify({"error": "ข้อมูลที่ส่งมีขนาดใหญ่เกินกว่าที่อนุญาต"}), 413


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
        return jsonify({"error": "This device is not paired yet. Enter a Pairing Key.", "auth_required": True}), 401
    return redirect("/pair", code=302)


@app.get("/templates/<page>/<filename>")
def page_asset(page: str, filename: str):
    """Serve the CSS/JS stored beside a page template.

    Only known page folders and the .css/.js extensions are exposed, so the
    Jinja templates themselves can never be downloaded.
    """
    if page not in PAGE_ASSETS or Path(filename).suffix.lower() not in {".css", ".js"}:
        abort(404)
    return send_from_directory(TEMPLATES_ROOT / page, filename)


@app.get("/pair")
def pair_page():
    """Render the pairing page where a client submits the server key."""
    if current_auth_session():
        return redirect("/")
    return render_template("pair/pair.html", ttl_minutes=AUTH_PAIRING_TTL_MINUTES, session_days=AUTH_SESSION_DAYS)


@app.get("/api/auth/status")
def auth_status():
    """Report whether this device is paired without exposing any secret."""
    session = current_auth_session() if AUTH_ENABLED else None
    return no_store(jsonify({
        "enabled": AUTH_ENABLED,
        "authenticated": bool(session) or not AUTH_ENABLED,
        "session": {
            "id": session.get("id"),
            "label": session.get("label", ""),
            "created_at": session.get("created_at"),
            "last_seen_at": session.get("last_seen_at"),
            "expires_at": session.get("expires_at"),
        } if session else None,
    }))


@app.post("/api/auth/pair")
def auth_pair():
    """Exchange a valid single-use pairing key for a session cookie."""
    if not AUTH_ENABLED:
        return jsonify({"ok": True, "redirect": "/"})
    body = request.get_json(silent=True) or {}
    client_ip = request.remote_addr or "unknown"
    if not pairing_attempt_allowed(client_ip):
        return jsonify({"error": "Too many pairing attempts. Please wait a few minutes and try again."}), 429
    if not consume_pairing_key(body.get("key")):
        record_pairing_failure(client_ip)
        return jsonify({"error": "This Pairing Key is invalid, expired, or already used."}), 401
    token = create_auth_session(
        label=str(body.get("label") or ""),
        user_agent=request.headers.get("User-Agent", ""),
        client_ip=client_ip,
    )
    log_event("auth.paired", "จับคู่อุปกรณ์ใหม่สำเร็จ", ip=client_ip)
    response = jsonify({"ok": True, "redirect": "/"})
    response.set_cookie(
        AUTH_SESSION_COOKIE,
        token,
        max_age=AUTH_SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
        path="/",
    )
    return response


@app.get("/api/auth/sessions")
def auth_sessions_list():
    """List paired devices so the owner can review and revoke them."""
    current = current_auth_session() or {}
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        save_auth_state(state)
        items = [{
            "id": item.get("id"),
            "label": item.get("label", ""),
            "created_at": item.get("created_at"),
            "last_seen_at": item.get("last_seen_at"),
            "expires_at": item.get("expires_at"),
            "current": item.get("id") == current.get("id"),
        } for item in state["sessions"]]
    items.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    return no_store(jsonify({"items": items, "auth_enabled": AUTH_ENABLED}))


@app.post("/api/auth/pairing-keys")
def auth_create_pairing_key():
    """Generate a fresh pairing key for a new device from an authorized session."""
    if not AUTH_ENABLED:
        return jsonify({"error": "Web auth is disabled. Set AI_WEB_AUTH=on to use pairing keys."}), 400
    body = request.get_json(silent=True) or {}
    record = generate_pairing_key(str(body.get("label") or ""))
    log_event("auth.pairing_key", "สร้าง Pairing Key ใหม่")
    return jsonify({"ok": True, **record}), 201


@app.post("/api/auth/logout")
def auth_logout():
    """Revoke this device's session and clear its cookie."""
    token = request.cookies.get(AUTH_SESSION_COOKIE, "")
    digest = hash_auth_token(token) if token else ""
    if digest:
        with AUTH_LOCK:
            state = load_auth_state()
            remaining = [
                item for item in state["sessions"]
                if not hmac.compare_digest(str(item.get("token_hash") or ""), digest)
            ]
            if len(remaining) != len(state["sessions"]):
                state["sessions"] = remaining
                save_auth_state(state)
    response = jsonify({"ok": True, "redirect": "/pair"})
    response.delete_cookie(AUTH_SESSION_COOKIE, path="/")
    return response


@app.delete("/api/auth/sessions/<session_id>")
def auth_revoke_session(session_id: str):
    """Revoke one paired device by id."""
    if not revoke_auth_session(session_id):
        return jsonify({"error": "Device not found"}), 404
    log_event("auth.revoked", "ยกเลิกอุปกรณ์ที่เชื่อมต่อ", session=session_id)
    return jsonify({"ok": True})


@app.get("/")
def index():
    """Render the single-page web application."""
    return render_template("index/index.html")


@app.get("/api/settings")
def settings_get():
    """Return settings with secrets masked for the settings UI."""
    settings = load_settings()
    provider = normalize_provider(settings.get("provider"))
    key = get_api_key(provider, settings)
    safe = {key_: value for key_, value in settings.items() if key_ not in {"api_keys", "api_key", "discord_token"}}
    safe["provider"] = provider
    safe["api_key"] = "" if not key else "••••••••"
    safe["has_api_key"] = bool(key)
    safe["key_providers"] = [name for name in PROVIDERS if key_is_configured(name, settings)]
    discord_token = get_discord_token(settings)
    safe["discord_token"] = "••••••••" if discord_token else ""
    safe["has_discord_token"] = bool(discord_token)
    safe["discord_status"] = discord_status()
    safe["available_skills"] = [{"name": item["name"]} for item in list_skills()]
    return jsonify(safe)


@app.get("/api/skills")
def skills_get():
    """List the available skills with their content."""
    return jsonify({"items": list_skills()})


@app.get("/api/skills/<name>")
def skill_get(name: str):
    """Return one skill's content by name."""
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": "ไม่พบ Skill"}), 404
        return jsonify({"name": path.parent.name, "content": path.read_text(encoding="utf-8")[:20_000]})
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/skills")
def skills_create():
    """Create a new skill from the settings UI payload."""
    body = request.get_json(silent=True) or {}
    try:
        result = run_local_tool("create_skill", {"name": body.get("name", ""), "content": body.get("content", "")}, approved=True)
        return jsonify(result), 201
    except (OSError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.put("/api/skills/<name>")
def skills_update(name: str):
    """Replace the content of an existing skill."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
        return jsonify({"error": "เนื้อหา Skill ไม่ถูกต้องหรือใหญ่เกินขนาดที่อนุญาต"}), 400
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": "ไม่พบ Skill"}), 404
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return jsonify({"ok": True, "name": path.parent.name})
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/skills/<name>")
def skills_delete(name: str):
    """Delete a skill folder by name."""
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": "ไม่พบ Skill"}), 404
        shutil.rmtree(path.parent)
        return jsonify({"ok": True, "name": path.parent.name})
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/status")
def status_get():
    """Report whether the selected provider/model is actually usable."""
    settings = load_settings()
    return jsonify(provider_readiness(settings, normalize_language(request.args.get("lang"))))


@app.get("/api/history")
def history_list():
    """Return history summaries sorted by most recently updated."""
    records = []
    if HISTORY_ROOT.exists():
        for path in HISTORY_ROOT.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(record, dict):
                # A stray list/scalar JSON file must not break the whole list.
                continue
            records.append({key: record.get(key) for key in ("id", "title", "created_at", "updated_at", "locked", "pinned")})
    records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return jsonify({"items": records})


@app.get("/api/history/<conversation_id>")
def history_get(conversation_id: str):
    """Return one full conversation record by id."""
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    record = read_history_file(path)
    if record is None:
        return jsonify({"error": "ไฟล์ประวัติเสียหายหรืออ่านไม่ได้ กรุณาตรวจสอบไฟล์ในโฟลเดอร์ history"}), 409
    return jsonify(record)


@app.patch("/api/history/<conversation_id>")
def history_update(conversation_id: str):
    """Rename, lock, or pin one conversation record."""
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if not path or not path.exists():
            return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
        record = read_history_file(path)
        if record is None:
            return jsonify({"error": "ไฟล์ประวัติเสียหายหรืออ่านไม่ได้ กรุณาตรวจสอบไฟล์ในโฟลเดอร์ history"}), 409
        body = request.get_json(silent=True) or {}
        if record.get("locked") and "title" in body:
            return jsonify({"error": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนเปลี่ยนชื่อ"}), 423
        if "title" in body:
            title = str(body["title"]).strip()
            if title:
                record["title"] = title[:100]
        if "locked" in body:
            record["locked"] = bool(body["locked"])
        if "pinned" in body:
            record["pinned"] = bool(body["pinned"])
        _write_history_record(path, record)
        return jsonify(record)


@app.delete("/api/history/<conversation_id>")
def history_delete(conversation_id: str):
    """Delete one conversation record unless it is locked."""
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if not path or not path.exists():
            return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
        record = read_history_file(path)
        if record is None:
            return jsonify({"error": "ไฟล์ประวัติเสียหายหรืออ่านไม่ได้ กรุณาตรวจสอบไฟล์ในโฟลเดอร์ history"}), 409
        if record.get("locked"):
            return jsonify({"error": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนลบ"}), 423
        path.unlink()
        return jsonify({"ok": True})


@app.post("/api/history/<conversation_id>/messages")
def history_append(conversation_id: str):
    """Append messages to a conversation that still exists."""
    body = request.get_json(silent=True) or {}
    messages = body.get("messages")
    generation = body.get("generation")
    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "รูปแบบประวัติไม่ถูกต้อง"}), 400
    try:
        record = append_history_messages(conversation_id, messages, generation)
    except HistoryConflict:
        return jsonify({"error": "เกิดความขัดแย้งข้อมูล: บันทึกถูกปรับปรุงโดยผู้อื่น กรุณาโหลดใหม่"}), 409
    if record is None:
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    return jsonify(record)


@app.post("/api/history")
def history_save():
    """Store a conversation payload sent by the web UI."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("messages"), list):
        return jsonify({"error": "รูปแบบประวัติไม่ถูกต้อง"}), 400
    try:
        return jsonify(save_history(body))
    except HistoryLocked as exc:
        return jsonify({"error": str(exc)}), 423


def models_response(provider: str, settings: dict[str, Any]):
    """Build the model list response shared by the GET and POST model endpoints."""
    try:
        models = list_models(provider, settings)
        return jsonify({"provider": provider, "models": models, "source": "api"})
    except (requests.RequestException, RuntimeError, KeyError, TypeError) as exc:
        api_key = get_api_key(provider, settings)
        fallback = [{"id": name, "name": name} for name in FALLBACK_MODELS.get(provider, [])]
        return jsonify({"provider": provider, "models": fallback, "source": "fallback", "error": redact_secrets(str(exc), api_key=api_key)}), 502


@app.get("/api/models")
def models_get():
    """Return provider models, falling back to a static list on failure."""
    settings = load_settings()
    provider = normalize_provider(request.args.get("provider", settings.get("provider", "openai")))
    return models_response(provider, settings)


@app.post("/api/models")
def models_post():
    """Return provider models for a key submitted before it is saved."""
    settings = load_settings()
    body = request.get_json(silent=True) or {}
    provider = normalize_provider(body.get("provider") or settings.get("provider", "openai"))
    base_url = body.get("base_url")
    # An explicit empty string means "use the provider default"; only an
    # omitted base_url leaves the configured value untouched.
    if isinstance(base_url, str):
        settings["base_url"] = base_url.strip()
    submitted_key = body.get("api_key")
    if isinstance(submitted_key, str) and submitted_key.strip() and submitted_key != "••••••••":
        keys = stored_api_keys(settings)
        keys[provider] = submitted_key.strip()
        settings["api_keys"] = keys
    return models_response(provider, settings)


@app.put("/api/settings")
def settings_put():
    """Persist editable settings, including the configured fallback provider."""
    body = request.get_json(silent=True) or {}
    current = load_settings()
    previous_provider = normalize_provider(current.get("provider"))
    allowed = {"agent_name", "agent_role", "response_language", "response_style", "use_markdown", "ask_clarifying_questions", "provider", "model", "base_url", "system_prompt", "memory_review", "skills", "temperature", "max_tokens", "top_p", "thinking_level", "stream", "fallback_enabled", "fallback_provider", "fallback_model", "discord_enabled", "discord_prefix", "terminal_enabled", "machine_access"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    current["provider"] = normalize_provider(current.get("provider"))
    if current["provider"] != previous_provider and "base_url" not in body:
        # A base URL belongs to one provider. Dropping it on a provider switch
        # stops hf/or/groq requests from being sent to the previous endpoint.
        current["base_url"] = ""
    current["agent_name"] = str(current.get("agent_name") or "Mux").strip()[:80]
    current["agent_role"] = str(current.get("agent_role") or "ผู้ช่วย AI อเนกประสงค์").strip()[:500]
    language = str(current.get("response_language") or "auto").strip().lower()
    current["response_language"] = language if language in {"auto", "th", "en"} else "auto"
    current["response_style"] = str(current.get("response_style") or "เป็นมิตร กระชับ และชัดเจน").strip()[:500]
    current["use_markdown"] = bool(current.get("use_markdown", True))
    current["ask_clarifying_questions"] = bool(current.get("ask_clarifying_questions", True))
    thinking_level = str(current.get("thinking_level") or "off").strip().lower()
    current["thinking_level"] = thinking_level if thinking_level in {"off", "low", "medium", "high"} else "off"
    current["fallback_enabled"] = bool(current.get("fallback_enabled"))
    current["fallback_provider"] = normalize_provider(current.get("fallback_provider"))
    current["fallback_model"] = str(current.get("fallback_model") or "")[:200]
    current["discord_enabled"] = bool(current.get("discord_enabled"))
    current["discord_prefix"] = str(current.get("discord_prefix") or "!ai").strip()[:30] or "!ai"
    current["terminal_enabled"] = bool(current.get("terminal_enabled", True))
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
    current.pop("api_key", None)
    save_settings(current)
    STATUS_CACHE.clear()
    if current.get("discord_enabled"):
        start_discord_bot()
    else:
        stop_discord_bot()
    return jsonify({"ok": True, "provider": current["provider"], "has_api_key": key_is_configured(current["provider"], current)})


@app.post("/api/settings/test")
def settings_test():
    """Test submitted settings against the provider without saving them."""
    settings = load_settings()
    body = request.get_json(silent=True) or {}
    # Test submitted settings without persisting credentials first. This lets
    # the UI validate a new key before it becomes part of the saved settings.
    for key in {"provider", "model", "base_url", "system_prompt", "memory_review", "temperature", "max_tokens", "top_p", "thinking_level"}:
        if key in body:
            settings[key] = body[key]
    submitted_key = body.get("api_key")
    if isinstance(submitted_key, str) and submitted_key.strip() and submitted_key != "••••••••":
        keys = stored_api_keys(settings)
        keys[normalize_provider(settings.get("provider"))] = submitted_key.strip()
        settings["api_keys"] = keys
    provider = normalize_provider(settings.get("provider"))
    STATUS_CACHE.clear()
    try:
        messages = clean_messages([{"role": "user", "content": "ตอบคำว่า OK สั้น ๆ"}], settings)
        answer, _usage = call_provider(messages, settings)
        STATUS_CACHE.clear()
        return jsonify({"ok": True, "answer": answer, "provider": provider})
    except requests.HTTPError as exc:
        detail = ""
        if exc.response is not None:
            try:
                payload = exc.response.json()
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
            else:
                detail = exc.response.text
            detail = detail[:300]
        api_key = get_api_key(provider, settings)
        message = redact_secrets(detail or str(exc), api_key=api_key)
        return jsonify({"ok": False, "provider": provider, "error": f"{PROVIDER_LABELS[provider]}: {message}"}), 502
    except (requests.RequestException, KeyError, IndexError, RuntimeError) as exc:
        api_key = get_api_key(provider, settings)
        return jsonify({"ok": False, "provider": provider, "error": redact_secrets(str(exc), api_key=api_key)}), 502


@app.post("/api/settings/reset")
def settings_reset():
    """Delete the persisted settings file and clear the status cache."""
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
    STATUS_CACHE.clear()
    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    """Answer one chat turn, retrying once with the configured fallback."""
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "กรุณาส่งข้อความ"}), 400

    provider = "openai"
    # Bound before the try block: the error handlers below must never raise a
    # NameError that hides the real cause.
    settings: dict[str, Any] = {}
    try:
        log_event("chat.start", "เริ่มประมวลผลข้อความ", message_count=len(messages))
        settings = load_settings()
        provider = str(settings.get("provider", "openai")).lower()
        request_skills = body.get("skills")
        if isinstance(request_skills, list):
            # Slash commands can apply a skill to one turn without changing
            # the skills saved in Settings.
            available_skills = {item["name"] for item in list_skills()}
            settings["skills"] = list(dict.fromkeys(
                name for name in map(str, request_skills) if name in available_skills
            ))
        requested_thinking = body.get("thinking_level")
        if requested_thinking in {"off", "low", "medium", "high"}:
            settings["thinking_level"] = requested_thinking
        requested_model = body.get("model")
        if isinstance(requested_model, str) and requested_model.strip():
            settings["model"] = requested_model.strip()
        command_mode = body.get("command_mode", settings.get("command_mode", "ask"))
        if command_mode not in {"ask", "auto", "fast"}:
            command_mode = "ask"
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
                f"แนวทางทบทวนความจำ:\n{settings.get('memory_review', '')}" if settings.get("memory_review") else "",
                selected_skill_prompt(settings),
                TOOL_INSTRUCTIONS,
            ) if part
        )
        provider = str(settings.get("provider", "openai")).lower()
        messages = clean_messages(messages, settings)
        started_at = time.perf_counter()
        fallback_used = None
        try:
            answer, usage = call_provider(messages, settings)
        except requests.HTTPError as primary_error:
            fallback_provider = normalize_provider(settings.get("fallback_provider"))
            fallback_model = str(settings.get("fallback_model") or "").strip()
            primary_provider = normalize_provider(settings.get("provider"))
            status_code = primary_error.response.status_code if primary_error.response is not None else None
            same_target = fallback_provider == primary_provider and fallback_model == settings["model"]
            can_fallback = (
                bool(settings.get("fallback_enabled"))
                and fallback_model
                and not same_target
                and status_code in {400, 404, 429, 500, 502, 503, 504}
            )
            if not can_fallback:
                raise
            if fallback_provider != primary_provider:
                settings["base_url"] = ""
            settings["provider"] = fallback_provider
            settings["model"] = fallback_model
            answer, usage = call_provider(messages, settings)
            fallback_used = fallback_model
        for _ in range(6):
            try:
                tool_requests = parse_tool_requests(answer)
            except ValueError as exc:
                log_event("tool.parse_failed", "ข้าม tool_call ที่ไม่สมบูรณ์", error=str(exc))
                tool_requests = []
            if not tool_requests:
                break
            required_tools = approval_required_tools(settings)
            approval_request = next(
                (item for item in tool_requests if TOOL_ALIASES.get(item["name"], item["name"]) in required_tools),
                None,
            )
            # Machine access always asks, whatever the command mode says.
            if approval_request and (machine_access_enabled(settings) or command_mode not in {"auto", "fast"}):
                return jsonify({
                    "answer": "AI ขอใช้เครื่องมือที่ต้องได้รับอนุมัติก่อน",
                    "provider": provider,
                    "tool_request": approval_request,
                    "approval_id": request_tool_approval(approval_request["name"], approval_request["arguments"]),
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    "usage": usage,
                    "model": settings["model"],
                })
            results = []
            for tool_request in tool_requests:
                result = run_local_tool(
                    tool_request["name"],
                    tool_request["arguments"],
                    approved=bool(approval_request),
                )
                results.append(result)
            messages.extend([
                {"role": "assistant", "content": answer},
                {"role": "user", "content": f"ผลการใช้เครื่องมือ:\n{json.dumps(results, ensure_ascii=False)}\n\nตอบผู้ใช้เป็นข้อความธรรมดา อธิบายชื่อและหน้าที่ของแต่ละ Skill ที่ตรวจพบ ห้ามแสดง tool_call หรือ JSON"},
            ])
            answer, usage = call_provider(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        log_event("chat.success", "ตอบข้อความสำเร็จ", provider=provider, model=settings["model"], duration_ms=duration_ms)
        return jsonify({"answer": answer, "provider": provider, "model": settings["model"], "fallback_used": fallback_used, "duration_ms": duration_ms, "usage": usage})
    except requests.HTTPError as exc:
        log_event("provider.error", "ผู้ให้บริการตอบกลับด้วย HTTP error", status=exc.response.status_code if exc.response is not None else "unknown")
        api_key = safe_stored_api_key(provider, settings)
        if exc.response is not None and exc.response.status_code in {429, 503}:
            provider_label = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic"}.get(provider, "ผู้ให้บริการ")
            return jsonify({"error": f"{provider_label} กำลังมีผู้ใช้หนาแน่นหรือถูกจำกัดอัตราการเรียก กรุณาลองใหม่อีกครั้ง หรือเลือกโมเดลอื่น"}), 503
        detail = redact_secrets(exc.response.text if exc.response is not None else str(exc), api_key=api_key)[:500]
        return jsonify({"error": f"เรียก API ไม่สำเร็จ: {detail}"}), 502
    except (KeyError, IndexError, RuntimeError, ValueError, FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        api_key = safe_stored_api_key(provider, settings)
        log_event("chat.error", "ประมวลผลข้อความไม่สำเร็จ", error=str(exc))
        return jsonify({"error": redact_secrets(str(exc), api_key=api_key)}), 500


def tls_configuration() -> Any:
    """Return a Werkzeug ssl_context for HTTPS, or None to serve plain HTTP."""
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    if cert or key:
        if not (cert and key):
            raise SystemExit("ต้องตั้ง AI_WEB_TLS_CERT และ AI_WEB_TLS_KEY พร้อมกัน")
        missing = [path for path in (cert, key) if not Path(path).is_file()]
        if missing:
            raise SystemExit(f"ไม่พบไฟล์ใบรับรอง/คีย์: {', '.join(missing)}")
        return (cert, key)
    if os.getenv("AI_WEB_TLS_ADHOC", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "adhoc"
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


def build_tls_context(ssl_context: Any) -> Any:
    """Turn a tls_configuration() value into a ready ssl.SSLContext."""
    if isinstance(ssl_context, tuple):
        return load_ssl_context(*ssl_context)
    return generate_adhoc_ssl_context()


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
        print(f"✅ ยกเลิกอุปกรณ์ที่เชื่อมต่อทั้งหมดแล้ว ({revoke_all_auth_sessions()})", flush=True)
    if "--pairing-key" in argv:
        if not AUTH_ENABLED:
            print("Web auth ปิดอยู่ — ตั้ง AI_WEB_AUTH=on เพื่อสร้าง Pairing Key", flush=True)
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


if __name__ == "__main__":
    if auth_cli(sys.argv[1:]):
        raise SystemExit(0)
    start_scheduler()
    start_discord_bot()
    print_pairing_banner(bootstrap_pairing_key())
    port = int(os.getenv("PORT", "5000"))
    ssl_context = tls_configuration()
    scheme = "https" if ssl_context else "http"
    print(f"🔒 เปิดให้บริการที่ {scheme}://<ip>:{port}" if ssl_context else f"🌐 เปิดให้บริการที่ http://<ip>:{port}", flush=True)
    if ssl_context:
        print("   คุกกี้ session จะถูกตั้งเป็น Secure เพราะ request.is_secure เป็นจริง", flush=True)
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

