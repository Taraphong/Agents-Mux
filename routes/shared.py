"""Response builders shared by the page blueprints.

These translate a settings update, a model list or a Gemini answer into the
JSON the page expects; they belong with the routes, not with the app assembly.
"""

from typing import Any

import requests
from flask import jsonify, request

import memory_engine

from core.log import log_event
from core.messages import request_language, status_message
from core.model_cache import remember_model_names
from core.providers import (
    FALLBACK_MODELS,
    STATUS_CACHE,
    key_is_configured,
    list_models,
)
from core.redaction import redact_secrets
from core.settings import (
    load_settings,
    normalize_custom_key_name,
    normalize_provider,
    parse_discord_ids,
    save_settings,
    stored_api_keys,
    stored_custom_api_keys,
)
from core.skills import list_skills
from services.discord_bot import start_discord_bot, stop_discord_bot


def error_response(
    language: str,
    key: str,
    *,
    status: int = 500,
    exc: BaseException | None = None,
    body: dict[str, Any] | None = None,
    event: str = "api.error",
    message: str,
    **details: Any,
):
    """Log the failure detail and return a generic, localized error body.

    Internal exceptions belong in the log: their text can hold paths, request
    ids and provider fragments the page must not see. ``message`` is the log
    line, ``details`` become log fields, and ``body`` adds non-error response
    fields such as ``{"ok": False}`` - it can never replace ``"error"``.

    Policy: this helper covers failures of our own code. A provider response
    that is already redacted and bounded (the Gemini endpoints and the settings
    connection test) keeps its detail, because it is actionable copy for the
    user rather than an internal trace.
    """
    if exc is not None:
        details.setdefault("error", redact_secrets(str(exc))[:300])
    if details:
        log_event(event, message, **details)
    payload: dict[str, Any] = {**(body or {}), "error": status_message(language, key)}
    return jsonify(payload), status


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
    previous_base_url = current.get("base_url")
    allowed = {"memory", "agent_name", "agent_role", "response_language", "response_style", "use_markdown", "ask_clarifying_questions", "provider", "model", "base_url", "system_prompt", "memory_review", "skills", "temperature", "max_tokens", "top_p", "thinking_level", "stream", "fallback_enabled", "fallback_provider", "fallback_model", "gemini_live_model", "gemini_agent", "gemini_decision_model", "discord_enabled", "discord_prefix", "discord_allowed_users", "discord_allowed_channels", "machine_access"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    if "••" in str(current.get("base_url") or ""):
        # /api/settings masks credentials inside the Base URL, so a value that
        # still carries the mask means "keep the stored URL" like api_key does.
        current["base_url"] = previous_base_url
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
