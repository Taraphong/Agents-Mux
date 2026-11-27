"""Response builders shared by the page blueprints.

These translate a settings update, a model list or a Gemini answer into the
JSON the page expects; they belong with the routes, not with the app assembly.
"""

from typing import Any

import requests
from flask import jsonify, request

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
from core.settings import load_settings, save_settings
from core.settings_update import (
    SettingsUpdateError,
    apply_settings_payload,
)
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
    """Apply a settings PUT body; call with SETTINGS_LOCK held.

    The rules live in core.settings_update so the page and the AI's
    update_settings tool cannot drift apart; this wrapper keeps the HTTP shape
    the page expects and syncs the side effects (Discord bot, status cache).
    """
    body = request.get_json(silent=True) or {}
    current = load_settings()
    try:
        current = apply_settings_payload(current, body)
    except SettingsUpdateError as exc:
        return jsonify({"error": status_message(request_language(), exc.key, **exc.details)}), 400
    save_settings(current)
    STATUS_CACHE.clear()
    if current.get("discord_enabled"):
        start_discord_bot()
    else:
        stop_discord_bot()
    return jsonify({
        "ok": True,
        "provider": current["provider"],
        "has_api_key": key_is_configured(current["provider"], current),
    })


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
