"""Import-time layering between the provider layer and the memory engine.

``core.providers`` is the lower layer: the engine asks it for a completion and
prompt assembly lives in ``core.prompts``. Providers must therefore never import
``memory_engine`` back, and the module-level import graph must stay acyclic so a
fresh interpreter can import any entry module first.
"""

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("core", "services", "routes")


def module_files():
    """Yield (module name, path) for every module in the import graph."""
    yield "app", PROJECT_ROOT / "app.py"
    yield "memory_engine", PROJECT_ROOT / "memory_engine.py"
    for package in PACKAGES:
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            if path.name == "__init__.py":
                name = package
            else:
                name = f"{package}." + ".".join(path.relative_to(PROJECT_ROOT / package).with_suffix("").parts)
            yield name, path


def imported_names(path):
    """Return every module name imported anywhere in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def module_level_edges(path, modules):
    """Return the modules imported while the file itself is loading."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    edges = set()
    for name in names:
        if name in modules:
            edges.add(name)
        elif name.split(".")[0] in modules:
            edges.add(name.split(".")[0])
    return edges


def find_cycle(graph):
    """Return one module cycle as a list, or None when the graph is acyclic."""
    state = {}

    def visit(node, stack):
        state[node] = 1
        stack.append(node)
        for neighbour in graph[node]:
            if state.get(neighbour) == 1:
                return stack[stack.index(neighbour):] + [neighbour]
            if not state.get(neighbour):
                found = visit(neighbour, stack)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if not state.get(node):
            found = visit(node, [])
            if found:
                return found
    return None


def test_providers_never_import_the_memory_engine():
    imports = set(imported_names(PROJECT_ROOT / "core" / "providers.py"))
    assert "memory_engine" not in imports


def test_each_entry_module_imports_in_a_fresh_interpreter():
    for statement in ("import memory_engine", "import core.providers", "import core.prompts"):
        result = subprocess.run(
            [sys.executable, "-c", statement],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{statement} failed:\n{result.stderr}"


def test_module_level_imports_are_acyclic():
    modules = dict(module_files())
    graph = {name: module_level_edges(path, modules) for name, path in modules.items()}
    cycle = find_cycle(graph)
    assert cycle is None, "module-level import cycle: " + " -> ".join(cycle or [])
