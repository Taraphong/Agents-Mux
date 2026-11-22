"""Environment-variable parsing helpers."""

import os


def env_int(name: str, default: int, minimum: int) -> int:
    """Read an integer environment variable, clamping invalid input to safe bounds."""
    try:
        value = int(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)
