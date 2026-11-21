"""Shared fixtures for the memory-engine tests.

The engine reads its storage paths from the environment at import time, so each
test points the AI_WEB_MEMORY_* variables at its own temporary folder and then
reloads the module. That keeps every test's vault, database and history folder
separate without touching the real memory files.
"""

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """Return a freshly loaded memory_engine with empty temporary storage."""
    monkeypatch.setenv("AI_WEB_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("AI_WEB_MEMORY_FILE", str(tmp_path / "MEMORY.md"))
    monkeypatch.setenv("AI_WEB_DREAMS_FILE", str(tmp_path / "DREAMS.md"))
    monkeypatch.setenv("AI_WEB_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AI_WEB_HISTORY_DIR", str(tmp_path / "history"))
    # Never depend on a vec0 build that happens to be installed on this machine.
    monkeypatch.setenv("AI_WEB_MEMORY_VEC_EXT", str(tmp_path / "missing-vec0.so"))
    for name in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HF_API_KEY",
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    import memory_engine

    module = importlib.reload(memory_engine)
    module.ensure_storage()
    yield module
