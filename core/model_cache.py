"""The model-id cache shared by autocomplete and settings saving.

It lives in its own module so ``core.settings`` can drop the cache after a save
without importing the provider layer, which imports settings in turn.
"""

import threading
import time

MODEL_LIST_CACHE_TTL = 600
MODEL_LIST_CACHE: dict[str, tuple[float, list[str]]] = {}
MODEL_LIST_REFRESH_LOCK = threading.Lock()
MODEL_LIST_REFRESH_STARTED: dict[str, float] = {}


def remember_model_names(provider: str, names: list[str]) -> None:
    """Cache a provider's model ids so Discord autocomplete can answer instantly."""
    # Imported here: core.settings imports this module for forget_model_names().
    from core.settings import normalize_provider

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
