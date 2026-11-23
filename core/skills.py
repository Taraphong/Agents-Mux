"""Skill folders: SKILL.md metadata, resource files and prompt assembly.

A skill is a folder under the skills root:

    <skill>/
    ├── SKILL.md      required: YAML frontmatter plus the instructions
    ├── scripts/      optional runnable code
    ├── references/   optional documentation to read on demand
    └── assets/       optional templates and images

Only the metadata (``name`` and ``description`` from the frontmatter) is loaded
for the catalog, so the model can choose a skill without paying for every
SKILL.md. The full SKILL.md is loaded for the skills selected in Settings or
invoked with ``/``, and the files in scripts/, references/ and assets/ are read
only when a workflow step needs them (progressive disclosure).
"""

import os
import re
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT, SKILLS_ROOT, TOOL_MAX_WRITE_BYTES
from core.paths import normalized_path_under

SKILL_FILE = "SKILL.md"
SKILL_RESOURCE_FOLDERS = ("scripts", "references", "assets")
SKILL_CONTENT_LIMIT = 20_000
SKILL_DESCRIPTION_LIMIT = 600


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


def parse_skill_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into its YAML frontmatter values and its body.

    Only the flat ``key: value`` form the skill format uses is read (plus the
    ``>``/``|`` block scalars), so no YAML dependency is needed on Termux.
    """
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return {}, text.strip("\n")
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text.strip("\n")
    header = text[4:end]
    body = text[end + 4:]
    body = body[1:] if body.startswith("\n") else body
    meta: dict[str, str] = {}
    lines = header.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if value in {">", "|", ">-", "|-", ">+", "|+"}:
            collected = []
            while index < len(lines) and (not lines[index].strip() or lines[index][:1] in {" ", "\t"}):
                collected.append(lines[index].strip())
                index += 1
            value = " ".join(part for part in collected if part)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            meta[key] = value
    return meta, body.strip("\n")


def _one_line(text: Any, limit: int = SKILL_DESCRIPTION_LIMIT) -> str:
    """Collapse whitespace so a value can sit on one frontmatter line."""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def skill_description(content: str) -> str:
    """Return a skill description, falling back to the first body paragraph."""
    meta, body = parse_skill_frontmatter(content)
    description = _one_line(meta.get("description"))
    if description:
        return description
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        return _one_line(line)
    return ""


def skill_files(directory: Path) -> list[str]:
    """List the resource files a skill ships, as paths relative to its folder."""
    items: list[str] = []
    for folder in SKILL_RESOURCE_FOLDERS:
        base = Path(directory) / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(directory)
            if not path.is_file() or any(part.startswith(".") for part in relative.parts):
                continue
            items.append(relative.as_posix())
    return items


def skill_info(directory: Path) -> dict[str, Any]:
    """Read one skill folder's catalog entry: name, description and resources."""
    content = (Path(directory) / SKILL_FILE).read_text(encoding="utf-8")[:SKILL_CONTENT_LIMIT]
    meta, _body = parse_skill_frontmatter(content)
    return {
        "name": Path(directory).name,
        "description": _one_line(meta.get("description")),
        "files": skill_files(Path(directory)),
    }


def list_skills() -> list[dict[str, Any]]:
    """Load every skill folder's metadata only, without its SKILL.md body."""
    root = (PROJECT_ROOT / SKILLS_ROOT).resolve()
    if not root.exists():
        return []
    items = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        if not (directory / SKILL_FILE).is_file():
            continue
        try:
            items.append(skill_info(directory))
        except OSError:
            continue
    return items


def read_skill(name: str) -> dict[str, Any]:
    """Return one skill's full SKILL.md content next to its catalog metadata."""
    path = skill_path(name)
    if not path.is_file():
        raise FileNotFoundError("Skill not found")
    info = skill_info(path.parent)
    info["content"] = path.read_text(encoding="utf-8")[:SKILL_CONTENT_LIMIT]
    return info


def skill_document(name: str, description: str, content: str) -> str:
    """Build a SKILL.md with a frontmatter carrying the name and description."""
    meta, body = parse_skill_frontmatter(content)
    final_description = (
        _one_line(description)
        or _one_line(meta.get("description"))
        or skill_description(content)
    )
    if not final_description:
        raise ValueError("A skill needs a description of when to use it")
    body = body.strip()
    if not body:
        raise ValueError("The skill content is empty")
    quoted = final_description.replace('"', "'")
    return f'---\nname: {name}\ndescription: "{quoted}"\n---\n\n{body}\n'


def _write_skill_file(directory: Path, relative_path: str, content: Any) -> str:
    """Write one resource file, keeping it inside scripts/, references/ or assets/."""
    if not isinstance(content, str):
        raise ValueError("Skill resource contents must be text")
    if len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
        raise ValueError("A skill resource is larger than allowed")
    relative = str(relative_path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in relative.split("/") if part not in {"", "."}]
    if not parts or ".." in parts or parts[0] not in SKILL_RESOURCE_FOLDERS:
        raise ValueError("Skill resources must live in scripts/, references/ or assets/")
    root_text = os.path.normpath(os.path.realpath(str(directory)))
    target_text = os.path.normpath(os.path.realpath(os.path.join(root_text, *parts)))
    if not target_text.startswith(root_text + os.sep):
        raise PermissionError("The skill resource path is outside the allowed folder")
    path = Path(target_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if parts[0] == "scripts" and path.suffix in {".sh", ".py"}:
        path.chmod(0o755)
    return "/".join(parts)


def save_skill(
    name: str,
    description: str = "",
    content: str = "",
    files: Any = None,
) -> dict[str, Any]:
    """Create or replace a skill folder's SKILL.md and optional resources."""
    directory = skill_dir(name)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The skill content is empty")
    if len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
        raise ValueError("The skill content is larger than allowed")
    if files is not None and not isinstance(files, dict):
        raise ValueError("Skill resources must be an object of path to content")
    document = skill_document(directory.name, description, content)
    root_text = os.path.normpath(os.path.realpath(str(PROJECT_ROOT / SKILLS_ROOT)))
    target_text = os.path.normpath(os.path.realpath(str(directory / SKILL_FILE)))
    if not target_text.startswith(root_text + os.sep):
        raise PermissionError("The skill path is outside the allowed folder")
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for relative_path, file_content in (files or {}).items():
        written.append(_write_skill_file(directory, str(relative_path), file_content))
    path = Path(target_text)
    path.write_text(document, encoding="utf-8")
    meta, _body = parse_skill_frontmatter(document)
    return {
        "name": directory.name,
        "description": _one_line(meta.get("description")),
        "files": skill_files(directory),
        "written": written,
    }


def skills_prompt(settings: dict[str, Any]) -> str:
    """Build the skills block: every skill's metadata, selected ones in full."""
    items = list_skills()
    if not items:
        return ""
    catalog = "\n".join(
        f"- `{item['name']}`: {item['description'] or 'No description'}" for item in items
    )
    parts = [
        "## Skills",
        (
            "Skill metadata is listed first so you can pick the right one. The full SKILL.md "
            "is loaded only for the skills selected or invoked below; open a skill's "
            "scripts/, references/ or assets/ files only when a workflow step needs them."
        ),
        catalog,
    ]
    selected = settings.get("skills", [])
    if not isinstance(selected, list):
        selected = []
    blocks = []
    for name in selected:
        try:
            info = read_skill(str(name))
        except (OSError, ValueError):
            continue
        block = f"### Skill: {info['name']}\n{info['content'].strip()}"
        if info["files"]:
            block += "\n\nSkill resources (read only when needed): " + ", ".join(info["files"])
        blocks.append(block)
    if blocks:
        parts.append("Guidance from the selected Skills:\n\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)
