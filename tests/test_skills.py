"""Guards and catalog metadata for the skill folders.

``core.skills`` resolves the skills root at import time. Instead of reloading the
module (which would leave the rest of the process on a stale path), the tests
point the two module-level constants at a temporary folder.
"""

import os
import stat
from pathlib import Path

import pytest


@pytest.fixture()
def skills(tmp_path, monkeypatch):
    """Return core.skills with its skills root moved into a temporary folder."""
    from core import skills as module

    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(module, "SKILLS_ROOT", root)
    monkeypatch.setattr(module, "SKILLS_ROOT_TEXT", os.path.normpath(os.path.realpath(str(root))))
    return module


def skills_root(skills) -> Path:
    return (skills.PROJECT_ROOT / skills.SKILLS_ROOT).resolve()


def write_skill(skills, name: str, content: str) -> Path:
    directory = skills_root(skills) / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    return directory


def test_skill_dir_rejects_names_without_a_usable_folder(skills):
    for name in ("", "   ", ".", "..", "...", "/", "---"):
        with pytest.raises(ValueError):
            skills.skill_dir(name)


def test_skill_dir_flattens_traversal_names_instead_of_escaping(skills):
    root = skills_root(skills)
    for name in ("../evil", "/etc/passwd", "other/file", "..hidden.."):
        directory = skills.skill_dir(name)
        assert directory.parent == root


def test_write_skill_file_refuses_a_folder_outside_the_skills_root(skills, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(PermissionError):
        skills._write_skill_file(outside, "scripts/run.sh", "echo hi\n")
    assert not (outside / "scripts").exists()


def test_write_skill_file_refuses_paths_that_leave_the_skill_folder(skills):
    directory = skills.skill_dir("demo")
    for relative in ("../evil.md", "scripts/../../evil.md", "/etc/passwd", "notes/run.md", ""):
        with pytest.raises(ValueError):
            skills._write_skill_file(directory, relative, "x")


def test_save_skill_keeps_resources_in_the_folder_and_marks_scripts(skills):
    saved = skills.save_skill(
        "demo",
        "Use when a demo is needed",
        "## Guidelines\n\nDo the demo.",
        {"scripts/run.sh": "echo hi\n", "references/notes.md": "# Notes\n"},
    )
    directory = skills_root(skills) / "demo"
    script = directory / "scripts" / "run.sh"
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert (directory / "references" / "notes.md").is_file()
    assert saved["files"] == ["scripts/run.sh", "references/notes.md"]
    assert saved["description"] == "Use when a demo is needed"


def test_save_skill_refuses_resources_outside_the_folder(skills):
    with pytest.raises(ValueError):
        skills.save_skill("demo", "A demo", "# Demo", {"../evil.md": "x"})
    assert not (skills_root(skills) / "evil.md").exists()


def test_skill_info_describes_a_skill_without_frontmatter(skills):
    write_skill(skills, "legacy", "# Legacy skill\n\nExplains the legacy workflow.\n\nMore text.")
    info = skills.skill_info(skills_root(skills) / "legacy")
    assert info["description"] == "Explains the legacy workflow."


def test_skill_info_prefers_the_frontmatter_description(skills):
    write_skill(
        skills,
        "modern",
        '---\nname: modern\ndescription: "Modern workflow"\n---\n\nBody text.\n',
    )
    assert skills.skill_info(skills_root(skills) / "modern")["description"] == "Modern workflow"


def test_list_skills_describes_legacy_folders(skills):
    write_skill(skills, "legacy", "# Legacy\n\nLegacy workflow.\n")
    write_skill(skills, "empty", "# Empty\n\n## Guidelines\n")
    items = {item["name"]: item["description"] for item in skills.list_skills()}
    assert items == {"legacy": "Legacy workflow.", "empty": ""}


def test_a_null_description_falls_back_instead_of_becoming_none(skills):
    saved = skills.save_skill("demo", None, "# Demo\n\nWhen the demo runs.")
    assert saved["description"] == "When the demo runs."
    document = (skills_root(skills) / "demo" / "SKILL.md").read_text(encoding="utf-8")
    assert "None" not in document


def test_save_skill_rejects_a_description_that_is_not_text(skills):
    for description in ({"text": "a description"}, ["a description"], 7, True):
        with pytest.raises(ValueError):
            skills.save_skill("demo", description, "# Demo\n\nBody.")
    assert not (skills_root(skills) / "demo").exists()


def test_skill_document_rejects_a_description_that_is_not_text(skills):
    for description in ({"text": "a description"}, ["a description"], 7):
        with pytest.raises(ValueError):
            skills.skill_document("demo", description, "# Demo\n\nBody.")


def test_skill_document_keeps_the_other_frontmatter_keys():
    from core.skills import parse_skill_frontmatter, skill_document

    document = skill_document(
        "demo",
        "A demo",
        '---\nname: old-name\ndescription: "Old"\nlicense: MIT\nallowed-tools: Read, Write\n---\n\n# Demo\n',
    )
    meta, body = parse_skill_frontmatter(document)
    assert meta["name"] == "demo"
    assert meta["description"] == "A demo"
    assert meta["license"] == "MIT"
    assert meta["allowed-tools"] == "Read, Write"
    assert list(meta) == ["name", "description", "license", "allowed-tools"]
    assert body == "# Demo"


def test_skill_document_keeps_a_key_whose_value_has_quotes():
    from core.skills import parse_skill_frontmatter, skill_document

    document = skill_document(
        "demo",
        "",
        '---\ndescription: "A demo"\nnotes: He said "hi" there\n---\n\nBody.\n',
    )
    meta, _body = parse_skill_frontmatter(document)
    assert meta["notes"] == 'He said "hi" there'


def test_save_skill_keeps_the_other_frontmatter_keys(skills):
    saved = skills.save_skill(
        "demo",
        "",
        '---\nlicense: MIT\nallowed-tools: Read\n---\n\n# Demo\n\nBody.\n',
    )
    document = (skills_root(skills) / "demo" / "SKILL.md").read_text(encoding="utf-8")
    meta, _body = skills.parse_skill_frontmatter(document)
    assert meta["license"] == "MIT"
    assert meta["allowed-tools"] == "Read"
    assert saved["description"] == "Body."


def test_a_null_description_keeps_the_submitted_frontmatter(skills):
    saved = skills.save_skill(
        "demo",
        None,
        '---\nname: demo\ndescription: "Kept description"\n---\n\nBody.\n',
    )
    assert saved["description"] == "Kept description"
