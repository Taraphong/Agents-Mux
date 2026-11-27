"""The single write path for application settings.

The Settings page (``PUT /api/settings``) and the AI's own ``update_settings``
tool both go through :func:`apply_settings_payload`, so the agent can change its
name, behaviour, models, memory options and Discord allowlists exactly the way
the page does instead of a second set of rules drifting from the first one.

Two kinds of setting stay out of the agent's reach: the stored secrets (API
keys, the Discord token) and the switches that decide whether tools need an
approval at all (``machine_access`` and the per-message ``command_mode``). A
model must never be able to lift its own permission gate; those changes are
made by the person on the Settings page.
"""

import os
from typing import Any

import memory_engine

from core.providers import STATUS_CACHE
from core.redaction import mask_url_credentials
from core.settings import (
    DEFAULT_SETTINGS,
    SETTINGS_LOCK,
    load_settings,
    normalize_custom_key_name,
    normalize_provider,
    normalize_update_settings,
    parse_discord_ids,
    save_settings,
    stored_api_keys,
    stored_custom_api_keys,
)
from core.skills import list_skills

# Every field the settings form may write. A body key outside this set is
# ignored by the page (it may send an old form) and rejected for the agent.
ALLOWED_SETTING_KEYS = {
    "memory",
    "update",
    "agent_name",
    "agent_role",
    "response_language",
    "response_style",
    "use_markdown",
    "ask_clarifying_questions",
    "provider",
    "model",
    "base_url",
    "system_prompt",
    "memory_review",
    "skills",
    "temperature",
    "max_tokens",
    "top_p",
    "thinking_level",
    "stream",
    "fallback_enabled",
    "fallback_provider",
    "fallback_model",
    "gemini_live_model",
    "gemini_agent",
    "gemini_decision_model",
    "discord_enabled",
    "discord_prefix",
    "discord_allowed_users",
    "discord_allowed_channels",
    "machine_access",
}
# The identity and behaviour fields the AI may change about itself.
AGENT_SETTING_KEYS = ALLOWED_SETTING_KEYS - {"machine_access"}
# Settings that hold a credential, and the switches that decide whether a tool
# needs an approval. The page writes them; the agent only reads a masked report.
SECRET_SETTING_KEYS = {
    "api_key",
    "api_keys",
    "custom_api_key",
    "custom_api_keys",
    "delete_custom_api_key",
    "discord_token",
}
LOCKED_AGENT_KEYS = SECRET_SETTING_KEYS | {"machine_access", "command_mode"}
MASK = "••••••••"


class SettingsUpdateError(ValueError):
    """A rejected settings update.

    ``key`` is a ``STATUS_MESSAGES`` entry the route localizes, while the
    exception text is the English sentence a tool result shows.
    """

    def __init__(self, key: str, message: str, **details: Any):
        super().__init__(message)
        self.key = key
        self.details = details


def _bounded_number(value: Any, low: float, high: float, fallback: float) -> float:
    """Clamp a numeric setting into its accepted range, falling back when unusable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if number != number:  # NaN
        return float(fallback)
    return max(low, min(high, number))


def _bounded_int(value: Any, low: int, high: int, fallback: int) -> int:
    """Clamp an integer setting into its accepted range, falling back when unusable."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return int(fallback)
    return max(low, min(high, number))


def _reject_locked_agent_keys(body: dict[str, Any]) -> None:
    """Refuse a change to a secret or to the agent's own permission switches."""
    for key in body:
        if key in LOCKED_AGENT_KEYS:
            raise SettingsUpdateError(
                "agent_setting_locked",
                f"The AI cannot change \"{key}\": it holds a secret or controls tool permissions. "
                "Change it on the Settings page.",
                field=key,
            )
        if key not in AGENT_SETTING_KEYS:
            raise SettingsUpdateError(
                "agent_setting_unknown",
                f"Unknown setting \"{key}\". Read get_settings for the names it may change.",
                field=key,
            )


def apply_settings_payload(
    current: dict[str, Any],
    body: dict[str, Any],
    *,
    allow_secrets: bool = True,
    agent: bool = False,
) -> dict[str, Any]:
    """Merge one settings update into *current* and return the normalized result.

    The caller owns the save so it can keep ``SETTINGS_LOCK``, sync the Discord
    bot and clear the provider status cache around it. Raises
    :class:`SettingsUpdateError` for a value that must not be stored.
    """
    if not isinstance(body, dict):
        raise SettingsUpdateError("invalid_body", "The settings payload must be a JSON object")
    if agent:
        _reject_locked_agent_keys(body)
    previous_provider = normalize_provider(current.get("provider"))
    previous_base_url = current.get("base_url")
    previous_memory = current.get("memory") if isinstance(current.get("memory"), dict) else {}
    previous_memory_base_url = previous_memory.get("base_url")
    for key in ALLOWED_SETTING_KEYS:
        if key in body:
            current[key] = body[key]
    if MASK[:2] in str(current.get("base_url") or ""):
        # /api/settings masks credentials inside the Base URL, so a value that
        # still carries the mask means "keep the stored URL".
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
        raise SettingsUpdateError(
            "discord_ids_invalid",
            "Discord IDs must be numbers only: " + ", ".join((invalid_users + invalid_channels)[:5]),
            ids=", ".join((invalid_users + invalid_channels)[:5]),
        )
    current["discord_allowed_users"] = allowed_users
    current["discord_allowed_channels"] = allowed_channels
    current["machine_access"] = bool(current.get("machine_access", True))
    current["update"] = normalize_update_settings(current.get("update"))
    current["temperature"] = _bounded_number(
        current.get("temperature"), 0.0, 2.0, DEFAULT_SETTINGS["temperature"]
    )
    current["top_p"] = _bounded_number(current.get("top_p"), 0.0, 1.0, DEFAULT_SETTINGS["top_p"])
    current["max_tokens"] = _bounded_int(
        current.get("max_tokens"), 1, 200_000, DEFAULT_SETTINGS["max_tokens"]
    )
    raw_skills = current.get("skills")
    available_skill_names = {item["name"] for item in list_skills()}
    current["skills"] = [
        str(name)
        for name in (raw_skills if isinstance(raw_skills, list) else [])
        if str(name) in available_skill_names
    ]
    if allow_secrets:
        discord_token = body.get("discord_token")
        if isinstance(discord_token, str) and discord_token.strip() and discord_token != MASK:
            current["discord_token"] = discord_token.strip()
        new_key = body.get("api_key")
        if isinstance(new_key, str) and new_key.strip() and new_key != MASK:
            keys = stored_api_keys(current)
            keys[current["provider"]] = new_key.strip()
            current["api_keys"] = keys
        custom_key = body.get("custom_api_key")
        if isinstance(custom_key, dict):
            try:
                custom_name = normalize_custom_key_name(custom_key.get("name"))
            except ValueError as exc:
                raise SettingsUpdateError(
                    "custom_key_name_invalid", "Invalid Custom API key name"
                ) from exc
            custom_value = custom_key.get("value")
            if isinstance(custom_value, str) and "\x00" in custom_value:
                raise SettingsUpdateError(
                    "custom_key_nul", "A Custom API key value must not contain NUL characters"
                )
            if isinstance(custom_value, str) and custom_value.strip() and custom_value.strip() != MASK:
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
    memory_update = current.get("memory")
    if isinstance(memory_update, dict) and MASK[:2] in str(memory_update.get("base_url") or ""):
        # The memory Base URL is masked the same way, so the mask keeps the
        # stored endpoint instead of overwriting it.
        current["memory"] = {**memory_update, "base_url": previous_memory_base_url}
    try:
        current["memory"] = memory_engine.normalize_settings(current.get("memory"))
    except ValueError as exc:
        raise SettingsUpdateError(
            "memory_schedule_invalid", "The memory cron expression is invalid"
        ) from exc
    return current


def settings_snapshot(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the settings with every credential replaced by a safe marker.

    The agent needs to see what it is about to change; it never needs a key, so
    the snapshot reports presence (``has_api_key``, ``has_discord_token``) and
    the custom key names instead of their values, and masks credentials inside
    both Base URLs.
    """
    settings = load_settings() if settings is None else settings
    snapshot = {key: value for key, value in settings.items() if key not in SECRET_SETTING_KEYS}
    snapshot["base_url"] = mask_url_credentials(snapshot.get("base_url"))
    memory = snapshot.get("memory")
    if isinstance(memory, dict):
        snapshot["memory"] = {**memory, "base_url": mask_url_credentials(memory.get("base_url"))}
    provider = normalize_provider(settings.get("provider"))
    snapshot["provider"] = provider
    snapshot["has_api_key"] = bool(stored_api_keys(settings).get(provider))
    snapshot["custom_api_keys"] = sorted(stored_custom_api_keys(settings))
    snapshot["has_discord_token"] = bool(
        str(settings.get("discord_token") or "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )
    return snapshot


def apply_agent_settings(body: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Save an update the AI requested and return the settings plus changed keys.

    The permission switches and the stored secrets are rejected before anything
    is written, so a failed call leaves the settings untouched.
    """
    with SETTINGS_LOCK:
        current = load_settings()
        # apply_settings_payload() merges into the dict it is given, so the
        # comparison snapshot is copied before the update runs.
        before = {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in current.items()
        }
        updated = apply_settings_payload(current, body, allow_secrets=False, agent=True)
        save_settings(updated)
    STATUS_CACHE.clear()
    # A key the normalization adds with an empty value (skills: []) was not a
    # change the caller asked for, so it is left out of the report.
    changed = sorted(
        key
        for key in set(before) | set(updated)
        if before.get(key) != updated.get(key) and (key in before or updated.get(key))
    )
    return updated, changed
