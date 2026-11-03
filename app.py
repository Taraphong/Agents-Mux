import os
import fcntl
import json
import logging
import re
import secrets
import shlex
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
APP_LOGS: deque[dict[str, Any]] = deque(maxlen=300)
APP_LOG_LOCK = threading.Lock()
LOGGER = logging.getLogger("ai-web")
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))
HISTORY_ROOT = Path(os.getenv("AI_WEB_HISTORY_DIR", "history"))
SCHEDULE_FILE = Path(os.getenv("AI_WEB_SCHEDULE_FILE", "scheduled-jobs.json"))
SCHEDULE_LOCK = threading.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent
TOOL_MAX_READ_BYTES = 200_000
TOOL_MAX_WRITE_BYTES = 200_000
PENDING_TOOL_REQUESTS: dict[str, dict[str, Any]] = {}
PENDING_APPROVAL_LOCK = threading.Lock()
APPROVAL_TTL_SECONDS = 15 * 60
MAX_PENDING_APPROVALS = 50
APPROVAL_REQUIRED_TOOLS = {"write_file", "run_command"}
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
""".strip()

TOOL_ALIASES = {"execute_command": "run_command"}


def log_event(event: str, message: str, **details: Any) -> None:
    """Keep a small, UI-readable diagnostic trail without storing secrets."""
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
    with APP_LOG_LOCK:
        APP_LOGS.append(record)
    LOGGER.info("%s: %s", event, message)

DEFAULT_SETTINGS = {
    "provider": os.getenv("AI_PROVIDER", "openai"),
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "base_url": "https://api.openai.com/v1",
    "system_prompt": "คุณเป็นผู้ช่วย AI ที่สุภาพ ชัดเจน และช่วยผู้ใช้ให้บรรลุเป้าหมาย",
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 1,
    "stream": False,
    "thinking_level": "off",
    "fallback_enabled": False,
    "fallback_model": os.getenv("AI_FALLBACK_MODEL", ""),
}

FALLBACK_MODELS = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini", "o3"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
}


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


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
        messages = clean_messages([{"role": "user", "content": job["prompt"]}], settings)
        started_at = time.perf_counter()
        answer, usage = call_provider(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        save_history({"title": f"⏰ {job['name']}", "messages": [
            {"role": "user", "content": job["prompt"], "schedule_id": job["id"]},
            {"role": "assistant", "content": answer, "duration_ms": duration_ms, "usage": usage, "schedule_id": job["id"]},
        ]})
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
    if not isinstance(answer, str):
        return None
    match = re.search(r"<tool_call>\s*", answer, re.IGNORECASE)
    if not match:
        return None
    decoder = json.JSONDecoder()
    try:
        request, _ = decoder.raw_decode(answer[match.end():].lstrip())
    except json.JSONDecodeError as exc:
        log_event("tool.parse_failed", "อ่าน tool_call ไม่สำเร็จ", error=str(exc))
        raise ValueError("รูปแบบ tool_call ไม่ถูกต้อง") from exc
    if not isinstance(request, dict) or not isinstance(request.get("name"), str) or not isinstance(request.get("arguments", {}), dict):
        raise ValueError("ข้อมูล tool_call ไม่ถูกต้อง")
    tool_request = {"name": request["name"], "arguments": request.get("arguments", {})}
    log_event("tool.request", f"AI ขอใช้ {tool_request['name']}", tool=tool_request["name"])
    return tool_request


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
    key = get_api_key(provider)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key จึงดึงรายการโมเดลไม่ได้")
    if provider == "gemini":
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key}, timeout=30)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [{"id": item["name"].removeprefix("models/"), "name": item.get("displayName", item["name"])} for item in models if "generateContent" in item.get("supportedGenerationMethods", [])]
    if provider == "anthropic":
        return [{"id": model, "name": model} for model in FALLBACK_MODELS["anthropic"]]
    base_url = settings.get("base_url", "https://api.openai.com/v1").rstrip("/")
    response = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    response.raise_for_status()
    models = response.json().get("data", [])
    return [{"id": item["id"], "name": item["id"]} for item in sorted(models, key=lambda item: item.get("id", ""))]


def get_api_key(provider: str) -> str:
    settings = load_settings()
    stored = settings.get("api_key", "")
    if stored:
        return stored
    return os.getenv({"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider, "OPENAI_API_KEY"), "")


def clean_messages(messages: list[dict[str, str]], settings: dict[str, Any]) -> list[dict[str, str]]:
    result = [{"role": "system", "content": settings.get("system_prompt", "")}] if settings.get("system_prompt") else []
    for item in messages:
        content = item.get("content", "")
        attachment = item.get("attachment")
        if isinstance(attachment, dict) and attachment.get("name") and attachment.get("content"):
            content = f"{content}\n\n[ไฟล์แนบ: {attachment['name']}]\n```\n{attachment['content']}\n```"
        result.append({"role": item.get("role", "user"), "content": content})
    return result


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
    key = get_api_key(settings["provider"])
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
    key = get_api_key("gemini")
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
    key = get_api_key("anthropic")
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


@app.get("/api/tools")
def tools_get():
    return jsonify({
        "scope": str(PROJECT_ROOT),
        "tools": [
            {"name": "list_files", "approval_required": False},
            {"name": "read_file", "approval_required": False},
            {"name": "write_file", "approval_required": True},
            {"name": "run_command", "approval_required": True},
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
    job = {"id": str(uuid.uuid4()), "name": name[:100], "schedule": schedule, "prompt": prompt[:10_000], "model": str(body.get("model", "")).strip()[:200], "enabled": bool(body.get("enabled", True)), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "last_run_at": None, "last_status": None, "last_error": ""}
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
        if "enabled" in body:
            job["enabled"] = bool(body["enabled"])
        save_schedules(jobs)
    return jsonify(job)


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
    key = get_api_key(settings["provider"])
    safe = {**settings, "api_key": "" if not key else "••••••••"}
    safe["has_api_key"] = bool(key)
    return jsonify(safe)


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
    provider = request.args.get("provider", settings.get("provider", "openai")).lower()
    try:
        models = list_models(provider, settings)
        return jsonify({"provider": provider, "models": models, "source": "api"})
    except (requests.RequestException, RuntimeError, KeyError, TypeError) as exc:
        return jsonify({"provider": provider, "models": [], "source": "error", "error": str(exc)}), 502


@app.put("/api/settings")
def settings_put():
    body = request.get_json(silent=True) or {}
    current = load_settings()
    allowed = {"provider", "model", "base_url", "system_prompt", "temperature", "max_tokens", "top_p", "stream", "fallback_enabled", "fallback_model"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    current["fallback_enabled"] = bool(current.get("fallback_enabled"))
    current["fallback_model"] = str(current.get("fallback_model") or "")[:200]
    if body.get("api_key") and body["api_key"] != "••••••••":
        current["api_key"] = body["api_key"]
    save_settings(current)
    return jsonify({"ok": True})


@app.post("/api/settings/test")
def settings_test():
    settings = load_settings()
    try:
        messages = clean_messages([{"role": "user", "content": "ตอบคำว่า OK สั้น ๆ"}], settings)
        answer, _usage = call_provider(messages, settings)
        return jsonify({"ok": True, "answer": answer})
    except (requests.RequestException, KeyError, IndexError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/settings/reset")
def settings_reset():
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
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
        settings["system_prompt"] = f"{settings.get('system_prompt', '')}\n\n{TOOL_INSTRUCTIONS}"
        provider = str(settings.get("provider", "openai")).lower()
        messages = clean_messages(messages, settings)
        started_at = time.perf_counter()
        fallback_used = None
        try:
            answer, usage = call_provider(messages, settings)
        except requests.HTTPError as primary_error:
            fallback_model = str(settings.get("fallback_model") or "").strip()
            status_code = primary_error.response.status_code if primary_error.response is not None else None
            can_fallback = bool(settings.get("fallback_enabled")) and fallback_model and fallback_model != settings["model"] and status_code in {400, 404, 429, 500, 502, 503, 504}
            if not can_fallback:
                raise
            settings["model"] = fallback_model
            answer, usage = call_provider(messages, settings)
            fallback_used = fallback_model
        try:
            tool_request = parse_tool_request(answer)
        except ValueError as exc:
            log_event("tool.parse_failed", "ข้าม tool_call ที่ไม่สมบูรณ์", error=str(exc))
            tool_request = None
        if tool_request:
            if tool_request["name"] in {"list_files", "read_file"}:
                result = run_local_tool(tool_request["name"], tool_request["arguments"])
                messages.extend([
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": f"ผลการใช้เครื่องมือ:\n{json.dumps(result, ensure_ascii=False)}"},
                ])
                answer, usage = call_provider(messages, settings)
            else:
                return jsonify({
                    "answer": "AI ขอใช้เครื่องมือที่ต้องได้รับอนุมัติก่อน",
                    "provider": provider,
                    "tool_request": tool_request,
                    "approval_id": request_tool_approval(tool_request["name"], tool_request["arguments"]),
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    "usage": usage,
                    "model": settings["model"],
                })
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

