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


SCHEDULE_RUNNING: set[str] = set()
SCHEDULE_RUNNING_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_START_LOCK = threading.Lock()
_SCHEDULER_LOCK_HANDLE: Any = None


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



FALLBACK_MODELS = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini", "o3"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
    "hf": ["meta-llama/Llama-3.1-8B-Instruct", "mistralai/Mistral-7B-Instruct"],
    "or": ["openai/gpt-3.5-turbo", "anthropic/claude-3-haiku-20240307"],
    "groq": ["mixtral-8x7b-32768", "gemma-7b-it"],
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
    # A local llama-server/Ollama serves /models without a key, matching the
    # rule call_openai() and provider_readiness() use for the chat request.
    if not key and not keyless_loopback_provider(provider, settings):
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
        headers={"Authorization": f"Bearer {key}"} if key else None,
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


# Saving settings can change the available models, so core.settings drops this
# cache through the hook instead of importing app.
set_saved_hook(forget_model_names)


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
        "memory_pin_failed": "ตั้งหรือยกเลิก pin ไม่สำเร็จ",
        "memory_pin_invalid": "ต้องระบุ pinned เป็น true หรือ false",
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
        "chat_network_failed": "ติดต่อ {label} ไม่สำเร็จ เพราะรอคำตอบนานเกินกำหนดหรือเครือข่ายไม่พร้อมใช้งาน (ลองใหม่ให้แล้ว 1 ครั้ง) กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองอีกครั้ง",
        "chat_empty_response": "{label} ตอบกลับมาโดยไม่มีข้อความ (finishReason: {reason}) — โมเดลมักใช้โควตาคำตอบไปกับการคิดจนหมด ลองเพิ่ม Max tokens หรือลดระดับการคิด",
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
        "memory_pin_failed": "Could not update the pin on that memory entry",
        "memory_pin_invalid": "pinned must be true or false",
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
        "chat_network_failed": "Could not reach {label}: the request timed out or the network is unavailable (retried once). Check the connection and try again",
        "chat_empty_response": "{label} returned no text (finishReason: {reason}); the model usually uses its whole output budget on thinking. Raise Max tokens or lower the thinking level",
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


def keyless_loopback_provider(provider: str, settings: dict[str, Any]) -> bool:
    """Whether a provider is a local endpoint that works without an API key.

    ``call_openai()`` accepts a loopback endpoint with no key (llama-server,
    Ollama), and Gemini and Anthropic always need one.
    """
    return provider not in {"gemini", "anthropic"} and endpoint_is_loopback(
        get_base_url(provider, settings)
    )


def provider_readiness(settings: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Check locally, then remotely, whether the selected provider and model are usable."""
    provider = normalize_provider(settings.get("provider"))
    model = str(settings.get("model") or "").strip()
    label = PROVIDER_LABELS[provider]
    key = get_api_key(provider, settings)
    base = {"provider": provider, "model": model}
    keyless_local = keyless_loopback_provider(provider, settings)
    if not key and not keyless_local:
        return {**base, "ready": False, "reason": status_message(language, "missing_key", label=label), "checked": "local"}
    if not model:
        return {**base, "ready": False, "reason": status_message(language, "missing_model", label=label), "checked": "local"}
    if keyless_local and not key:
        # A no-key local server is usable, and the request path already accepts
        # it: without this the page disabled Send for a working setup.
        return {**base, "ready": True, "reason": "", "checked": "local"}
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


def memory_context_block(messages: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    """Return the memory block for the newest user turn, or an empty string."""
    query = ""
    for item in reversed(messages):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        text = content if isinstance(content, str) else memory_engine.message_text(item)
        if text.strip():
            query = text
            break
    if not query:
        return ""
    try:
        block, _ids = memory_engine.build_context(query, settings)
    except Exception:
        return ""
    return block


def build_system_prompt(
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    include_memory_review: bool = True,
) -> str:
    """Assemble the system prompt with the memory block before tool rules.

    The block sits before the skill and tool instructions: a stored note must
    never occupy the position the model treats as the strongest instruction.
    """
    memory_review = (
        f"Memory review guidance:\n{settings.get('memory_review', '')}"
        if include_memory_review and settings.get("memory_review")
        else ""
    )
    parts = (
        settings.get("system_prompt", ""),
        agent_profile_prompt(settings),
        memory_review,
        memory_context_block(messages, settings),
        selected_skill_prompt(settings),
        TOOL_INSTRUCTIONS,
    )
    return "\n\n".join(part for part in parts if part)


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


class ProviderEmptyResponse(RuntimeError):
    """The provider answered without any text, so there is nothing to show.

    Thinking models count their reasoning tokens against the output budget, so
    a small Max tokens can end the answer before the first text token. That is
    not an app failure and must not be reported as one.
    """

    def __init__(self, message: str, finish_reason: str = "") -> None:
        super().__init__(message)
        self.finish_reason = finish_reason


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
    choice = data["choices"][0]
    content = choice.get("message", {}).get("content")
    if not str(content or "").strip():
        # A reasoning model can spend its whole output budget before it writes
        # text; a blank bubble would look like the app silently failed.
        raise ProviderEmptyResponse(
            f"OpenAI-compatible response contained no text (finishReason={choice.get('finish_reason')})",
            str(choice.get("finish_reason") or ""),
        )
    return content, normalize_usage(data.get("usage"), "prompt_tokens", "completion_tokens", "total_tokens")


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
        raise ProviderEmptyResponse(
            f"Gemini response contained no text (finishReason={finish_reason})",
            finish_reason,
        )
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
        stop_reason = str(data.get("stop_reason") or "unknown")
        raise ProviderEmptyResponse(
            f"Anthropic response contained no text block (stop_reason={stop_reason})",
            stop_reason,
        )
    return text, normalize_usage(usage, "input_tokens", "output_tokens", None)


# A timeout or a dropped connection means the provider or the network failed,
# not the app: retry once and let the caller report it as such.
PROVIDER_NETWORK_ERRORS = (
    requests.Timeout,
    requests.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def call_provider(messages: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """Dispatch one chat turn, retrying once when the provider is unreachable."""
    provider = settings["provider"].lower()
    for attempt in range(2):
        try:
            if provider == "gemini":
                return call_gemini(messages, settings)
            if provider == "anthropic":
                return call_anthropic(messages, settings)
            return call_openai(messages, settings)
        except PROVIDER_NETWORK_ERRORS as exc:
            if attempt:
                raise
            # A stalled read or a dropped link usually clears on the next try.
            log_event("provider.retry", "Retrying the provider after a network error", provider=provider, error=str(exc)[:200])
            time.sleep(1)


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
            settings_for_chat["system_prompt"] = build_system_prompt(
                settings_for_chat, messages, include_memory_review=False
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

