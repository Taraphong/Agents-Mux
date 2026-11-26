"""A new chat keeps its first message as the title when the summary fails.

The page asks the server for a model-written title beside saving the new
conversation; the first message is only the fallback. The real page functions
(requestGeneratedTitle, applyGeneratedTitle) are run by
``tests/title_fallback_harness.js`` against a DOM/fetch stub: this test only
starts it and checks how the saved conversation is wired to them.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = ROOT / "templates" / "index" / "index.js"
HARNESS = ROOT / "tests" / "title_fallback_harness.js"
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


def test_the_page_patches_a_generated_title(summary):
    assert summary["ok"] is True, summary
    assert summary["requests"] >= 3


def test_save_conversation_uses_the_first_message_as_the_fallback():
    src = INDEX_JS.read_text(encoding="utf-8")

    save = src[src.index("async function saveConversation(") :]
    save = save[: save.index("\n}\nasync function appendAssistantToHistory(")]
    # The stored title starts as the first question, so a failed summary leaves
    # the conversation named that way instead of untitled.
    assert 'const title = firstUser?.content || t("chat.newConversationTitle");' in save
    assert "title,\n          messages: snapshot.map(historyMessagePayload)," in save
    # The model-written title is applied only beside the saved record.
    assert "applyGeneratedTitle(generatedTitle, saved.id, title)" in save
