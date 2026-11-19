"""Routes for the chat page (index) and the API it uses.

The handlers were split out of app.py so the page-specific code stays in one
place; shared helpers, settings, history and the Flask app remain in app.py,
which registers this blueprint.
"""

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from app import (
    APPROVAL_TTL_SECONDS,
    APP_LOGS,
    APP_LOG_LOCK,
    APP_STARTED_AT,
    ASSET_CACHE_CONTROL,
    Any,
    GEMINI_DECISION_MODEL,
    GEMINI_DEFAULT_AGENT,
    GEMINI_LIVE_FALLBACK_MODEL,
    HISTORY_LOCK,
    HISTORY_ROOT,
    HistoryConflict,
    HistoryLocked,
    LOG_FILE,
    MODEL_LIST_ERROR_LOGGED,
    PAGE_ASSETS,
    PROJECT_ROOT,
    PROVIDERS,
    PROVIDER_LABELS,
    rate_limit_response,
    Path,
    SCHEDULE_LOCK,
    SCHEDULE_RUNNING,
    SCHEDULE_RUNNING_LOCK,
    SERVER_CONTROL_LOG,
    SERVER_JOB,
    SERVER_JOB_LOCK,
    SERVER_SCRIPT,
    SETTINGS_FILE,
    SETTINGS_LOCK,
    STATUS_CACHE,
    TEMPLATES_ROOT,
    TERMINAL_TIMEOUT_SECONDS,
    TLS_ENV_LOCK,
    TOOL_ALIASES,
    TOOL_INSTRUCTIONS,
    TOOL_MAX_WRITE_BYTES,
    UPDATE_JOB,
    UPDATE_JOB_LOCK,
    UPDATE_LOG_FILE,
    UPDATE_MODES,
    UPDATE_SCRIPT,
    _write_history_record,
    agent_profile_prompt,
    append_history_messages,
    apply_settings_update,
    apply_tls_environment,
    approval_required_tools,
    call_provider,
    clean_messages,
    compress_response,
    configured_certificate_pair,
    consume_tool_approval,
    datetime,
    discord_status,
    env_int,
    execute_schedule,
    execute_terminal_command,
    find_history_file,
    forget_model_names,
    gemini_agent_answer,
    gemini_capabilities,
    gemini_error_detail,
    gemini_post,
    get_api_key,
    get_discord_token,
    json,
    key_is_configured,
    list_skills,
    load_schedules,
    load_settings,
    log_event,
    machine_access_enabled,
    models_response,
    no_store,
    normalize_language,
    normalize_provider,
    os,
    parse_tool_requests,
    provider_readiness,
    re,
    read_history_file,
    redact_secrets,
    request_language,
    request_tool_approval,
    requests,
    resolve_terminal_cwd,
    run_local_tool,
    safe_stored_api_key,
    save_history,
    save_schedules,
    save_update_status,
    selected_skill_prompt,
    server_tls_state,
    shlex,
    shutil,
    skill_path,
    status_message,
    stored_api_keys,
    stored_custom_api_keys,
    subprocess,
    terminal_identity,
    terminal_is_enabled,
    terminal_settings,
    terminal_shell,
    threading,
    time,
    timedelta,
    timezone,
    update_build_info,
    update_env_file,
    update_job_snapshot,
    update_log_tail,
    update_script_ready,
    uuid,
    validate_cron,
    watch_update_job,
)

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
        # with a token this endpoint will reject.
        return jsonify({"ok": False, "error": status_message(request_language(), "tool_failed"), "approval_consumed": approved}), 400


@index_bp.get("/api/terminal/info")
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


@index_bp.post("/api/terminal/exec")
def terminal_exec():
    """Run one terminal command submitted by the web UI."""
    limited = rate_limit_response("terminal")
    if limited:
        return limited
    body = request.get_json(silent=True) or {}
    command = body.get("command")
    if not isinstance(command, str):
        return jsonify({"ok": False, "error": status_message(request_language(), "command_required")}), 400
    try:
        cwd = resolve_terminal_cwd(body.get("cwd", "."))
        result = execute_terminal_command(command, cwd)
        return jsonify({"ok": True, **result})
    except (PermissionError, FileNotFoundError, ValueError, OSError, subprocess.SubprocessError) as exc:
        log_event("tool.terminal_error", "The terminal command failed", error=str(exc))
        return jsonify({"ok": False, "error": status_message(request_language(), "terminal_failed")}), 400


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
    safe["available_skills"] = [{"name": item["name"]} for item in list_skills()]
    return jsonify(safe)


@index_bp.get("/api/skills")
def skills_get():
    """List the available skills with their content."""
    return jsonify({"items": list_skills()})


@index_bp.get("/api/skills/<name>")
def skill_get(name: str):
    """Return one skill's content by name."""
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": status_message(request_language(), "skill_not_found")}), 404
        return jsonify({"name": path.parent.name, "content": path.read_text(encoding="utf-8")[:20_000]})
    except (OSError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_read_failed")}), 400


@index_bp.post("/api/skills")
def skills_create():
    """Create a new skill from the settings UI payload."""
    body = request.get_json(silent=True) or {}
    try:
        result = run_local_tool("create_skill", {"name": body.get("name", ""), "content": body.get("content", "")}, approved=True)
        return jsonify(result), 201
    except (OSError, PermissionError, ValueError):
        return jsonify({"error": status_message(request_language(), "skill_create_failed")}), 400


@index_bp.put("/api/skills/<name>")
def skills_update(name: str):
    """Replace the content of an existing skill."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
        return jsonify({"error": status_message(request_language(), "skill_content_invalid")}), 400
    try:
        path = skill_path(name)
        if not path.exists():
            return jsonify({"error": status_message(request_language(), "skill_not_found")}), 404
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return jsonify({"ok": True, "name": path.parent.name})
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
    # omitted base_url leaves the configured value untouched.
    if isinstance(base_url, str):
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
            return jsonify({"ok": False, "error": status_message(language, "env_write_failed", error=str(exc))}), 500
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
            return jsonify({"ok": False, "error": status_message(language, "server_action_failed", error=str(exc))}), 500
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
        settings["system_prompt"] = "\n\n".join(
            part for part in (
                settings.get("system_prompt", ""),
                agent_profile_prompt(settings),
                f"Memory review guidance:\n{settings.get('memory_review', '')}" if settings.get("memory_review") else "",
                selected_skill_prompt(settings),
                TOOL_INSTRUCTIONS,
            ) if part
        )
        provider = str(settings.get("provider", "openai")).lower()
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
        for _ in range(6):
            try:
                tool_requests = parse_tool_requests(answer)
            except ValueError as exc:
                log_event("tool.parse_failed", "Skipped an incomplete tool_call", error=str(exc))
                tool_requests = []
            if not tool_requests:
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
                    "answer": "The AI requested a tool that needs approval first",
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
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        log_event("chat.success", "Replied successfully", provider=provider, model=settings["model"], duration_ms=duration_ms)
        return jsonify({"answer": answer, "provider": provider, "model": settings["model"], "fallback_used": fallback_used, "duration_ms": duration_ms, "usage": usage})
    except requests.HTTPError as exc:
        log_event("provider.error", "The provider answered with an HTTP error", status=exc.response.status_code if exc.response is not None else "unknown")
        api_key = safe_stored_api_key(provider, settings)
        if exc.response is not None and exc.response.status_code in {429, 503}:
            provider_label = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic"}.get(provider, "The provider")
            return jsonify({"error": status_message(request_language(), "chat_busy", label=provider_label)}), 503
        fallback_detail = status_message(request_language(), "chat_provider_error")
        detail = redact_secrets(exc.response.text if exc.response is not None else fallback_detail, api_key=api_key)[:500]
        return jsonify({"error": status_message(request_language(), "chat_api_failed", detail=detail)}), 502
    except (KeyError, IndexError, RuntimeError, ValueError, FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        log_event("chat.error", "Could not process the message", error=str(exc))
        return jsonify({"error": status_message(request_language(), "chat_failed")}), 500
