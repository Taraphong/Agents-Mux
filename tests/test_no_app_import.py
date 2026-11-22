"""Implementation modules must not import ``app``.

``app`` is the assembly point: it imports from ``core``, ``services`` and
``routes``, never the other way around. A reverse import would create a cycle
and pull the whole Flask application into pure helpers, so this test fails on
one. ``memory_engine`` imports core modules directly but must not reach back
into the application object either.
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("core", "services", "routes")
ROOT_MODULES = ("memory_engine.py",)


def _imports_app(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "app" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            return True
    return False


def test_implementation_modules_do_not_import_app():
    offenders: list[str] = []
    for package in PACKAGES:
        directory = PROJECT_ROOT / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if _imports_app(path):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    for module in ROOT_MODULES:
        if _imports_app(PROJECT_ROOT / module):
            offenders.append(module)
    assert not offenders, f"these modules import app: {offenders}"
