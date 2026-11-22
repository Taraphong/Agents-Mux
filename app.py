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


from core.runtime import APP_STARTED_AT, SERVER_JOB, SERVER_JOB_LOCK


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






















from core.messages import (
    STATUS_MESSAGES,
    normalize_language,
    request_language,
    status_message,
)








# A simple in-process limiter for the expensive, state-changing endpoints.
# Pairing already has its own failure limiter; this keeps a paired device (or a
# script that got hold of a session) from hammering the provider API.
from core.ratelimit import (
    API_RATE_BUDGETS,
    API_RATE_LIMITS,
    API_RATE_LOCK,
    api_rate_limited,
    rate_limit_response,
)




























































































































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


from routes.shared import (
    apply_settings_update,
    gemini_agent_answer,
    gemini_error_detail,
    models_response,
)










from core.update_job import (
    UPDATE_JOB,
    UPDATE_JOB_LOCK,
    UPDATE_LOG_FILE,
    UPDATE_LOG_TAIL_LINES,
    UPDATE_MODES,
    UPDATE_SCRIPT,
    UPDATE_STATUS_FILE,
    load_update_status,
    process_is_alive,
    save_update_status,
    update_build_info,
    update_job_snapshot,
    update_log_finished_at,
    update_log_succeeded,
    update_log_tail,
    update_script_ready,
    watch_update_job,
)
























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
from routes.index import index_bp  # noqa: E402  (must follow the definitions above)
from routes.pair import pair_bp  # noqa: E402

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

