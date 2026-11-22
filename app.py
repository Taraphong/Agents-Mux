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

# Imported after load_dotenv(): the module resolves AI_WEB_MEMORY_* paths at
# import time, so a value that exists only in .env must already be loaded.
import memory_engine  # noqa: E402


from core.env import env_int




app = Flask(__name__)
from core.log import (
    APP_LOGS,
    APP_LOG_LOCK,
    LOGGER,
    load_persisted_logs,
    log_event,
    set_redactor,
)


# Reject oversized bodies before they reach the JSON parser or the history writer.
app.config["MAX_CONTENT_LENGTH"] = env_int("AI_WEB_MAX_CONTENT_BYTES", 8 * 1024 * 1024, 64 * 1024)
from core.config import (
    ADHOC_CERT_FILE,
    ADHOC_KEY_FILE,
    APPROVAL_REQUIRED_TOOLS,
    APPROVAL_TTL_SECONDS,
    ASSET_CACHE_CONTROL,
    AUTH_ENABLED,
    AUTH_FILE,
    AUTH_KEY_ALPHABET,
    AUTH_KEY_LENGTH,
    AUTH_PAIRING_FAILURE_WINDOW,
    AUTH_PAIRING_MAX_FAILURES,
    AUTH_PAIRING_TTL_MINUTES,
    AUTH_PUBLIC_PATHS,
    AUTH_PUBLIC_PREFIXES,
    AUTH_SESSION_COOKIE,
    AUTH_SESSION_COOKIE_HTTP,
    AUTH_SESSION_COOKIE_NAMES,
    AUTH_SESSION_DAYS,
    AUTH_TRUST_PROXY,
    CERT_DIR,
    COMMAND_MAX_OUTPUT_BYTES,
    COMMAND_TIMEOUT_SECONDS,
    ENV_FILE,
    HISTORY_LOCK_FILE,
    HISTORY_ROOT,
    HISTORY_ROOT_TEXT,
    LOG_FILE,
    MACHINE_TOOL_NAMES,
    MAX_PENDING_APPROVALS,
    MUTATING_METHODS,
    PAGE_ASSETS,
    PROJECT_ROOT,
    PROJECT_ROOT_TEXT,
    PROTECTED_NAMES,
    PROTECTED_PARTS,
    SCHEDULE_CONTEXT_MESSAGES,
    SCHEDULE_FILE,
    SCHEDULE_LOCK_FILE,
    SENSITIVE_ENV_PARTS,
    SERVER_CONTROL_LOG,
    SERVER_SCRIPT,
    SETTINGS_FILE,
    SKILLS_ROOT,
    SKILLS_ROOT_TEXT,
    TEMPLATES_ROOT,
    TOOL_ALIASES,
    TOOL_CALL_BLOCK_PATTERN,
    TOOL_INSTRUCTIONS,
    TOOL_MAX_READ_BYTES,
    TOOL_MAX_WRITE_BYTES,
    WORKSPACE_ROOT,
)


from core.schedule_store import (
    SCHEDULE_LOCK,
    cron_matches,
    cron_values,
    load_schedules,
    save_schedules,
    update_schedule,
    validate_cron,
)


APP_STARTED_AT = time.time()
SERVER_JOB: dict[str, Any] = {"process": None, "action": "", "started_at": ""}
SERVER_JOB_LOCK = threading.Lock()
from core.http_cache import (
    ASSET_GZIP_CACHE,
    ASSET_GZIP_CACHE_LIMIT,
    ASSET_GZIP_LOCK,
    GZIP_MIMETYPES,
    GZIP_MIN_BYTES,
    accepts_gzip,
    compress_response,
    gzip_body,
    representation_etag,
)


from core.tools import (
    ASCII_LOWERCASE_TABLE,
    PENDING_APPROVAL_LOCK,
    PENDING_TOOL_REQUESTS,
    SAFE_GIT_OPTIONS,
    SAFE_GIT_SUBCOMMANDS,
    SAFE_LS_OPTIONS,
    approval_required_tools,
    command_environment,
    command_shell,
    configured_secret_targets,
    consume_tool_approval,
    display_tool_path,
    ensure_safe_command_token,
    kill_process_group,
    machine_access_enabled,
    parse_command,
    parse_tool_request,
    parse_tool_requests,
    process_group_alive,
    protected_write_target,
    read_command_capture,
    request_tool_approval,
    resolve_machine_path,
    resolve_project_path,
    resolve_tool_path,
    run_local_tool,
    run_shell_process,
    secret_values,
    tool_call_bodies,
    workspace_directory,
    workspace_tool_path,
)


from services.scheduler import (
    SCHEDULE_RUNNING,
    SCHEDULE_RUNNING_LOCK,
    _SCHEDULER_LOCK_HANDLE,
    _SCHEDULER_START_LOCK,
    _SCHEDULER_STARTED,
    execute_schedule,
    schedule_conversation_id,
    schedule_loop,
    start_scheduler,
)




from core.auth import (
    AUTH_LOCK,
    AUTH_PAIRING_FAILURES,
    active_auth_session_count,
    auth_expired,
    auth_now,
    auth_session_tokens,
    auth_timestamp,
    bootstrap_pairing_key,
    consume_pairing_key,
    create_auth_session,
    current_auth_session,
    empty_auth_state,
    format_pairing_key,
    generate_pairing_key,
    hash_auth_token,
    load_auth_state,
    no_store,
    normalize_pairing_key,
    pairing_attempt_allowed,
    print_pairing_banner,
    prune_auth_state,
    record_pairing_failure,
    revoke_all_auth_sessions,
    revoke_auth_session,
    save_auth_state,
)



if AUTH_TRUST_PROXY:
    # Honour X-Forwarded-Proto/Host when TLS terminates at a reverse proxy so
    # request.is_secure (and the Secure session cookie) reflects the client.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)





from core.skills import list_skills, selected_skill_prompt, skill_dir, skill_path












load_persisted_logs()

from core.settings import (
    CUSTOM_KEY_NAME_PATTERN,
    DEFAULT_SETTINGS,
    PROVIDERS,
    PROVIDER_BASE_URLS,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABELS,
    SETTINGS_LOCK,
    discord_access_allowed,
    get_discord_token,
    load_settings,
    migrate_legacy_api_key,
    normalize_custom_key_name,
    normalize_discord_ids,
    normalize_provider,
    parse_discord_ids,
    save_settings,
    set_saved_hook,
    stored_api_keys,
    stored_custom_api_keys,
)



from core.providers import (
    ALLOW_INSECURE_PROVIDER_HTTP,
    FALLBACK_MODELS,
    GEMINI_AGENT_PRESETS,
    GEMINI_CAPABILITY_CACHE,
    GEMINI_CAPABILITY_CACHE_TTL,
    GEMINI_CAPABILITY_LOCK,
    GEMINI_CAPABILITY_PROBE,
    GEMINI_DECISION_MODEL,
    GEMINI_DEFAULT_AGENT,
    GEMINI_LIVE_FALLBACK_MODEL,
    MODEL_LIST_CACHE,
    MODEL_LIST_CACHE_TTL,
    MODEL_LIST_ERROR_LOGGED,
    MODEL_LIST_REFRESH_INTERVAL,
    MODEL_LIST_REFRESH_LOCK,
    MODEL_LIST_REFRESH_STARTED,
    MODEL_LIST_REFRESH_TIMEOUT,
    MULTIMODAL_MAX_BYTES,
    MULTIMODAL_MIME_PREFIXES,
    MULTIMODAL_MIME_TYPES,
    PROVIDER_NETWORK_ERRORS,
    ProviderEmptyResponse,
    STATUS_CACHE,
    STATUS_CACHE_TTL,
    agent_profile_prompt,
    anthropic_adaptive_thinking_supported,
    anthropic_content,
    anthropic_model_version,
    anthropic_thinking_supported,
    attachment_payload,
    build_system_prompt,
    call_anthropic,
    call_gemini,
    call_openai,
    call_provider,
    clean_messages,
    endpoint_is_loopback,
    ensure_secure_model_endpoint,
    forget_model_names,
    gemini_agent_presets,
    gemini_base_url,
    gemini_capabilities,
    gemini_feature_groups,
    gemini_model_metadata,
    gemini_parts,
    gemini_post,
    get_api_key,
    get_base_url,
    is_openai_reasoning_model,
    key_is_configured,
    key_looks_plausible,
    keyless_loopback_provider,
    list_models,
    memory_context_block,
    model_names_for_autocomplete,
    normalize_usage,
    openai_content,
    provider_key_check,
    provider_models_get,
    provider_readiness,
    refresh_model_names,
    rejects_sampling_params,
    remember_model_names,
    safe_stored_api_key,
    same_secret,
    schedule_model_list_refresh,
    static_model_names,
)






from services.discord_bot import (
    DISCORD_ACTIVE_TOKEN,
    DISCORD_BOT,
    DISCORD_CONTEXTS,
    DISCORD_CONTEXT_LOCK,
    DISCORD_CONVERSATION_IDS,
    DISCORD_LOOP,
    DISCORD_THREAD,
    discord_status,
    send_discord_schedule_result,
    split_discord_message,
    start_discord_bot,
    stop_discord_bot,
)














































from core.paths import normalized_path_under


















try:
    workspace_directory()
except OSError as exc:
    LOGGER.warning("Could not create the AI workspace folder: %s", exc)


























from core.redaction import (
    PEM_LOOKBACK_BYTES,
    PEM_MARKER_PATTERN,
    PEM_REDACTED_MARKER,
    SECRET_QUERY_PATTERN,
    mask_unterminated_pem,
    pem_state,
    redact_command_output,
    redact_secrets,
    set_secret_provider,
)












# Log records are redacted with the same rule before they are stored, and the
# secret list is read through app.secret_values() on every call so a key saved
# after start-up is redacted at once.
set_redactor(redact_secrets)
set_secret_provider(lambda: secret_values())


















from core.history import (
    HISTORY_LOCK,
    HistoryConflict,
    HistoryLocked,
    _save_history_unlocked,
    _write_history_record,
    append_history_messages,
    find_history_file,
    find_schedule_conversation_id,
    history_generation,
    history_mutation_lock,
    history_record_path,
    load_history_record,
    read_history_file,
    save_discord_turn,
    save_history,
)
















































# Saving settings can change the available models, so core.settings drops this
# cache through the hook instead of importing app.
set_saved_hook(forget_model_names)






















from core.messages import STATUS_MESSAGES, normalize_language, status_message








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


















































































































@app.before_request
def reject_cross_site_mutation():
    """Refuse state-changing requests that a browser sent from another site."""
    if request.method not in MUTATING_METHODS:
        return None
    # Sec-Fetch-Site is set by the browser and cannot be forged by page script,
    # so it catches a cross-site request even when the Origin comparison is
    # defeated by a spoofed or proxy-supplied Host / X-Forwarded-Host.
    fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if fetch_site in {"cross-site", "same-site"}:
        log_event("security.cross_site", "Rejected a cross-site request", path=request.path, method=request.method, site=fetch_site)
        return jsonify({"error": status_message(request_language(), "cross_origin")}), 403
    origin = request.headers.get("Origin", "").strip()
    if origin:
        parsed = urlsplit(origin)
        if not (parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request.host.lower()):
            log_event("security.cross_origin", "Rejected a request from another origin", path=request.path, method=request.method)
            return jsonify({"error": status_message(request_language(), "cross_origin")}), 403
    # Only a request that will actually be served counts as the owner being
    # active: recording it before these checks let rejected cross-site requests
    # postpone the nightly memory run. An unpaired client is rejected below.
    if not AUTH_ENABLED or current_auth_session():
        memory_engine.touch_activity()
    return None


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


from core.tls import (
    RESPONSE_LINGER_SECONDS,
    TLS_ENV_KEYS,
    TLS_ENV_LOCK,
    TLS_HANDSHAKE_TIMEOUT_SECONDS,
    DrainingRequestHandler,
    TLSServer,
    _is_ip_address,
    adhoc_certificate,
    apply_tls_environment,
    build_tls_context,
    configured_certificate_pair,
    server_tls_state,
    set_log_event,
    tls_configuration,
    update_env_file,
)

set_log_event(log_event)



























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

