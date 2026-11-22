"""The extracted packages must not import ``app``.

``app`` is the assembly point: it imports from ``core`` and ``services``, never
the other way around. A reverse import would create a cycle and pull the whole
Flask application into pure helpers, so this test fails on one.
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("core", "services", "routes")


def _imports_app(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "app" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            return True
    return False


def test_extracted_packages_do_not_import_app():
    offenders: list[str] = []
    for package in PACKAGES:
        directory = PROJECT_ROOT / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if _imports_app(path):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, f"these modules import app: {offenders}"
