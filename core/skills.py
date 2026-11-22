"""Skill folders and their SKILL.md entrypoints.

A skill is a folder under the skills root holding SKILL.md; the folder name is
sanitized so a skill can never point outside that root.
"""

import re
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT, SKILLS_ROOT
from core.paths import normalized_path_under


def skill_dir(name: str) -> Path:
    """Resolve a skill name to its directory inside the skills root."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name).strip().lower()).strip("-")
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Invalid skill name")
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    directory = normalized_path_under(safe_name, root, "Skill name is outside the allowed folder")
    if directory.parent != root:
        raise ValueError("Skill name is outside the allowed folder")
    return directory


def skill_path(name: str) -> Path:
    """Return the canonical Agent Skills entrypoint: <skill>/SKILL.md."""
    return skill_dir(name) / "SKILL.md"


def list_skills() -> list[dict[str, str]]:
    """Load every skill folder that contains a SKILL.md entrypoint."""
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    if not root.exists():
        return []
    items = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        path = directory / "SKILL.md"
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")[:20_000]
        except OSError:
            continue
        items.append({"name": directory.name, "content": content})
    return items


def selected_skill_prompt(settings: dict[str, Any]) -> str:
    """Build the skill guidance block for the skills selected in settings."""
    selected = settings.get("skills", [])
    if not isinstance(selected, list):
        return ""
    by_name = {item["name"]: item["content"] for item in list_skills()}
    blocks = [f"## Skill: {name}\n{by_name[name]}" for name in selected if name in by_name]
    return "Guidance from the selected Skills:\n\n" + "\n\n".join(blocks) if blocks else ""
