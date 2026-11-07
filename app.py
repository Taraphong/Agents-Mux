import os
import asyncio
import fcntl
import hashlib
import json
import logging
import re
import secrets
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from collections import deque

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
APP_LOGS: list[dict[str, Any]] = []
APP_LOG_LOCK = threading.Lock()
LOGGER = logging.getLogger("ai-web")
LOG_FILE = Path(os.getenv("AI_WEB_LOG_FILE", "logs/app-log.jsonl"))
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))
HISTORY_ROOT = Path(os.getenv("AI_WEB_HISTORY_DIR", "history"))
SCHEDULE_FILE = Path(os.getenv("AI_WEB_SCHEDULE_FILE", "scheduled-jobs.json"))
SCHEDULE_LOCK = threading.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = Path(os.getenv("AI_WEB_SKILLS_DIR", "skills"))
TOOL_MAX_READ_BYTES = 200_000
TOOL_MAX_WRITE_BYTES = 200_000
PENDING_TOOL_REQUESTS: dict[str, dict[str, Any]] = {}
PENDING_APPROVAL_LOCK = threading.Lock()
APPROVAL_TTL_SECONDS = 15 * 60
MAX_PENDING_APPROVALS = 50
APPROVAL_REQUIRED_TOOLS = {"write_file", "run_command", "create_schedule", "update_schedule"}
SCHEDULE_LOCK_FILE = Path(f"{SCHEDULE_FILE}.lock")
SCHEDULE_RUNNING: set[str] = set()
SCHEDULE_RUNNING_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_START_LOCK = threading.Lock()
_SCHEDULER_LOCK_HANDLE: Any = None
PROTECTED_NAMES = {".env", ".app-settings.json"}
PROTECTED_PARTS = {"history", ".venv", ".git", "__pycache__"}
TOOL_INSTRUCTIONS = """
คุณมีเครื่องมือจำกัดอยู่ในโฟลเดอร์โปรเจกต์เท่านั้น หากต้องอ่านไฟล์หรือดูรายการไฟล์ ให้ร้องขอด้วยรูปแบบนี้เพียงอย่างเดียว:
<tool_call>{"name":"read_file","arguments":{"path":"app.py"}}</tool_call>
หรือ <tool_call>{"name":"list_files","arguments":{"path":"."}}</tool_call>
หากต้องเขียนไฟล์ ให้ใช้ชื่อ write_file และหากต้องรันคำสั่ง ให้ใช้ชื่อ run_command (ระบบยอมรับ execute_command เป็นชื่อเก่าด้วย) ระบบจะรอการอนุมัติจากผู้ใช้ก่อนเสมอ
ห้ามขออ่าน .env, .app-settings.json, history, .venv, .git หรือไฟล์ลับ
หากต้องสร้างหรือปรับปรุงสกิล ให้ใช้เครื่องมือ create_skill พร้อมชื่อไฟล์ .md และเนื้อหาสกิลที่ชัดเจน ระบบจะจำกัดการเขียนไว้ในโฟลเดอร์ skills เท่านั้น
เมื่อผู้ใช้สั่งให้สร้างหรือแก้ไขงานตามเวลา/Cron อย่างชัดเจน ให้ใช้ create_schedule หรือ update_schedule โดย create_schedule รับ arguments: name, schedule (Cron 5 ช่อง), prompt, model (ไม่บังคับ), enabled (ไม่บังคับ) และ discord_channel_id (ไม่บังคับ เป็น Channel ID ของ Discord); ส่วน update_schedule รับ job_id และฟิลด์ที่ต้องการแก้ไข โดยใช้ timezone ของ Server
""".strip()

TOOL_ALIASES = {"execute_command": "run_command"}


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
        safe_details[key] = str(value)[:500]
    record = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": str(event)[:60],
        "message": str(message)[:500],
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
    "base_url": "https://api.openai.com/v1",
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
}

FALLBACK_MODELS = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini", "o3"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
}

PROVIDERS = ("openai", "gemini", "anthropic")
PROVIDER_LABELS = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic"}
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
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
    provider = str(value or "openai").strip().lower()
    return provider if provider in PROVIDERS else "openai"


def stored_api_keys(settings: dict[str, Any]) -> dict[str, str]:
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
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return migrate_legacy_api_key(settings)


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_schedules() -> list[dict[str, Any]]:
    if not SCHEDULE_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_schedules(jobs: list[dict[str, Any]]) -> None:
    SCHEDULE_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        if part == "*":
            values.update(range(minimum, maximum + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            if step < 1:
                raise ValueError("cron step ต้องมากกว่า 0")
            values.update(range(minimum, maximum + 1, step))
        elif "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            if start > end:
                raise ValueError("ช่วง cron ไม่ถูกต้อง")
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values or min(values) < minimum or max(values) > maximum:
        raise ValueError("ค่า cron อยู่นอกช่วงที่อนุญาต")
    return values


def validate_cron(expression: str) -> str:
    aliases = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *"}
    expression = aliases.get(str(expression).strip().lower(), str(expression).strip())
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron ต้องมี 5 ช่อง เช่น */5 * * * * หรือ 0 9 * * 1-5")
    for field, minimum, maximum in zip(fields, (0, 0, 1, 1, 0), (59, 23, 31, 12, 6)):
        cron_values(field, minimum, maximum)
    return expression


def cron_matches(expression: str, now: datetime) -> bool:
    minute, hour, day_of_month, month, day_of_week = validate_cron(expression).split()
    if now.minute not in cron_values(minute, 0, 59):
        return False
    if now.hour not in cron_values(hour, 0, 23):
        return False
    if now.month not in cron_values(month, 1, 12):
        return False
    dom_matches = now.day in cron_values(day_of_month, 1, 31)
    dow_matches = ((now.weekday() + 1) % 7) in cron_values(day_of_week, 0, 6)
    # Standard cron ORs day-of-month and day-of-week when both are restricted.
    if day_of_month.strip() == "*" or day_of_week.strip() == "*":
        return dom_matches and dow_matches
    return dom_matches or dow_matches


def update_schedule(job_id: str, **changes: Any) -> None:
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        for job in jobs:
            if job.get("id") == job_id:
                job.update(changes)
                break
        save_schedules(jobs)


def execute_schedule(job: dict[str, Any]) -> None:
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
        messages = clean_messages([{"role": "user", "content": job["prompt"]}], settings)
        started_at = time.perf_counter()
        answer, usage = call_provider(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        save_history({"title": f"⏰ {job['name']}", "messages": [
            {"role": "user", "content": job["prompt"], "schedule_id": job["id"]},
            {"role": "assistant", "content": answer, "duration_ms": duration_ms, "usage": usage, "schedule_id": job["id"]},
        ]})
        send_discord_schedule_result(job, answer)
        update_schedule(job["id"], last_status="สำเร็จ", last_error="", last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        log_event("schedule.success", f"งานตามเวลา {job['name']} สำเร็จ", job=job["id"], duration_ms=duration_ms)
    except Exception as exc:
        log_event("schedule.error", f"งานตามเวลา {job.get('name', job.get('id', ''))} ล้มเหลว", error=str(exc))
        update_schedule(job["id"], last_status="ล้มเหลว", last_error=str(exc)[:500], last_run_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    finally:
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id:
            with SCHEDULE_RUNNING_LOCK:
                SCHEDULE_RUNNING.discard(job_id)


def schedule_loop() -> None:
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
    channel_id = str(job.get("discord_channel_id") or "").strip()
    if not channel_id:
        return
    if not channel_id.isdigit():
        raise ValueError("Discord Channel ID ต้องเป็นตัวเลข")
    if DISCORD_BOT is None or DISCORD_LOOP is None or DISCORD_LOOP.is_closed():
        raise RuntimeError("Discord bot ยังไม่ได้เชื่อมต่อ")

    async def deliver() -> None:
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
    elif binary in {"python", "python3"}:
        if rest != ["-m", "py_compile", "app.py"]:
            raise ValueError("อนุญาตเฉพาะการตรวจ syntax ของ app.py")
    else:
        raise ValueError("อนุญาตเฉพาะคำสั่งตรวจสอบโปรเจกต์ที่กำหนดไว้")
    return argv


def request_tool_approval(name: str, arguments: dict[str, Any]) -> str:
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
        result = {"tool": name, "name": path.parent.name, "path": str(path.relative_to(PROJECT_ROOT))}
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
        root = resolve_project_path(arguments.get("path", "."), must_exist=True)
        if not root.is_dir():
            raise ValueError("path นี้ไม่ใช่โฟลเดอร์")
        files: list[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(directory for directory in dirnames if directory not in PROTECTED_PARTS)
            for filename in sorted(filenames):
                if filename in PROTECTED_NAMES:
                    continue
                if len(files) >= 500:
                    truncated = True
                    break
                files.append(str(Path(dirpath, filename).relative_to(PROJECT_ROOT)))
            if truncated:
                break
        result = {"tool": name, "files": files, "truncated": truncated}
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, count=len(files))
        return result

    if name == "read_file":
        path = resolve_project_path(arguments.get("path", ""), must_exist=True)
        if not path.is_file():
            raise ValueError("path นี้ไม่ใช่ไฟล์")
        if path.stat().st_size > TOOL_MAX_READ_BYTES:
            raise ValueError("ไฟล์ใหญ่เกินขนาดที่อนุญาตให้อ่าน")
        result = {"tool": name, "path": str(path.relative_to(PROJECT_ROOT)), "content": path.read_text(encoding="utf-8")}
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, path=result["path"])
        return result

    if name == "write_file":
        if not approved:
            raise PermissionError("การเขียนไฟล์ต้องได้รับการอนุมัติก่อน")
        path = resolve_project_path(arguments.get("path", ""))
        content = arguments.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("เนื้อหาไฟล์ใหญ่เกินขนาดที่อนุญาต")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result = {"tool": name, "path": str(path.relative_to(PROJECT_ROOT)), "bytes": len(content.encode("utf-8"))}
        log_event("tool.success", f"ใช้ {name} สำเร็จ", tool=name, path=result["path"], bytes=result["bytes"])
        return result

    if name == "run_command":
        if not approved:
            raise PermissionError("การรันคำสั่งต้องได้รับการอนุมัติก่อน")
        command = arguments.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("ต้องระบุคำสั่ง")
        argv = parse_command(command)
        completed = subprocess.run(argv, cwd=PROJECT_ROOT, shell=False, capture_output=True, text=True, timeout=30)
        result = {"tool": name, "command": command, "returncode": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:]}
        log_event("tool.success" if completed.returncode == 0 else "tool.failed", f"รันคำสั่งเสร็จ ({completed.returncode})", tool=name, command=command)
        return result

    raise ValueError("ไม่รู้จักเครื่องมือนี้")


def parse_tool_request(answer: str) -> dict[str, Any] | None:
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
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    for path in HISTORY_ROOT.rglob(f"*_{conversation_id}.json"):
        return path
    return None


def save_history(payload: dict[str, Any]) -> dict[str, Any]:
    conversation_id = payload.get("id") or ""
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        conversation_id = str(uuid.uuid4())
    now = datetime.now().astimezone()
    existing = find_history_file(conversation_id)
    existing_record = {}
    if existing and existing.exists():
        try:
            existing_record = json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_record = {}
    created_at = payload.get("created_at") or now.isoformat(timespec="seconds")
    path = existing or HISTORY_ROOT / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_{conversation_id}.json"
    record = {
        "id": conversation_id,
        "title": (payload.get("title") or "บทสนทนาใหม่")[:100],
        "created_at": created_at,
        "updated_at": now.isoformat(timespec="seconds"),
        "locked": bool(existing_record.get("locked", False)),
        "pinned": bool(existing_record.get("pinned", False)),
        "messages": payload.get("messages", []),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def list_models(provider: str, settings: dict[str, Any]) -> list[dict[str, str]]:
    provider = normalize_provider(provider)
    key = get_api_key(provider, settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key จึงดึงรายการโมเดลไม่ได้")
    if provider == "gemini":
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key}, timeout=30)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [{"id": item["name"].removeprefix("models/"), "name": item.get("displayName", item["name"])} for item in models if "generateContent" in item.get("supportedGenerationMethods", [])]
    if provider == "anthropic":
        try:
            response = requests.get(
                "https://api.anthropic.com/v1/models",
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
    base_url = settings.get("base_url", "https://api.openai.com/v1").rstrip("/")
    response = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    response.raise_for_status()
    models = response.json().get("data", [])
    return [{"id": item["id"], "name": item["id"]} for item in sorted(models, key=lambda item: item.get("id", ""))]


def get_api_key(provider: str, settings: dict[str, Any] | None = None) -> str:
    provider = normalize_provider(provider)
    settings = settings if settings is not None else load_settings()
    key = stored_api_keys(settings).get(provider, "")
    if not key:
        key = str(os.getenv(PROVIDER_ENV_KEYS.get(provider, "OPENAI_API_KEY"), "")).strip()
    return key


def key_is_configured(provider: str, settings: dict[str, Any] | None = None) -> bool:
    return bool(get_api_key(provider, settings))


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
    return "en" if str(value or "").strip().lower().startswith("en") else "th"


def status_message(language: str, key: str, **kwargs: Any) -> str:
    messages = STATUS_MESSAGES.get(language) or STATUS_MESSAGES["th"]
    template = messages.get(key) or STATUS_MESSAGES["th"].get(key, key)
    return template.format(**kwargs)


def provider_key_check(provider: str, settings: dict[str, Any], language: str = "th") -> dict[str, Any]:
    """Check credentials and, for Anthropic, the selected model's real usability."""
    provider = normalize_provider(provider)
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base_url = str(settings.get("base_url") or "").rstrip("/")
    model = str(settings.get("model") or "").strip()
    cache_key = f"{provider}|{base_url}|{model}|{key_fingerprint(key)}|{language}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < STATUS_CACHE_TTL:
        return {**cached[1], "cached": True}
    result: dict[str, Any]
    try:
        if provider == "gemini":
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key},
                timeout=20,
            )
        elif provider == "anthropic":
            response = requests.get(
                "https://api.anthropic.com/v1/models",
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
                "https://api.anthropic.com/v1/messages",
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


def provider_readiness(settings: dict[str, Any], language: str = "th") -> dict[str, Any]:
    provider = normalize_provider(settings.get("provider"))
    model = str(settings.get("model") or "").strip()
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base = {"provider": provider, "model": model}
    if not key:
        return {**base, "ready": False, "reason": status_message(language, "missing_key", label=label), "checked": "local"}
    if not model:
        return {**base, "ready": False, "reason": status_message(language, "missing_model", label=label), "checked": "local"}
    if not key_looks_plausible(key, provider, str(settings.get("base_url") or "")):
        return {**base, "ready": False, "reason": status_message(language, "invalid_key_shape", label=label), "checked": "local"}
    check = provider_key_check(provider, settings, language)
    return {**base, "ready": check["ready"], "reason": check["reason"], "checked": "api", "cached": check.get("cached", False)}


def clean_messages(messages: list[dict[str, str]], settings: dict[str, Any]) -> list[dict[str, str]]:
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


def call_openai(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    key = get_api_key(settings["provider"], settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key")

    base_url = settings.get("base_url", "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": settings["model"],
        "messages": messages,
        "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"],
        "top_p": settings["top_p"],
    }
    if settings.get("thinking_level") in {"low", "medium", "high"} and (settings["model"].startswith(("o", "gpt-5"))):
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
    request_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
    key = get_api_key("anthropic", settings)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Anthropic API key")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
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
    provider = settings["provider"].lower()
    if provider == "gemini":
        return call_gemini(messages, settings)
    if provider == "anthropic":
        return call_anthropic(messages, settings)
    return call_openai(messages, settings)


def get_discord_token(settings: dict[str, Any] | None = None) -> str:
    settings = settings if settings is not None else load_settings()
    configured = str(settings.get("discord_token") or "").strip()
    return configured or os.getenv("DISCORD_BOT_TOKEN", "").strip()


def discord_status() -> dict[str, Any]:
    token = get_discord_token()
    return {
        "enabled": bool(load_settings().get("discord_enabled")),
        "configured": bool(token),
        "connected": bool(DISCORD_BOT and getattr(DISCORD_BOT, "is_ready", lambda: False)()),
    }


def split_discord_message(text: str, limit: int = 2000) -> list[str]:
    text = str(text or "")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or ["(ไม่มีข้อความตอบกลับ)"]


def stop_discord_bot() -> None:
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

            answer = await ask_agent(str(message.channel.id), content, getattr(message.channel, "name", "Discord"))
            for chunk in split_discord_message(answer):
                await message.reply(chunk, mention_author=False)

    client = AIClient(intents=intents)
    command_tree = discord.app_commands.CommandTree(client)

    def is_server_admin(interaction: Any) -> bool:
        member = getattr(interaction, "user", None)
        permissions = getattr(member, "guild_permissions", None)
        return bool(getattr(permissions, "administrator", False))

    async def require_server_admin(interaction: Any) -> bool:
        if is_server_admin(interaction):
            return True
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะผู้ดูแล server เท่านั้นครับ", ephemeral=True)
        return False

    async def check_model_availability(provider: str, model: str, settings: dict[str, Any]) -> dict[str, Any]:
        probe_settings = dict(settings)
        probe_settings["provider"] = provider
        probe_settings["model"] = model
        return await asyncio.to_thread(provider_readiness, probe_settings, "th")

    async def ask_agent(context_key: str, content: str, channel_title: str = "Discord") -> str:
        """Run one agent turn while keeping a short per-channel conversation."""
        with DISCORD_CONTEXT_LOCK:
            context = DISCORD_CONTEXTS.setdefault(context_key, deque(maxlen=12))
            context.append({"role": "user", "content": content})
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
                status_code = primary_error.response.status_code if primary_error.response is not None else None
                can_fallback = (
                    bool(settings_for_chat.get("fallback_enabled"))
                    and fallback_model
                    and fallback_model != settings_for_chat.get("model")
                    and status_code in {400, 404, 429, 500, 502, 503, 504}
                )
                if not can_fallback:
                    raise
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
                DISCORD_CONTEXTS[context_key].append({"role": "assistant", "content": answer})
                conversation_id = DISCORD_CONVERSATION_IDS.setdefault(context_key, str(uuid.uuid4()))
                history_messages = list(DISCORD_CONTEXTS[context_key])
            save_history({
                "id": conversation_id,
                "title": f"Discord · {channel_title}"[:100],
                "messages": history_messages,
            })
            log_event("discord.message", "ตอบข้อความจาก Discord แล้ว", channel=context_key)
            if fallback_used:
                log_event("discord.fallback", "ใช้ fallback model สำหรับ Discord", model=fallback_used, channel=context_key)
            return answer
        except Exception as exc:
            log_event("discord.error", "ตอบข้อความจาก Discord ไม่สำเร็จ", error=str(exc))
            return "ขออภัยครับ ตอนนี้เรียก AI ไม่สำเร็จ กรุณาตรวจสอบการตั้งค่าในเว็บ"

    @command_tree.command(name="ai", description="ส่งงานหรือพูดคุยกับ AI agent")
    async def ai_command(interaction: Any, prompt: str) -> None:
        await interaction.response.defer()
        answer = await ask_agent(str(interaction.channel_id), prompt, getattr(interaction.channel, "name", "Discord"))
        for chunk in split_discord_message(answer):
            await interaction.followup.send(chunk)

    @command_tree.command(name="clear", description="ล้างบริบทการสนทนาของห้องนี้")
    async def clear_command(interaction: Any) -> None:
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(str(interaction.channel_id), None)
            DISCORD_CONVERSATION_IDS.pop(str(interaction.channel_id), None)
        await interaction.response.send_message("ล้างบริบทการสนทนาของห้องนี้แล้วครับ")

    @command_tree.command(name="new", description="เปิดแชทใหม่และสร้างประวัติใหม่บนเว็บ")
    async def new_command(interaction: Any) -> None:
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
    ])
    async def models_command(interaction: Any, provider: discord.app_commands.Choice[str], model: str | None = None) -> None:
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
        latency_ms = round(client.latency * 1000)
        await interaction.response.send_message(f"Pong! Discord latency: `{latency_ms} ms`")

    @command_tree.command(name="fallback", description="ตั้ง fallback model สำหรับห้อง Discord นี้")
    @discord.app_commands.autocomplete(model=model_autocomplete)
    async def fallback_command(interaction: Any, model: str | None = None) -> None:
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
    return jsonify({
        "scope": str(PROJECT_ROOT),
        "tools": [
            {"name": "list_files", "approval_required": False},
            {"name": "read_file", "approval_required": False},
            {"name": "write_file", "approval_required": True},
            {"name": "run_command", "approval_required": True},
            {"name": "create_skill", "approval_required": True},
            {"name": "create_schedule", "approval_required": True},
            {"name": "update_schedule", "approval_required": True},
            {"name": "execute_command", "alias_for": "run_command", "approval_required": True},
        ],
    })


@app.post("/api/tools/execute")
def tools_execute():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    arguments = body.get("arguments", {})
    approval_id = body.get("approval_id")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        log_event("tool.invalid", "ข้อมูลเครื่องมือไม่ถูกต้อง")
        return jsonify({"ok": False, "error": "ข้อมูลเครื่องมือไม่ถูกต้อง"}), 400
    canonical_name = TOOL_ALIASES.get(name, name)
    approved = False
    if canonical_name in APPROVAL_REQUIRED_TOOLS:
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


@app.get("/api/logs")
def logs_get():
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
    return jsonify({"items": load_schedules(), "timezone": datetime.now().astimezone().tzname()})


@app.post("/api/schedules")
def schedules_create():
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
    job = {"id": str(uuid.uuid4()), "name": name[:100], "schedule": schedule, "prompt": prompt[:10_000], "model": str(body.get("model", "")).strip()[:200], "discord_channel_id": discord_channel_id, "enabled": bool(body.get("enabled", True)), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "last_run_at": None, "last_status": None, "last_error": ""}
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        jobs.append(job)
        save_schedules(jobs)
    return jsonify(job), 201


@app.patch("/api/schedules/<job_id>")
def schedules_update(job_id: str):
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
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        remaining = [job for job in jobs if job.get("id") != job_id]
        if len(remaining) == len(jobs):
            return jsonify({"error": "ไม่พบงานตามเวลา"}), 404
        save_schedules(remaining)
    return jsonify({"ok": True})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/settings")
def settings_get():
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
    return jsonify({"items": list_skills()})


@app.get("/api/skills/<name>")
def skill_get(name: str):
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": "ไม่พบ Skill"}), 404
        return jsonify({"name": path.parent.name, "content": path.read_text(encoding="utf-8")[:20_000]})
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/skills")
def skills_create():
    body = request.get_json(silent=True) or {}
    try:
        result = run_local_tool("create_skill", {"name": body.get("name", ""), "content": body.get("content", "")}, approved=True)
        return jsonify(result), 201
    except (OSError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.put("/api/skills/<name>")
def skills_update(name: str):
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
    records = []
    if HISTORY_ROOT.exists():
        for path in HISTORY_ROOT.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                records.append({key: record.get(key) for key in ("id", "title", "created_at", "updated_at", "locked", "pinned")})
            except (OSError, json.JSONDecodeError):
                continue
    records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return jsonify({"items": records})


@app.get("/api/history/<conversation_id>")
def history_get(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


@app.patch("/api/history/<conversation_id>")
def history_update(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    record = json.loads(path.read_text(encoding="utf-8"))
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
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify(record)


@app.delete("/api/history/<conversation_id>")
def history_delete(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("locked"):
        return jsonify({"error": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนลบ"}), 423
    path.unlink()
    return jsonify({"ok": True})


@app.post("/api/history")
def history_save():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("messages"), list):
        return jsonify({"error": "รูปแบบประวัติไม่ถูกต้อง"}), 400
    return jsonify(save_history(body))


@app.get("/api/models")
def models_get():
    settings = load_settings()
    provider = normalize_provider(request.args.get("provider", settings.get("provider", "openai")))
    try:
        models = list_models(provider, settings)
        return jsonify({"provider": provider, "models": models, "source": "api"})
    except (requests.RequestException, RuntimeError, KeyError, TypeError) as exc:
        fallback = [{"id": name, "name": name} for name in FALLBACK_MODELS.get(provider, [])]
        return jsonify({"provider": provider, "models": fallback, "source": "fallback", "error": str(exc)}), 502


@app.put("/api/settings")
def settings_put():
    body = request.get_json(silent=True) or {}
    current = load_settings()
    allowed = {"agent_name", "agent_role", "response_language", "response_style", "use_markdown", "ask_clarifying_questions", "provider", "model", "base_url", "system_prompt", "memory_review", "skills", "temperature", "max_tokens", "top_p", "thinking_level", "stream", "fallback_enabled", "fallback_provider", "fallback_model", "discord_enabled", "discord_prefix"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    current["provider"] = normalize_provider(current.get("provider"))
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
    current["skills"] = [str(name) for name in current.get("skills", []) if str(name) in {item["name"] for item in list_skills()}]
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
                detail = str((payload.get("error") or {}).get("message") or payload.get("message") or "")[:300]
            except ValueError:
                detail = exc.response.text[:300]
        message = detail or str(exc)
        return jsonify({"ok": False, "provider": provider, "error": f"{PROVIDER_LABELS[provider]}: {message}"}), 502
    except (requests.RequestException, KeyError, IndexError, RuntimeError) as exc:
        return jsonify({"ok": False, "provider": provider, "error": str(exc)}), 502


@app.post("/api/settings/reset")
def settings_reset():
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
    STATUS_CACHE.clear()
    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "กรุณาส่งข้อความ"}), 400

    try:
        log_event("chat.start", "เริ่มประมวลผลข้อความ", message_count=len(messages))
        settings = load_settings()
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
            status_code = primary_error.response.status_code if primary_error.response is not None else None
            can_fallback = bool(settings.get("fallback_enabled")) and fallback_model and fallback_model != settings["model"] and status_code in {400, 404, 429, 500, 502, 503, 504}
            if not can_fallback:
                raise
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
            approval_request = next(
                (item for item in tool_requests if item["name"] not in {"list_files", "read_file"}),
                None,
            )
            if approval_request and command_mode not in {"auto", "fast"}:
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
        if exc.response is not None and exc.response.status_code in {429, 503}:
            provider_label = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic"}.get(provider, "ผู้ให้บริการ")
            return jsonify({"error": f"{provider_label} กำลังมีผู้ใช้หนาแน่นหรือถูกจำกัดอัตราการเรียก กรุณาลองใหม่อีกครั้งในอีกสักครู่ หรือเลือกโมเดลอื่น"}), 503
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        return jsonify({"error": f"เรียก API ไม่สำเร็จ: {detail}"}), 502
    except (KeyError, IndexError, RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
        log_event("chat.error", "ประมวลผลข้อความไม่สำเร็จ", error=str(exc))
        return jsonify({"error": str(exc)}), 500


if os.getenv("AI_WEB_ENABLE_SCHEDULER", "").strip().lower() in {"1", "true", "yes"}:
    start_scheduler()


if __name__ == "__main__":
    start_scheduler()
    start_discord_bot()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

