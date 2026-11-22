"""Settings storage, provider metadata and the secret list.

Settings are one JSON file, written atomically. A save also drops the model-id
cache, which has its own module so this one stays free of the provider layer.
"""

import json
import os
import re
import threading
import uuid
from typing import Any

import memory_engine

from core.config import SENSITIVE_ENV_PARTS, SETTINGS_FILE
from core.model_cache import forget_model_names

DEFAULT_SETTINGS = {
    "memory": memory_engine.DEFAULT_MEMORY_SETTINGS.copy(),
    "agent_name": "Mux",
    "agent_role": "A versatile AI assistant",
    "response_language": "auto",
    "response_style": "Friendly, concise, and clear",
    "use_markdown": True,
    "ask_clarifying_questions": True,
    "provider": os.getenv("AI_PROVIDER", "openai"),
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "base_url": os.getenv("AI_BASE_URL", ""),
    "system_prompt": "You are a polite, clear AI assistant who helps the user achieve their goals.",
    "memory_review": (
        "Before answering, review the earlier conversation to keep continuity, check facts and "
        "outstanding tasks, and ask the user when information conflicts. Do not reveal internal reasoning."
    ),
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 1,
    "stream": False,
    "thinking_level": "off",
    "command_mode": "ask",
    "fallback_enabled": False,
    "fallback_provider": os.getenv("AI_FALLBACK_PROVIDER", "openai"),
    "fallback_model": os.getenv("AI_FALLBACK_MODEL", ""),
    "gemini_live_model": os.getenv("GEMINI_LIVE_MODEL", ""),
    "gemini_agent": os.getenv("GEMINI_AGENT", ""),
    "gemini_decision_model": os.getenv("GEMINI_DECISION_MODEL", ""),
    "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN", "").strip()),
    "discord_prefix": os.getenv("DISCORD_BOT_PREFIX", "!ai"),
    "discord_allowed_users": [
        item.strip() for item in os.getenv("DISCORD_ALLOWED_USER_IDS", "").split(",") if item.strip()
    ],
    "discord_allowed_channels": [
        item.strip() for item in os.getenv("DISCORD_ALLOWED_CHANNEL_IDS", "").split(",") if item.strip()
    ],
    "machine_access": True,
    "custom_api_keys": {},
}
PROVIDERS = ("openai", "gemini", "anthropic", "hf", "or", "groq")
PROVIDER_LABELS = {"openai": "OpenAI", "gemini": "Gemini", "anthropic": "Anthropic", "hf": "Hugging Face", "or": "OpenRouter", "groq": "Groq"}
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "hf": "HF_API_KEY",
    "or": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
}
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "anthropic": "https://api.anthropic.com/v1",
    "hf": "https://router.huggingface.co/v1",
    "or": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}
SETTINGS_LOCK = threading.Lock()


def normalize_provider(value: Any) -> str:
    """Clamp an unknown provider name to a supported provider id."""
    provider = str(value or "openai").strip().lower()
    return provider if provider in PROVIDERS else "openai"


def parse_discord_ids(value: Any, limit: int = 100) -> tuple[list[str], list[str]]:
    """Split a Discord allowlist input into unique numeric IDs and bad entries.

    Accepts a comma/space separated string or a list, because the settings API
    accepts both the web form input and a JSON array. Invalid entries are
    reported instead of dropped so a typo cannot silently empty the allowlist.
    """
    if isinstance(value, str):
        raw_items: list[Any] = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    ids: list[str] = []
    invalid: list[str] = []
    for item in raw_items:
        item = str(item).strip()
        if not item:
            continue
        if not item.isdigit():
            invalid.append(item[:40])
            continue
        if item not in ids and len(ids) < limit:
            ids.append(item)
    return ids, invalid


def normalize_discord_ids(value: Any, limit: int = 100) -> list[str]:
    """Normalize a stored Discord allowlist into unique numeric IDs."""
    return parse_discord_ids(value, limit)[0]


def discord_access_allowed(settings: dict[str, Any], channel_id: Any, user_id: Any) -> bool:
    """Return whether a Discord channel/user pair passes the allowlists.

    An empty allowlist means "no restriction", so existing installs keep
    working after the upgrade.
    """
    allowed_channels = normalize_discord_ids(settings.get("discord_allowed_channels"))
    allowed_users = normalize_discord_ids(settings.get("discord_allowed_users"))
    if allowed_channels and str(channel_id) not in allowed_channels:
        return False
    if allowed_users and str(user_id) not in allowed_users:
        return False
    return True


def stored_api_keys(settings: dict[str, Any]) -> dict[str, str]:
    """Return the per-provider API key map from settings."""
    raw = settings.get("api_keys")
    keys = raw if isinstance(raw, dict) else {}
    return {provider: str(keys.get(provider) or "").strip() for provider in PROVIDERS}
CUSTOM_KEY_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def normalize_custom_key_name(value: Any) -> str:
    """Validate a user-chosen name for an extra API key (used as an env var)."""
    name = re.sub(r"[\s-]+", "_", str(value or "").strip()).upper()
    if not CUSTOM_KEY_NAME_PATTERN.fullmatch(name):
        raise ValueError("The key name must start with A-Z and use only A-Z, 0-9 and _ (64 characters max)")
    return name


def stored_custom_api_keys(settings: dict[str, Any]) -> dict[str, str]:
    """Return the extra named API keys, dropping invalid or empty entries."""
    raw = settings.get("custom_api_keys")
    if not isinstance(raw, dict):
        return {}
    keys: dict[str, str] = {}
    for name, value in raw.items():
        try:
            valid_name = normalize_custom_key_name(name)
        except ValueError:
            continue
        text = str(value or "").strip()
        if text:
            keys[valid_name] = text
    return keys


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
    """Load settings from disk, falling back to defaults on error."""
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    settings = migrate_legacy_api_key(settings)
    settings.pop("terminal_enabled", None)
    settings["custom_api_keys"] = stored_custom_api_keys(settings)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """Write the current settings atomically so readers never see a partial file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = SETTINGS_FILE.with_name(f".{SETTINGS_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        payload = json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8")
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temp_path, SETTINGS_FILE)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    # A changed API key or base URL can change the model list, so drop the cached
    # ids Discord autocomplete answers from.
    forget_model_names()


def get_discord_token(settings: dict[str, Any] | None = None) -> str:
    """Return the Discord bot token from settings or the environment."""
    settings = settings if settings is not None else load_settings()
    configured = str(settings.get("discord_token") or "").strip()
    return configured or os.getenv("DISCORD_BOT_TOKEN", "").strip()


def secret_values(extra: list[str] | None = None) -> list[str]:
    """Collect secret values that command output and logs must never expose."""
    settings = load_settings()
    values = {value for value in stored_api_keys(settings).values() if value}
    values.update(stored_custom_api_keys(settings).values())
    if extra:
        values.update(value for value in extra if value)
    discord_token = get_discord_token(settings)
    if discord_token:
        values.add(discord_token)
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(part in name.upper() for part in SENSITIVE_ENV_PARTS):
            values.add(value)
    return sorted(values, key=len, reverse=True)
