"""Editing a conversation's first question renames the chat.

The title of a conversation comes from its first question, so an edited first
question must rename it with the same summary call a new chat uses. The real
page functions (refreshTitleAfterPromptEdit, requestGeneratedTitle,
applyGeneratedTitle) are run by ``tests/edit_title_harness.js`` against a
DOM/fetch stub; this test only starts it and checks how saveMessageEdit wires
the rename to an edited first question.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = ROOT / "templates" / "index" / "index.js"
HARNESS = ROOT / "tests" / "edit_title_harness.js"
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def summary():
    if NODE is None:
        pytest.skip("node runs the page script")
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(ROOT),
        env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_edited_question_renames_the_chat(summary):
    assert summary["ok"] is True, summary
    assert summary["requests"] >= 4
    # A summary, plus the two fallbacks to the edited question; a manual rename
    # and an unsaved chat rename nothing.
    assert summary["patches"] == 3


def test_only_an_edited_first_question_renames_the_chat():
    src = INDEX_JS.read_text(encoding="utf-8")

    save = src[src.index("async function saveMessageEdit(") :]
    save = save[: save.index("\n}\n$(\"message-modal-cancel\")")]
    # The rename is conditioned on the edited message being the first question.
    assert "const editsFirstQuestion = !prefix.some(" in save
    assert "if (targetConversationId && editsFirstQuestion)" in save
    # It reuses the summary helper that named the chat in the first place.
    assert "refreshTitleAfterPromptEdit(" in save


def test_the_rename_reuses_the_existing_summary_request():
    src = INDEX_JS.read_text(encoding="utf-8")

    helper = src[src.index("function refreshTitleAfterPromptEdit(") :]
    helper = helper[: helper.index("\n}\n", helper.index("return applyGeneratedTitle("))]
    assert "requestGeneratedTitle(prompt)" in helper
    # A failed summary still renames the chat to the edited question.
    assert "generated || prompt" in helper
    # The previous title guards a manual rename made while the summary runs.
    assert "applyGeneratedTitle(title, conversationIdForTitle, previousTitle)" in helper
