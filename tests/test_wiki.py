"""The personal llm-wiki vault is seeded once and never overwrites notes."""

from core.wiki import WIKI_DIRECTORIES, WIKI_FILES, ensure_wiki


def test_ensure_wiki_creates_structure(tmp_path):
    root = ensure_wiki(tmp_path / "llm-wiki")

    assert root.is_dir()
    for name in WIKI_DIRECTORIES:
        assert (root / name).is_dir()
    for relative in WIKI_FILES:
        assert (root / relative).is_file()

    index = (root / "index.md").read_text(encoding="utf-8")
    assert "AGENTS" in index
    assert "inbox/" in index


def test_ensure_wiki_never_overwrites_a_note(tmp_path):
    root = ensure_wiki(tmp_path)
    note = root / "notes" / "my-note.md"
    note.write_text("my knowledge", encoding="utf-8")
    (root / "index.md").write_text("edited index", encoding="utf-8")

    ensure_wiki(root)

    assert note.read_text(encoding="utf-8") == "my knowledge"
    assert (root / "index.md").read_text(encoding="utf-8") == "edited index"


def test_seed_has_rules_and_templates(tmp_path):
    root = ensure_wiki(tmp_path)

    guide = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Never write API keys" in guide
    assert "[[note-name]]" in guide
    for template in ("note.md", "project.md", "daily.md"):
        assert (root / "templates" / template).is_file()
