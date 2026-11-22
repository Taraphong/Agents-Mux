"""The route modules import a large shared surface from ``app``.

Moving a definition out of app.py is only safe while every name these modules
import still resolves, so this test reads their import lists and checks them
against the live module.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTE_MODULES = ("index_routes.py", "pair_routes.py")


def _names_imported_from_app(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            names.extend(alias.name for alias in node.names)
    return names


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("AI_WEB_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    import app

    return app


@pytest.mark.parametrize("module_file", ROUTE_MODULES)
def test_every_imported_name_still_exists(app_module, module_file):
    names = _names_imported_from_app(PROJECT_ROOT / module_file)
    assert names, f"{module_file} should import shared names from app"
    missing = [name for name in names if not hasattr(app_module, name)]
    assert not missing, f"{module_file} imports missing names from app: {missing}"
