"""Model providers: readiness, discovery and chat calls.

Every HTTP endpoint is checked before a key is sent, model ids are cached for
autocomplete, and each provider's request/response shape lives beside its
siblings. It logs through core.log directly.
"""

import base64
import ipaddress
import os
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

import memory_engine

from core.config import TOOL_INSTRUCTIONS
from core.log import log_event
from core.model_cache import (
    MODEL_LIST_CACHE,
    MODEL_LIST_CACHE_TTL,
    MODEL_LIST_ERROR_LOGGED,
    MODEL_LIST_REFRESH_INTERVAL,
    MODEL_LIST_REFRESH_LOCK,
    MODEL_LIST_REFRESH_STARTED,
    MODEL_LIST_REFRESH_TIMEOUT,
    remember_model_names,
)
from core.messages import status_message
from core.settings import (
    PROVIDER_BASE_URLS,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABELS,
    load_settings,
    normalize_provider,
    stored_api_keys,
)
from core.skills import selected_skill_prompt


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
