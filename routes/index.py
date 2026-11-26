"""Routes for the chat page (index) and the API it uses.

The handlers were split out of app.py so the page-specific code stays in one
place; shared helpers, settings, history and the Flask app remain in app.py,
which registers this blueprint.
"""

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

import memory_engine
from core.auth import no_store
from core.config import (
    APPROVAL_PLACEHOLDER,
    APPROVAL_TTL_SECONDS,
    is_approval_placeholder,
    ASSET_CACHE_CONTROL,
    HISTORY_ROOT,
    LOG_FILE,
    PAGE_ASSETS,
    PROJECT_ROOT,
    SERVER_CONTROL_LOG,
    SERVER_SCRIPT,
    SETTINGS_FILE,
    TEMPLATES_ROOT,
    TOOL_ALIASES,
    TOOL_CALL_REPAIR_INSTRUCTION,
    TOOL_MAX_WRITE_BYTES,
)
from core.env import env_int
from core.history import (
    HISTORY_LOCK,
    HistoryConflict,
    HistoryLocked,
    _write_history_record,
    append_history_messages,
    find_history_file,
    read_history_file,
    save_history,
)
from core.http_cache import compress_response
from core.log import APP_LOGS, APP_LOG_LOCK, log_event
from core.messages import normalize_language, request_language, status_message
from core.model_cache import MODEL_LIST_ERROR_LOGGED, forget_model_names
from core.prompts import build_system_prompt
from core.providers import (
    CUT_FINISH_REASONS,
    GEMINI_DECISION_MODEL,
    GEMINI_DEFAULT_AGENT,
    GEMINI_LIVE_FALLBACK_MODEL,
    PROVIDER_NETWORK_ERRORS,
    ProviderEmptyResponse,
    STATUS_CACHE,
    call_provider,
    clean_messages,
    gemini_capabilities,
    gemini_post,
    get_api_key,
    key_is_configured,
    provider_readiness,
    safe_stored_api_key,
)
from core.ratelimit import rate_limit_response
from core.redaction import mask_url_credentials, redact_secrets
from core.runtime import APP_STARTED_AT, SERVER_JOB, SERVER_JOB_LOCK
from core.schedule_store import SCHEDULE_LOCK, load_schedules, save_schedules, validate_cron
from core.settings import (
    PROVIDERS,
    PROVIDER_LABELS,
    SETTINGS_LOCK,
    get_discord_token,
    load_settings,
    normalize_provider,
    stored_api_keys,
    stored_custom_api_keys,
)
from core.skills import list_skills, read_skill, save_skill, skill_path
from core.tls import (
    TLS_ENV_LOCK,
    apply_tls_environment,
    configured_certificate_pair,
    server_tls_state,
    update_env_file,
)
from core.tools import (
    approval_required_tools,
    consume_tool_approval,
    has_tool_marker,
    machine_access_enabled,
    parse_tool_requests,
    request_tool_approval,
    run_local_tool,
    strip_tool_markers,
)
from core.update_job import (
    UPDATE_JOB,
    UPDATE_JOB_LOCK,
    UPDATE_LOG_FILE,
    UPDATE_MODES,
    UPDATE_SCRIPT,
    save_update_status,
    update_build_info,
    update_job_snapshot,
    update_log_tail,
    update_script_ready,
    watch_update_job,
)
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import requests
from routes.shared import (
    apply_settings_update,
    error_response,
    gemini_agent_answer,
    gemini_error_detail,
    models_response,
)
from services.discord_bot import discord_status
from services.scheduler import SCHEDULE_RUNNING, SCHEDULE_RUNNING_LOCK, execute_schedule
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any
import uuid

index_bp = Blueprint("index", __name__)


@index_bp.get("/api/tools")
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
            {"name": "list_schedules", "approval_required": "list_schedules" in required},
            {"name": "update_schedule", "approval_required": "update_schedule" in required},
            {"name": "execute_command", "alias_for": "run_command", "approval_required": "run_command" in required},
        ],
    })


@index_bp.post("/api/tools/execute")
def tools_execute():
    """Execute a local tool call after validating its approval token."""
    limited = rate_limit_response("tools")
    if limited:
        return limited
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    arguments = body.get("arguments", {})
    approval_id = body.get("approval_id")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        log_event("tool.invalid", "Invalid tool payload")
        return jsonify({"ok": False, "error": status_message(request_language(), "tool_invalid_payload")}), 400
    canonical_name = TOOL_ALIASES.get(name, name)
    approved = False
    if canonical_name in approval_required_tools():
        approved = consume_tool_approval(approval_id, name, arguments)
        if not approved:
            log_event("tool.denied", f"Denied {name} because there is no valid approval", tool=name)
            return jsonify({"ok": False, "error": status_message(request_language(), "tool_approval_invalid")}), 403
    try:
        result = run_local_tool(name, arguments, approved=approved)
        return jsonify({"ok": True, "result": result})
    except (FileNotFoundError, PermissionError, ValueError, OSError, subprocess.SubprocessError) as exc:
        log_event("tool.error", f"{name} failed", tool=name, error=str(exc))
        # ``approved`` means the single-use token was already consumed above, so
        # the client must ask for a new approval instead of offering a retry
        # with a token this endpoint will reject. The generic message alone
        # hides the reason (a wrong job id, a rejected command), so the redacted
        # exception text is returned as ``detail`` for the card to show.
        detail = redact_secrets(str(exc)).strip()[:400]
        return jsonify({
            "ok": False,
            "error": status_message(request_language(), "tool_failed"),
            "detail": detail,
            "approval_consumed": approved,
        }), 400


@index_bp.get("/api/logs")
def logs_get():
    """Return the in-memory diagnostic log entries."""
    with APP_LOG_LOCK:
        items = list(APP_LOGS)
    return jsonify({"items": items})


@index_bp.delete("/api/logs")
def logs_delete():
    """Delete the persisted log file and clear the in-memory view."""
    try:
        with APP_LOG_LOCK:
            deleted = len(APP_LOGS)
            APP_LOGS.clear()
            LOG_FILE.unlink(missing_ok=True)
    except OSError:
        return jsonify({"ok": False, "error": status_message(request_language(), "log_clear_failed")}), 500
    return jsonify({"ok": True, "deleted": deleted})


@index_bp.get("/api/schedules")
def schedules_get():
    """List scheduled jobs and the server timezone."""
    return jsonify({"items": load_schedules(), "timezone": datetime.now().astimezone().tzname()})


@index_bp.post("/api/schedules")
def schedules_create():
    """Create a scheduled job from the settings UI payload."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    prompt = str(body.get("prompt", "")).strip()
    if not name or not prompt:
        return jsonify({"error": status_message(request_language(), "schedule_name_required")}), 400
    try:
        schedule = validate_cron(body.get("schedule", ""))
    except (TypeError, ValueError):
        return jsonify({"error": status_message(request_language(), "schedule_invalid")}), 400
    discord_channel_id = str(body.get("discord_channel_id", "")).strip()[:30]
    if discord_channel_id and not discord_channel_id.isdigit():
        return jsonify({"error": status_message(request_language(), "schedule_channel_invalid")}), 400
    job = {"id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()), "name": name[:100], "schedule": schedule, "prompt": prompt[:10_000], "model": str(body.get("model", "")).strip()[:200], "discord_channel_id": discord_channel_id, "enabled": bool(body.get("enabled", True)), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "last_run_at": None, "last_status": None, "last_error": ""}
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        jobs.append(job)
        save_schedules(jobs)
    return jsonify(job), 201


@index_bp.patch("/api/schedules/<job_id>")
def schedules_update(job_id: str):
    """Update fields of one scheduled job from the settings UI."""
    body = request.get_json(silent=True) or {}
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        job = next((item for item in jobs if item.get("id") == job_id), None)
        if not job:
            return jsonify({"error": status_message(request_language(), "schedule_not_found")}), 404
        if "schedule" in body:
            try:
                job["schedule"] = validate_cron(body["schedule"])
            except (TypeError, ValueError):
                return jsonify({"error": status_message(request_language(), "schedule_invalid")}), 400
        if "name" in body:
            job["name"] = str(body["name"]).strip()[:100] or job["name"]
        if "prompt" in body:
            job["prompt"] = str(body["prompt"]).strip()[:10_000]
        if "model" in body:
            job["model"] = str(body["model"]).strip()[:200]
        if "discord_channel_id" in body:
            discord_channel_id = str(body["discord_channel_id"]).strip()[:30]
            if discord_channel_id and not discord_channel_id.isdigit():
                return jsonify({"error": status_message(request_language(), "schedule_channel_invalid")}), 400
            job["discord_channel_id"] = discord_channel_id
        if "enabled" in body:
            job["enabled"] = bool(body["enabled"])
        save_schedules(jobs)
    return jsonify(job)


@index_bp.post("/api/schedules/<job_id>/run")
def schedules_run(job_id: str):
    """Start a scheduled job immediately in a background thread."""
    jobs = load_schedules()
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if not job:
        return jsonify({"error": status_message(request_language(), "schedule_not_found")}), 404
    with SCHEDULE_RUNNING_LOCK:
        if job_id in SCHEDULE_RUNNING:
            return jsonify({"error": status_message(request_language(), "schedule_running")}), 409
        SCHEDULE_RUNNING.add(job_id)
    try:
        threading.Thread(target=execute_schedule, args=(job,), daemon=True).start()
    except Exception:
        with SCHEDULE_RUNNING_LOCK:
            SCHEDULE_RUNNING.discard(job_id)
        raise
    return jsonify({"ok": True, "job_id": job_id}), 202


@index_bp.delete("/api/schedules/<job_id>")
def schedules_delete(job_id: str):
    """Delete one scheduled job by id."""
    with SCHEDULE_LOCK:
        jobs = load_schedules()
        remaining = [job for job in jobs if job.get("id") != job_id]
        if len(remaining) == len(jobs):
            return jsonify({"error": status_message(request_language(), "schedule_not_found")}), 404
        save_schedules(remaining)
    return jsonify({"ok": True})


@index_bp.get("/api/memory/status")
def memory_status_get():
    """Report the memory engine state, counts and capabilities."""
    status = memory_engine.status(load_settings())
    # The report carries the memory engine's Base URL, which can hold the same
    # credentials as the chat URL; mask it the way /api/settings does.
    if isinstance(status, dict):
        status["base_url"] = mask_url_credentials(status.get("base_url"))
    return jsonify(status)


@index_bp.get("/api/memory/entries")
def memory_entries_get():
    """List promoted memories and the newest dream log text."""
    return jsonify({"items": memory_engine.entries(), "dreams": memory_engine.recent_dreams()})


@index_bp.post("/api/memory/run")
def memory_run_post():
    """Run the consolidation phases now, optionally as a dry run."""
    limited = rate_limit_response("chat")
    if limited:
        return limited
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    language = request_language()
    dry_run = bool(body.get("dry_run"))
    try:
        result = memory_engine.run(
            trigger="manual",
            dry_run=dry_run,
            settings=load_settings(),
            language=language,
        )
        safe_result = dict(result) if isinstance(result, dict) else result
        if isinstance(safe_result, dict) and isinstance(safe_result.get("stats"), dict):
            safe_stats = dict(safe_result["stats"])
            # The engine already stores a category. Only a known category may
            # leave the server, so raw exception text can never reach the page.
            kind = str(safe_stats.get("llm_error") or "")
            safe_stats["llm_error"] = kind if kind in memory_engine.LLM_ERROR_KINDS else ""
            safe_result["stats"] = safe_stats
        return jsonify(safe_result)
    except RuntimeError as exc:
        if str(exc) == "memory_busy":
            return jsonify({"error": status_message(language, "memory_busy")}), 409
        # The reason goes to the log only: an exception message can carry
        # paths, request ids and key fragments that must not reach the page.
        log_event("memory.error", "Memory run failed", error=redact_secrets(str(exc))[:300])
        return jsonify({"error": status_message(language, "memory_run_failed")}), 500
    except Exception as exc:  # noqa: BLE001 - details go to the log, not the page
        log_event("memory.error", "Memory run failed", error=redact_secrets(str(exc))[:300])
        return jsonify({"error": status_message(language, "memory_run_failed")}), 500


@index_bp.delete("/api/memory/entries/<memory_id>")
def memory_entry_delete(memory_id: str):
    """Forget one promoted memory in both tiers."""
    language = request_language()
    try:
        removed = memory_engine.forget(memory_id)
    except RuntimeError as exc:
        if str(exc) == "memory_busy":
            return jsonify({"error": status_message(language, "memory_busy")}), 409
        return jsonify({"error": status_message(language, "memory_forget_failed")}), 500
    except OSError:
        return jsonify({"error": status_message(language, "memory_forget_failed")}), 500
    if not removed:
        return jsonify({"error": status_message(language, "memory_not_found")}), 404
    return jsonify({"ok": True})


@index_bp.put("/api/memory/entries/<memory_id>/pin")
def memory_entry_pin(memory_id: str):
    """Pin or unpin one memory so the entry cap never evicts it."""
    language = request_language()
    body = request.get_json(silent=True) or {}
    # A valid JSON array or number is truthy but has no .get(): treat it as an
    # invalid payload instead of raising AttributeError and returning 500.
    if not isinstance(body, dict):
        body = {}
    pinned = body.get("pinned")
    if not isinstance(pinned, bool):
        return jsonify({"error": status_message(language, "memory_pin_invalid")}), 400
    try:
        updated = memory_engine.pin(memory_id, pinned)
    except RuntimeError as exc:
        if str(exc) == "memory_busy":
            return jsonify({"error": status_message(language, "memory_busy")}), 409
        return jsonify({"error": status_message(language, "memory_pin_failed")}), 500
    except OSError:
        return jsonify({"error": status_message(language, "memory_pin_failed")}), 500
    if not updated:
        return jsonify({"error": status_message(language, "memory_not_found")}), 404
    return jsonify({"ok": True, "pinned": pinned})


@index_bp.post("/api/memory/reindex")
def memory_reindex_post():
    """Reset the SQLite index; the next consolidation run rebuilds it."""
    language = request_language()
    try:
        return jsonify(memory_engine.reindex())
    except RuntimeError:
        return jsonify({"error": status_message(language, "memory_busy")}), 409
    except Exception as exc:  # noqa: BLE001 - detail goes to the log, not the page
        return error_response(
            language,
            "memory_reindex_failed",
            exc=exc,
            event="memory.error",
            message="Memory index rebuild failed",
        )


@index_bp.get("/templates/<page>/<filename>")
def page_asset(page: str, filename: str):
    """Serve the CSS/JS stored beside a page template.

    Only known page folders and the .css/.js extensions are exposed, so the
    Jinja templates themselves can never be downloaded.
    """
    if page not in PAGE_ASSETS or Path(filename).suffix.lower() not in {".css", ".js"}:
        abort(404)
    # Conditional evaluation is deferred to compress_response: the file's identity
    # validators must not decide the response before the encoding is chosen.
    response = send_from_directory(TEMPLATES_ROOT / page, filename, conditional=False)
    # send_from_directory streams the file; the body must be readable here so it
    # can be gzipped before it travels over the slow link.
    response.direct_passthrough = False
    response.headers["Cache-Control"] = ASSET_CACHE_CONTROL
    cache_key = None
    try:
        stat = (TEMPLATES_ROOT / page / filename).stat()
        cache_key = (str(TEMPLATES_ROOT / page / filename), stat.st_mtime_ns, stat.st_size)
    except OSError:
        cache_key = None
    return compress_response(response, cache_key, accept_ranges=True)


@index_bp.get("/")
def index():
    """Render the single-page web application."""
    return render_template("index/index.html")


@index_bp.get("/api/settings")
def settings_get():
    """Return settings with secrets masked for the settings UI."""
    settings = load_settings()
    provider = normalize_provider(settings.get("provider"))
    key = get_api_key(provider, settings)
    safe = {key_: value for key_, value in settings.items() if key_ not in {"api_keys", "api_key", "discord_token", "custom_api_keys"}}
    # A Base URL can carry credentials (https://user:token@host/v1); the page
    # only needs the endpoint, so the userinfo stays on the server.
    safe["base_url"] = mask_url_credentials(safe.get("base_url"))
    memory = safe.get("memory")
    if isinstance(memory, dict):
        # The memory engine can run on its own endpoint, which can carry the
        # same kind of credentials, so it is masked the same way.
        safe["memory"] = {**memory, "base_url": mask_url_credentials(memory.get("base_url"))}
    safe["provider"] = provider
    safe["api_key"] = "" if not key else "••••••••"
    safe["has_api_key"] = bool(key)
    safe["key_providers"] = [name for name in PROVIDERS if key_is_configured(name, settings)]
    # Names are safe to show; the values must never leave the server.
    safe["custom_api_keys"] = [{"name": name} for name in stored_custom_api_keys(settings)]
    discord_token = get_discord_token(settings)
    safe["discord_token"] = "••••••••" if discord_token else ""
    safe["has_discord_token"] = bool(discord_token)
    safe["discord_status"] = discord_status()
    safe["available_skills"] = [
        {"name": item["name"], "description": item["description"]} for item in list_skills()
    ]
    return jsonify(safe)


@index_bp.get("/api/skills")
def skills_get():
    """List the available skills: metadata and resource files, not bodies."""
    return jsonify({"items": list_skills()})


@index_bp.get("/api/skills/<name>")
def skill_get(name: str):
    """Return one skill's SKILL.md content and its resource files by name."""
    try:
        return jsonify(read_skill(name))
    except FileNotFoundError:
        return jsonify({"error": status_message(request_language(), "skill_not_found")}), 404
    except (OSError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_read_failed")}), 400


@index_bp.post("/api/skills")
def skills_create():
    """Create a new skill from the settings UI payload."""
    body = request.get_json(silent=True) or {}
    try:
        result = run_local_tool(
            "create_skill",
            {
                "name": body.get("name", ""),
                "description": body.get("description", ""),
                "content": body.get("content", ""),
                "files": body.get("files"),
            },
            approved=True,
        )
        return jsonify(result), 201
    except (OSError, PermissionError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_create_failed")}), 400


@index_bp.put("/api/skills/<name>")
def skills_update(name: str):
    """Replace one skill's SKILL.md, keeping its frontmatter valid."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
        return jsonify({"error": status_message(request_language(), "skill_content_invalid")}), 400
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": status_message(request_language(), "skill_not_found")}), 404
        # A null description stays None on purpose: save_skill() then keeps the
        # description already in the document instead of writing "None".
        saved = save_skill(name, description=body.get("description", ""), content=content)
        return jsonify({"ok": True, "name": saved["name"], "description": saved["description"]})
    except (OSError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_save_failed")}), 400


@index_bp.delete("/api/skills/<name>")
def skills_delete(name: str):
    """Delete a skill folder by name."""
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": status_message(request_language(), "skill_not_found")}), 404
        shutil.rmtree(path.parent)
        return jsonify({"ok": True, "name": path.parent.name})
    except (OSError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_delete_failed")}), 400


@index_bp.get("/api/status")
def status_get():
    """Report whether the selected provider/model is actually usable."""
    settings = load_settings()
    return jsonify(provider_readiness(settings, normalize_language(request.args.get("lang"))))


@index_bp.get("/api/history")
def history_list():
    """Return history summaries sorted by most recently updated."""
    records = []
    # The same conversation can exist more than once when an older build wrote a
    # relative path under history/history. Keep only the newest copy per id so
    # the sidebar never lists one conversation twice.
    positions = {}
    if HISTORY_ROOT.exists():
        for path in HISTORY_ROOT.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(record, dict):
                # A stray list/scalar JSON file must not break the whole list.
                continue
            item = {key: record.get(key) for key in ("id", "title", "created_at", "updated_at", "locked", "pinned")}
            identity = item.get("id")
            if isinstance(identity, str) and identity:
                position = positions.get(identity)
                if position is not None:
                    if str(item.get("updated_at") or "") >= str(records[position].get("updated_at") or ""):
                        records[position] = item
                    continue
                positions[identity] = len(records)
            records.append(item)
    # A record whose timestamp is missing or null must not break the whole list.
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return jsonify({"items": records})


@index_bp.get("/api/history/<conversation_id>")
def history_get(conversation_id: str):
    """Return one full conversation record by id."""
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": status_message(request_language(), "history_not_found")}), 404
    record = read_history_file(path)
    if record is None:
        return jsonify({"error": status_message(request_language(), "history_corrupt")}), 409
    payload = dict(record)
    # A pending approval restored from disk needs the server clock to be
    # measured against; the browser clock cannot be trusted for that.
    payload["server_time"] = int(time.time())
    return jsonify(payload)


@index_bp.post("/api/history/<conversation_id>/approvals/clear")
def history_clear_approval(conversation_id: str):
    """Clear a used or rejected approval token from one stored message.

    The chat page keeps the token in its message metadata so a reload can offer
    the button again. Once the token is consumed the stored copy has to go as
    well, otherwise reopening the conversation offers a dead approval.
    """
    body = request.get_json(silent=True) or {}
    message_id = body.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return jsonify({"ok": False, "error": status_message(request_language(), "history_message_id_required")}), 400
    # find_history_file already rejects anything that is not a conversation id.
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if not path or not path.exists():
            return jsonify({"ok": False, "error": status_message(request_language(), "history_not_found")}), 404
        record = read_history_file(path)
        if record is None:
            return jsonify({"ok": False, "error": status_message(request_language(), "history_corrupt")}), 409
        stored = record.get("messages") if isinstance(record.get("messages"), list) else []
        cleared = False
        for message in stored:
            if not isinstance(message, dict) or message.get("message_id") != message_id:
                continue
            for key in ("tool_request", "approval_id", "approval_expires_at", "approval_deadline"):
                if message.pop(key, None) is not None:
                    cleared = True
        if cleared:
            # Only a single-use token is removed, so a locked conversation can
            # still be cleaned up without changing its content.
            _write_history_record(path, record)
        return jsonify({"ok": True, "cleared": cleared})


@index_bp.patch("/api/history/<conversation_id>")
def history_update(conversation_id: str):
    """Rename, lock, or pin one conversation record."""
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if not path or not path.exists():
            return jsonify({"error": status_message(request_language(), "history_not_found")}), 404
        record = read_history_file(path)
        if record is None:
            return jsonify({"error": status_message(request_language(), "history_corrupt")}), 409
        body = request.get_json(silent=True) or {}
        if record.get("locked") and {"title", "messages"} & set(body):
            return jsonify({"error": status_message(request_language(), "history_locked_edit")}), 423
        if "title" in body:
            title = str(body["title"]).strip()
            if title:
                record["title"] = title[:100]
        if "locked" in body:
            record["locked"] = bool(body["locked"])
        if "pinned" in body:
            record["pinned"] = bool(body["pinned"])
        if "messages" in body:
            new_messages = body.get("messages")
            if not isinstance(new_messages, list):
                return jsonify({"error": status_message(request_language(), "history_invalid")}), 400
            if len(new_messages) > 5000:
                return jsonify({"error": status_message(request_language(), "history_too_many_messages")}), 400
            safe_roles = {"user", "assistant"}
            stored_messages = record.get("messages") if isinstance(record.get("messages"), list) else []
            stored_by_id = {
                str(message.get("message_id")): message
                for message in stored_messages
                if isinstance(message, dict) and message.get("message_id")
            }
            sanitized_messages = []
            for item in new_messages:
                if not isinstance(item, dict):
                    return jsonify({"error": status_message(request_language(), "history_invalid_message")}), 400
                role = str(item.get("role", "")).strip().lower()
                content = item.get("content")
                if role not in safe_roles:
                    return jsonify({"error": status_message(request_language(), "history_unsupported_role")}), 400
                if not isinstance(content, str):
                    return jsonify({"error": status_message(request_language(), "history_invalid_message")}), 400
                message_id = item.get("message_id")
                if isinstance(message_id, str) and message_id in stored_by_id:
                    # Keep the metadata already stored for this message (its
                    # attachments, model, pending approval, ...) and update the
                    # text that was edited instead of discarding it.
                    entry = dict(stored_by_id[message_id])
                    entry["role"] = role
                    entry["content"] = content[:20000]
                else:
                    entry = {"role": role, "content": content[:20000]}
                    if isinstance(message_id, str) and message_id.strip():
                        entry["message_id"] = message_id.strip()[:100]
                sanitized_messages.append(entry)
            # Editing a prompt replaces the stored list with the sanitized one.
            record["messages"] = sanitized_messages
            record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_history_record(path, record)
        return jsonify(record)


@index_bp.delete("/api/history/<conversation_id>")
def history_delete(conversation_id: str):
    """Delete one conversation record unless it is locked."""
    with HISTORY_LOCK:
        path = find_history_file(conversation_id)
        if not path or not path.exists():
            return jsonify({"error": status_message(request_language(), "history_not_found")}), 404
        record = read_history_file(path)
        if record is None:
            return jsonify({"error": status_message(request_language(), "history_corrupt")}), 409
        if record.get("locked"):
            return jsonify({"error": status_message(request_language(), "history_locked_delete")}), 423
        path.unlink()
        return jsonify({"ok": True})


@index_bp.post("/api/history/<conversation_id>/messages")
def history_append(conversation_id: str):
    """Append messages to a conversation that still exists."""
    body = request.get_json(silent=True) or {}
    messages = body.get("messages")
    generation = body.get("generation")
    if not isinstance(messages, list) or not messages:
        return jsonify({"error": status_message(request_language(), "history_invalid")}), 400
    try:
        record = append_history_messages(conversation_id, messages, generation)
    except HistoryConflict:
        return jsonify({"error": status_message(request_language(), "history_conflict")}), 409
    except HistoryLocked:
        return jsonify({"error": status_message(request_language(), "history_locked_edit")}), 423
    if record is None:
        return jsonify({"error": status_message(request_language(), "history_not_found")}), 404
    return jsonify(record)


@index_bp.post("/api/history")
def history_save():
    """Store a conversation payload sent by the web UI."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("messages"), list):
        return jsonify({"error": status_message(request_language(), "history_invalid")}), 400
    try:
        return jsonify(save_history(body))
    except HistoryLocked:
        return jsonify({"error": status_message(request_language(), "history_locked_save")}), 423


TITLE_INPUT_MAX_LENGTH = 4000
TITLE_MAX_LENGTH = 100


def clean_generated_title(answer: str) -> str:
    """Turn a model reply into one plain title line without decoration."""
    line = next((row.strip() for row in str(answer or "").splitlines() if row.strip()), "")
    title = re.sub(r"\s+", " ", line).strip().strip("`*_\"'“”‘’ ")
    # Unwrap quotes first, otherwise "Title: ..." keeps its prefix.
    title = re.sub(r"^(?:title|หัวข้อ|หัวเรื่อง)\s*[:：-]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\s.,;:!?]+$", "", title)
    # Decoration can sit outside the final punctuation ("**Title**."), so the
    # trim runs after the punctuation is gone as well.
    title = title.strip("`*_\"'“”‘’ ")
    title = re.sub(r"[\s.,;:!?]+$", "", title)
    return title[:TITLE_MAX_LENGTH]


def summarize_conversation_title(question: str, language: str, settings: dict[str, Any]) -> str:
    """Ask the configured model for a short title that names the question."""
    if language == "th":
        instruction = (
            "คุณเป็นผู้ตั้งชื่อบทสนทนา สรุปข้อความแรกของผู้ใช้เป็นหัวข้อสั้น ๆ ที่บอกเนื้อหาจริง "
            "ใช้ภาษาไทย ความยาวไม่เกิน 60 ตัวอักษร ห้ามใส่เครื่องหมายคำพูด ห้ามมีเครื่องหมายวรรคตอนท้าย "
            "ห้ามขึ้นต้นด้วย 'หัวข้อ:' และห้ามตอบคำถาม ตอบเฉพาะหัวข้อเท่านั้น"
        )
    else:
        instruction = (
            "You name chat conversations. Summarise the user's first message into one short, specific "
            "title that names its actual subject. Use English. At most 10 words, no quotes, no ending "
            "punctuation, no prefix such as 'Title:', and never answer the message. Reply with the title only."
        )
    title_settings = dict(settings)
    # A title is a single cheap line: no thinking budget, a small output cap.
    title_settings["thinking_level"] = "off"
    title_settings["max_tokens"] = min(max(int(title_settings.get("max_tokens") or 0), 64), 200)
    title_settings["temperature"] = 0.2
    answer, _usage = call_provider(
        [
            {"role": "system", "content": instruction},
            {"role": "user", "content": question},
        ],
        title_settings,
    )
    return clean_generated_title(answer)


TITLE_FALLBACK_STATUSES = {400, 404, 429, 500, 502, 503, 504}


def title_fallback_settings(settings: dict[str, Any]) -> dict[str, Any] | None:
    """Return the configured fallback target, mirroring the chat retry rules."""
    if not settings.get("fallback_enabled"):
        return None
    model = str(settings.get("fallback_model") or "").strip()
    if not model:
        return None
    provider = normalize_provider(settings.get("fallback_provider"))
    primary_provider = normalize_provider(settings.get("provider"))
    if provider == primary_provider and model == str(settings.get("model") or "").strip():
        return None
    fallback = dict(settings)
    # A Base URL belongs to the primary provider, so it cannot follow the retry.
    if provider != primary_provider:
        fallback["base_url"] = ""
    fallback["provider"] = provider
    fallback["model"] = model
    return fallback


def request_conversation_title(question: str, language: str, settings: dict[str, Any]) -> str:
    """Summarise the question, retrying on the fallback model like /api/chat.

    A busy primary model (503/429) would otherwise leave every new chat with the
    raw first message as its title, even though a working fallback is configured.
    """
    try:
        return summarize_conversation_title(question, language, settings)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        fallback = title_fallback_settings(settings) if status_code in TITLE_FALLBACK_STATUSES else None
        if fallback is None:
            raise
        log_event(
            "title.retry",
            "The primary model could not name the conversation, retrying on the fallback",
            status=status_code,
        )
        return summarize_conversation_title(question, language, fallback)


@index_bp.post("/api/history/title")
def history_title():
    """Summarise the first question into a title for a new conversation."""
    limited = rate_limit_response("title")
    if limited:
        return limited
    body = request.get_json(silent=True) or {}
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": status_message(request_language(), "chat_message_required")}), 400
    settings = load_settings()
    requested_model = body.get("model")
    if isinstance(requested_model, str) and requested_model.strip():
        settings["model"] = requested_model.strip()[:200]
    language = request_language()
    try:
        title = redact_secrets(request_conversation_title(
            question.strip()[:TITLE_INPUT_MAX_LENGTH], language, settings
        ))
    except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
        log_event("title.failed", "Could not summarise a conversation title", error=str(exc)[:200])
        return jsonify({"error": status_message(language, "title_generation_failed")}), 502
    if not title:
        log_event("title.empty", "The title summary came back empty")
        return jsonify({"error": status_message(language, "title_generation_failed")}), 502
    return jsonify({"title": title})


@index_bp.get("/api/models")
def models_get():
    """Return provider models, falling back to a static list on failure."""
    settings = load_settings()
    provider = normalize_provider(request.args.get("provider", settings.get("provider", "openai")))
    return models_response(provider, settings)


@index_bp.post("/api/models")
def models_post():
    """Return provider models for a key submitted before it is saved."""
    settings = load_settings()
    body = request.get_json(silent=True) or {}
    provider = normalize_provider(body.get("provider") or settings.get("provider", "openai"))
    base_url = body.get("base_url")
    # An explicit empty string means "use the provider default"; only an
    # omitted base_url leaves the configured value untouched. A masked value is
    # the one the settings page was shown, so it must not replace the real URL.
    if isinstance(base_url, str) and "••" not in base_url:
        settings["base_url"] = base_url.strip()
    submitted_key = body.get("api_key")
    if isinstance(submitted_key, str) and submitted_key.strip() and submitted_key != "••••••••":
        keys = stored_api_keys(settings)
        keys[provider] = submitted_key.strip()
        settings["api_keys"] = keys
    return models_response(provider, settings)


@index_bp.put("/api/settings")
def settings_put():
    """Persist editable settings, including the configured fallback provider."""
    with SETTINGS_LOCK:
        return apply_settings_update()


@index_bp.post("/api/settings/test")
def settings_test():
    """Test submitted settings against the provider without saving them."""
    limited = rate_limit_response("test")
    if limited:
        return limited
    settings = load_settings()
    body = request.get_json(silent=True) or {}
    # Test submitted settings without persisting credentials first. This lets
    # the UI validate a new key before it becomes part of the saved settings.
    stored_base_url = settings.get("base_url")
    for key in {"provider", "model", "base_url", "system_prompt", "memory_review", "temperature", "max_tokens", "top_p", "thinking_level"}:
        if key in body:
            settings[key] = body[key]
    if "••" in str(settings.get("base_url") or ""):
        # The page sends back the masked Base URL it was shown; test the real one.
        settings["base_url"] = stored_base_url
    submitted_key = body.get("api_key")
    if isinstance(submitted_key, str) and submitted_key.strip() and submitted_key != "••••••••":
        keys = stored_api_keys(settings)
        keys[normalize_provider(settings.get("provider"))] = submitted_key.strip()
        settings["api_keys"] = keys
    provider = normalize_provider(settings.get("provider"))
    STATUS_CACHE.clear()
    try:
        messages = clean_messages([{"role": "user", "content": "Reply with a short OK"}], settings)
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
        message = redact_secrets(detail, api_key=api_key) if detail else status_message(request_language(), "test_connection_hint")
        return jsonify({"ok": False, "provider": provider, "error": f"{PROVIDER_LABELS[provider]}: {message}"}), 502
    except (requests.RequestException, KeyError, IndexError, RuntimeError):
        return jsonify({"ok": False, "provider": provider, "error": status_message(request_language(), "test_connection_failed", label=PROVIDER_LABELS[provider])}), 502


@index_bp.get("/api/gemini/capabilities")
def gemini_capabilities_get():
    """Report which Gemini feature groups the stored key can use."""
    settings = load_settings()
    language = normalize_language(request.args.get("lang"))
    force = request.args.get("refresh") == "1"
    return jsonify(gemini_capabilities(settings, language, force=force))


@index_bp.post("/api/gemini/decisions")
def gemini_decisions_create():
    """Evaluate structured decision questions with the Gemini Decisions API."""
    body = request.get_json(silent=True)
    language = normalize_language(body.get("lang") if isinstance(body, dict) else None)
    if not isinstance(body, dict):
        return jsonify({"error": status_message(language, "invalid_body")}), 400
    settings = load_settings()
    key = get_api_key("gemini", settings)
    if not key:
        return jsonify({"error": status_message(language, "gemini_key_missing")}), 400
    input_text = body.get("input")
    if isinstance(input_text, list):
        input_text = "\n".join(
            str(part.get("text") or "") for part in input_text if isinstance(part, dict)
        )
    if not isinstance(input_text, str) or not input_text.strip() or len(input_text) > 32_000:
        return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
    questions = body.get("questions")
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 1000:
        return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
    cleaned: dict[str, Any] = {}
    for question_id, question in questions.items():
        if not isinstance(question_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", question_id):
            return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
        if (
            not isinstance(question, dict)
            or not isinstance(question.get("type"), str)
            or question["type"] not in {"noul", "choice", "score"}
        ):
            return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
        criteria = question.get("criteria")
        if question["type"] == "choice":
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255:
                return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
        elif question["type"] == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 255:
                return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
        item: dict[str, Any] = {"type": question["type"], "instructions": instructions[:8000]}
        if question["type"] == "choice":
            item["criteria"] = {
                str(name)[:128]: str(value)[:2000]
                for name, value in list(criteria.items())[:255]
            }
        elif question["type"] == "score":
            item["criteria"] = [str(value)[:2000] for value in criteria[:255]]
        elif criteria is not None:
            # A yes/no question takes an optional rubric describing what true
            # and false mean; dropping it silently changes the answer.
            wanted = ("true_description", "false_description")
            if not isinstance(criteria, dict) or any(
                criteria.get(key) is not None and not isinstance(criteria.get(key), str)
                for key in wanted
            ):
                return jsonify({"error": status_message(language, "gemini_decisions_invalid")}), 400
            forwarded = {
                key: criteria[key][:2000] for key in wanted
                if isinstance(criteria.get(key), str) and criteria[key].strip()
            }
            if forwarded:
                item["criteria"] = forwarded
        cleaned[question_id] = item
    model = str(body.get("model") or settings.get("gemini_decision_model") or GEMINI_DECISION_MODEL)[:100]
    payload = {"model": model, "input": input_text, "questions": cleaned}
    try:
        response = gemini_post("/decisions", settings, key, payload, timeout=90)
        data = response.json()
    except requests.HTTPError as exc:
        detail = gemini_error_detail(exc.response, key)
        return jsonify({"error": status_message(language, "gemini_request_failed", detail=detail)}), 502
    except (requests.RequestException, RuntimeError) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else exc.__class__.__name__
        return jsonify({"error": status_message(language, "gemini_request_failed", detail=redact_secrets(detail, api_key=key)[:400])}), 502
    return jsonify({
        "model": model,
        "answers": data.get("answers") if isinstance(data, dict) else {},
        "usage": data.get("usage") if isinstance(data, dict) else {},
    })


@index_bp.post("/api/gemini/agents")
def gemini_agents_create():
    """Run one managed agent interaction through the Gemini Interactions API."""
    body = request.get_json(silent=True)
    language = normalize_language(body.get("lang") if isinstance(body, dict) else None)
    if not isinstance(body, dict):
        return jsonify({"error": status_message(language, "invalid_body")}), 400
    settings = load_settings()
    key = get_api_key("gemini", settings)
    if not key:
        return jsonify({"error": status_message(language, "gemini_key_missing")}), 400
    agent = str(body.get("agent") or settings.get("gemini_agent") or GEMINI_DEFAULT_AGENT).strip()
    prompt = str(body.get("input") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", agent) or not prompt or len(prompt) > 20_000:
        return jsonify({"error": status_message(language, "gemini_agents_invalid")}), 400
    environment = str(body.get("environment") or "remote").strip()[:200]
    payload: dict[str, Any] = {
        "agent": agent,
        "input": [{"type": "text", "text": prompt}],
        "environment": {"type": "remote"} if environment == "remote" else environment,
    }
    previous = body.get("previous_interaction_id")
    if isinstance(previous, str) and previous.strip():
        payload["previous_interaction_id"] = previous.strip()[:200]
    try:
        response = gemini_post("/interactions", settings, key, payload, timeout=300)
        data = response.json()
    except requests.HTTPError as exc:
        detail = gemini_error_detail(exc.response, key)
        return jsonify({"error": status_message(language, "gemini_request_failed", detail=detail)}), 502
    except (requests.RequestException, RuntimeError) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else exc.__class__.__name__
        return jsonify({"error": status_message(language, "gemini_request_failed", detail=redact_secrets(detail, api_key=key)[:400])}), 502
    if not isinstance(data, dict):
        return jsonify({"error": status_message(language, "gemini_request_failed", detail="empty response")}), 502
    steps = data.get("steps")
    answer = gemini_agent_answer(steps)
    if not answer and isinstance(data.get("output_text"), str):
        answer = data["output_text"]
    return jsonify({
        "answer": answer,
        "interaction_id": data.get("id"),
        "environment_id": data.get("environment_id"),
        "steps": steps if isinstance(steps, list) else [],
    })


@index_bp.post("/api/gemini/live-token")
def gemini_live_token():
    """Mint a short-lived Live API token so the browser never sees the API key."""
    body = request.get_json(silent=True)
    language = normalize_language(body.get("lang") if isinstance(body, dict) else None)
    if not isinstance(body, dict):
        return jsonify({"error": status_message(language, "invalid_body")}), 400
    settings = load_settings()
    key = get_api_key("gemini", settings)
    if not key:
        return jsonify({"error": status_message(language, "gemini_key_missing")}), 400
    model = str(body.get("model") or settings.get("gemini_live_model") or "").strip()[:120]
    if not model:
        # Prefer a conversational model the key can actually reach; the
        # capability check is cached, so a second Live start is cheap.
        try:
            model = str(gemini_capabilities(settings, language).get("live_default") or "")
        except (requests.RequestException, RuntimeError, ValueError, KeyError):
            model = ""
    if not model or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", model):
        model = GEMINI_LIVE_FALLBACK_MODEL
    now = datetime.now(timezone.utc)
    payload = {
        "uses": 1,
        "expireTime": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "newSessionExpireTime": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        response = gemini_post("/auth_tokens", settings, key, payload, timeout=30)
        data = response.json()
    except requests.HTTPError as exc:
        detail = gemini_error_detail(exc.response, key)
        return jsonify({"error": status_message(language, "gemini_live_failed", detail=detail)}), 502
    except (requests.RequestException, RuntimeError) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else exc.__class__.__name__
        return jsonify({"error": status_message(language, "gemini_live_failed", detail=redact_secrets(detail, api_key=key)[:400])}), 502
    token = data.get("name") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token.strip():
        return jsonify({"error": status_message(language, "gemini_live_failed", detail="missing token")}), 502
    return jsonify({
        "token": token,
        "model": model,
        "expires_at": payload["expireTime"],
        "ws_url": (
            "wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"
        ),
    })


@index_bp.post("/api/settings/reset")
def settings_reset():
    """Delete the persisted settings file and clear the status cache."""
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
    STATUS_CACHE.clear()
    forget_model_names()
    MODEL_LIST_ERROR_LOGGED.clear()
    return jsonify({"ok": True})


@index_bp.get("/api/server/status")
def server_status():
    """Report the running server, its address, and the saved TLS mode."""
    return no_store(jsonify({
        "running": True,
        "pid": os.getpid(),
        "scheme": "https" if request.is_secure else "http",
        "port": env_int("PORT", 5000, 1),
        "url": request.url_root.rstrip("/"),
        "uptime_seconds": max(0, int(time.time() - APP_STARTED_AT)),
        "tls": server_tls_state(),
        "script_available": SERVER_SCRIPT.is_file(),
    }))


@index_bp.put("/api/server/tls")
def server_tls_update():
    """Save HTTP/HTTPS mode to .env; the next restart applies it."""
    body = request.get_json(silent=True) or {}
    language = normalize_language(body.get("lang"))
    mode = str(body.get("mode") or "").strip().lower()
    if mode not in {"http", "https"}:
        return jsonify({"ok": False, "error": status_message(language, "tls_invalid_mode")}), 400
    if mode == "http":
        https_kind = "none"
        values = {"AI_WEB_TLS_CERT": "", "AI_WEB_TLS_KEY": "", "AI_WEB_TLS_ADHOC": ""}
    else:
        https_kind = "adhoc" if str(body.get("https_kind") or "").strip().lower() == "adhoc" else "cert"
        if https_kind == "cert":
            pair = configured_certificate_pair()
            if pair is None:
                return jsonify({"ok": False, "error": status_message(language, "tls_cert_missing")}), 400
            values = {
                "AI_WEB_TLS_CERT": pair[0],
                "AI_WEB_TLS_KEY": pair[1],
                "AI_WEB_TLS_ADHOC": "",
            }
        else:
            # Keep the certificate pair in .env while ad-hoc mode runs; ad-hoc
            # wins over the pair, so switching back to certificate files still
            # has the same paths instead of losing them.
            pair = configured_certificate_pair()
            values = {
                "AI_WEB_TLS_CERT": pair[0] if pair else "",
                "AI_WEB_TLS_KEY": pair[1] if pair else "",
                "AI_WEB_TLS_ADHOC": "1",
            }
    with TLS_ENV_LOCK:
        try:
            update_env_file(values)
        except OSError as exc:
            return error_response(
                language,
                "env_write_failed",
                exc=exc,
                body={"ok": False},
                event="system.tls_save_failed",
                message="Could not write the TLS mode to .env",
            )
        apply_tls_environment(values)
    log_event("system.tls_saved", "Saved the connection mode from the web page", mode=mode, kind=https_kind)
    return no_store(jsonify({
        "ok": True,
        "mode": mode,
        "https_kind": https_kind,
        "restart_required": True,
    }))


@index_bp.post("/api/server/action")
def server_action():
    """Start, stop, or restart the server through start_web.sh."""
    body = request.get_json(silent=True) or {}
    language = normalize_language(body.get("lang"))
    action = str(body.get("action") or "").strip().lower()
    if action not in {"start", "stop", "restart"}:
        return jsonify({"ok": False, "error": status_message(language, "server_action_invalid")}), 400
    if not SERVER_SCRIPT.is_file():
        return jsonify({"ok": False, "error": status_message(language, "server_script_missing")}), 400
    with SERVER_JOB_LOCK:
        process = SERVER_JOB.get("process")
        if process is not None and process.poll() is None:
            return jsonify({"ok": False, "error": status_message(language, "server_busy")}), 409
        try:
            SERVER_CONTROL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(SERVER_CONTROL_LOG, "ab") as handle:
                # stop/restart terminate this process, so wait until this
                # response has been delivered before the server goes away.
                command = [
                    "bash",
                    "-c",
                    f"sleep 2; exec {shlex.quote(str(SERVER_SCRIPT))} --{action}",
                ]
                child = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as exc:
            return error_response(
                language,
                "server_action_failed",
                exc=exc,
                body={"ok": False},
                event="system.server_action_failed",
                message="Could not start the server control command",
            )
        SERVER_JOB.update({
            "process": child,
            "action": action,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    log_event("system.server_action", "Server control requested from the web page", action=action)
    return no_store(jsonify({"ok": True, "action": action, "pid": child.pid})), 202


@index_bp.get("/api/update")
def update_state():
    """Report the installed build, the last update run, and its log tail."""
    log_tail, log_truncated = update_log_tail()
    snapshot = update_job_snapshot()
    return jsonify({
        **update_build_info(),
        "script_available": update_script_ready(),
        **snapshot,
        "log": log_tail,
        "log_truncated": log_truncated,
    })


@index_bp.post("/api/update/run")
def update_run():
    """Run update.sh for a dry-run check or a real update, detached from Flask."""
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode") or "apply").strip().lower()
    if mode not in UPDATE_MODES:
        return jsonify({"ok": False, "error": status_message(request_language(), "update_mode_invalid")}), 400
    if not update_script_ready():
        return jsonify({"ok": False, "error": status_message(request_language(), "update_script_missing")}), 400
    # Check the same view GET /api/update reports, so a job that is still running
    # after a server restart is not truncated and replaced by a second updater.
    if update_job_snapshot()["running"]:
        return jsonify({"ok": False, "error": status_message(request_language(), "update_busy")}), 409
    with UPDATE_JOB_LOCK:
        process = UPDATE_JOB.get("process")
        if process and process.poll() is None:
            return jsonify({"ok": False, "error": status_message(request_language(), "update_busy")}), 409
        args = [str(UPDATE_SCRIPT)]
        if mode == "check":
            # A dry run only compares files, so it must not write or restart.
            args += ["--dry-run", "--no-restart"]
        try:
            UPDATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(UPDATE_LOG_FILE, "wb") as handle:
                new_process = subprocess.Popen(
                    args,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    # A real update restarts the server; a separate session keeps
                    # this updater alive while the web process is replaced.
                    start_new_session=True,
                    env={**os.environ, "AI_WEB_UPDATE_FROM_WEB": "1"},
                )
        except OSError:
            return jsonify({"ok": False, "error": status_message(request_language(), "update_start_failed")}), 500
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UPDATE_JOB.clear()
        UPDATE_JOB.update({
            "process": new_process,
            "pid": new_process.pid,
            "mode": mode,
            "started_at": started_at,
            "finished_at": "",
            "ok": None,
            "exit_code": None,
        })
        save_update_status({"mode": mode, "started_at": started_at, "pid": new_process.pid})
    threading.Thread(target=watch_update_job, args=(new_process,), daemon=True).start()
    log_event("system.update_started", "Started a system update from the web page", mode=mode)
    return jsonify({"ok": True, "mode": mode, "pid": new_process.pid}), 202


TOOL_RESULT_CONTINUATION = (
    "The user approved the tool `{name}` and it has already run. Its output follows.\n\n"
    "{output}\n\n"
    "Continue the answer you were giving in plain text: do not greet the user again, do not ask "
    "what they need, and never show a tool_call or raw JSON unless it is the answer."
)


def prepare_tool_result_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap an approved tool result so the model continues instead of restarting.

    The page sends the tool output as a user turn after an approval, which read
    like a brand new question: the model greeted the user and began again. The
    turn keeps its content for the page and the history, but the provider sees a
    tool-result continuation instead.

    The placeholder turn that asked for the approval is dropped on the way: it
    is page text, and replaying it made a small model copy the sentence instead
    of answering from the tool result.
    """
    prepared: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "assistant" and is_approval_placeholder(item.get("content")):
            continue
        if item.get("tool_result"):
            name = str(item.get("tool_name") or "a tool")[:60]
            prepared.append({
                "role": item.get("role", "user"),
                "content": TOOL_RESULT_CONTINUATION.format(name=name, output=str(item.get("content") or "")),
            })
            continue
        prepared.append(item)
    return prepared


@index_bp.post("/api/chat")
def chat():
    """Answer one chat turn, retrying once with the configured fallback."""
    limited = rate_limit_response("chat")
    if limited:
        return limited
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return jsonify({"error": status_message(request_language(), "chat_message_required")}), 400

    provider = "openai"
    # Bound before the try block: the error handlers below must never raise a
    # NameError that hides the real cause.
    settings: dict[str, Any] = {}
    try:
        log_event("chat.start", "Started processing a message", message_count=len(messages))
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
        settings["system_prompt"] = build_system_prompt(settings, messages)
        provider = str(settings.get("provider", "openai")).lower()
        # Must run before clean_messages(), which keeps only role and content.
        messages = prepare_tool_result_turns(messages)
        messages = clean_messages(messages, settings)
        unsupported = None
        if normalize_provider(provider) in {"openai", "hf", "or", "groq"}:
            unsupported = next(
                (
                    item["attachment"]
                    for item in messages
                    if isinstance(item.get("attachment"), dict)
                    and not str(item["attachment"].get("mime_type") or "").startswith("image/")
                ),
                None,
            )
        if unsupported:
            # An OpenAI-compatible payload only maps images, so say the file
            # cannot be sent instead of quietly dropping it from the prompt.
            return jsonify({
                "error": status_message(
                    normalize_language(body.get("lang")),
                    "attachment_unsupported",
                    name=unsupported.get("name", ""),
                    mime=unsupported.get("mime_type", ""),
                )
            }), 400
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
        repaired = False
        for _ in range(6):
            try:
                tool_requests = parse_tool_requests(answer)
            except ValueError as exc:
                log_event("tool.parse_failed", "Skipped an unreadable tool_call", error=str(exc))
                tool_requests = []
            if not tool_requests:
                # A marker with a broken payload (bad JSON, wrong shape, or a
                # reply cut off mid-call) used to end up on screen as raw text.
                # Ask the model once to resend the same call in the documented
                # format before giving up on the turn.
                if not repaired and has_tool_marker(answer):
                    repaired = True
                    log_event("tool.repair_requested", "Asked the model to resend an unreadable tool_call")
                    messages.extend([
                        {"role": "assistant", "content": answer},
                        {"role": "user", "content": TOOL_CALL_REPAIR_INSTRUCTION},
                    ])
                    answer, usage = call_provider(messages, settings)
                    continue
                break
            # Refresh required-tool set using both policy observations
            # so machine access enabled during call_provider includes
            # read_file and list_files in the approval decision.
            _machine_access = machine_access_enabled(settings) or machine_access_enabled(load_settings())
            required_tools = approval_required_tools(
                {"machine_access": _machine_access} if _machine_access is not None else settings
            )
            approval_request = next(
                (item for item in tool_requests if TOOL_ALIASES.get(item["name"], item["name"]) in required_tools),
                None,
            )
            # Machine access always asks, whatever the command mode says.
            if approval_request and (
                machine_access_enabled(settings)
                or machine_access_enabled(load_settings())
                or command_mode not in {"auto", "fast"}
            ):
                approval_id, approval_expires_at = request_tool_approval(approval_request["name"], approval_request["arguments"])
                return jsonify({
                    "answer": APPROVAL_PLACEHOLDER,
                    "provider": provider,
                    "tool_request": approval_request,
                    "approval_id": approval_id,
                    # The client needs the expiry to only offer the button while
                    # the token can still be redeemed (e.g. after a reload).
                    "approval_expires_at": approval_expires_at,
                    # The matching server clock reading lets a browser whose
                    # clock is off still compute the real remaining lifetime.
                    "server_time": approval_expires_at - APPROVAL_TTL_SECONDS,
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
                {"role": "user", "content": f"Tool results:\n{json.dumps(results, ensure_ascii=False)}\n\nAnswer the user in plain text, describing the name and purpose of each detected Skill. Never show a tool_call or JSON."},
            ])
            answer, usage = call_provider(messages, settings)
        if has_tool_marker(answer):
            # Nothing usable came out of the tool protocol in this turn: never
            # show the raw block (it carries a command and can carry a key).
            # Text around the block is still delivered; a reply that was only
            # the unreadable call becomes a clear reason instead.
            answer = strip_tool_markers(answer)
            if not answer:
                log_event("tool.unreadable", "The final answer was only an unreadable tool_call", provider=provider)
                return jsonify({"error": status_message(request_language(), "tool_call_unreadable")}), 502
        # A provider can stop before the reply is complete (token budget, a
        # safety or recitation block). The partial text is still delivered, but
        # it must never look like a finished answer.
        finish_reason = str((usage or {}).get("finish_reason") or "").strip()
        if finish_reason.upper() in CUT_FINISH_REASONS:
            log_event("chat.reply_cut", "The provider stopped the reply early", provider=provider, reason=finish_reason)
            answer = f"{answer}\n\n{status_message(request_language(), 'chat_reply_cut', reason=finish_reason)}"
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        log_event("chat.success", "Replied successfully", provider=provider, model=settings["model"], duration_ms=duration_ms)
        # The model can echo a key it was given (a skill that embeds one, for
        # example), so what reaches the page - and the saved history - is
        # redacted here as well as in tool output.
        return jsonify({"answer": redact_secrets(answer), "provider": provider, "model": settings["model"], "fallback_used": fallback_used, "duration_ms": duration_ms, "usage": usage})
    except requests.HTTPError as exc:
        log_event("provider.error", "The provider answered with an HTTP error", status=exc.response.status_code if exc.response is not None else "unknown")
        api_key = safe_stored_api_key(provider, settings)
        if exc.response is not None and exc.response.status_code in {429, 503}:
            provider_label = PROVIDER_LABELS.get(provider, "The provider")
            return jsonify({"error": status_message(request_language(), "chat_busy", label=provider_label)}), 503
        fallback_detail = status_message(request_language(), "chat_provider_error")
        detail = redact_secrets(exc.response.text if exc.response is not None else fallback_detail, api_key=api_key)[:500]
        return jsonify({"error": status_message(request_language(), "chat_api_failed", detail=detail)}), 502
    except PROVIDER_NETWORK_ERRORS as exc:
        # requests timeouts and connection failures are OSError subclasses, so
        # they must be reported here before the generic handler turns them into
        # "could not process the message": the provider or the network failed.
        log_event("provider.network_error", "Could not reach the provider", provider=provider, error=str(exc)[:300])
        status = 504 if isinstance(exc, requests.Timeout) else 502
        return jsonify({
            "error": status_message(
                request_language(),
                "chat_network_failed",
                label=PROVIDER_LABELS.get(provider, provider),
            )
        }), status
    except ProviderEmptyResponse as exc:
        log_event("provider.empty_response", "The provider returned no text", provider=provider, reason=exc.finish_reason)
        return jsonify({
            "error": status_message(
                request_language(),
                "chat_empty_response",
                label=PROVIDER_LABELS.get(provider, provider),
                reason=exc.finish_reason or "unknown",
            )
        }), 502
    except (KeyError, IndexError, RuntimeError, ValueError, FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        log_event("chat.error", "Could not process the message", error=str(exc))
        return jsonify({"error": status_message(request_language(), "chat_failed")}), 500
