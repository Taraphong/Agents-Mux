"""app.py is the assembly point, not a helper module.

The blueprints import their helpers from ``core``, ``services`` and
``routes.shared``; memory_engine keeps a few lazy ``import app`` calls, so the
attributes it reads stay pinned here.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTE_MODULES = ("routes/index.py", "routes/pair.py")
# Attributes memory_engine reads through its lazy `import app`.
MEMORY_ENGINE_SURFACE = (
    "cron_matches",
    "endpoint_is_loopback",
    "get_base_url",
    "key_is_configured",
    "load_settings",
    "normalize_provider",
    "redact_secrets",
    "secret_values",
)


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    import app

    return app


@pytest.mark.parametrize("module_file", ROUTE_MODULES)
def test_route_modules_do_not_import_app(module_file):
    tree = ast.parse((PROJECT_ROOT / module_file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "app" for alias in node.names):
            pytest.fail(f"{module_file} imports app")
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            pytest.fail(f"{module_file} imports from app")


def test_app_still_exposes_the_memory_engine_surface(app_module):
    missing = [name for name in MEMORY_ENGINE_SURFACE if not hasattr(app_module, name)]
    assert not missing, f"memory_engine imports missing names from app: {missing}"
