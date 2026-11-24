"""System-prompt assembly: agent profile, memories, skills and tool rules.

This lives apart from the provider calls so the dependency runs one way:
``memory_engine`` asks ``core.providers`` for a completion, while this module
asks the engine for relevant memories.
"""

from typing import Any

import memory_engine

from core.config import TOOL_INSTRUCTIONS
from core.skills import skills_prompt


def memory_context_block(messages: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    """Return the memory block for the newest user turn, or an empty string."""
    query = ""
    for item in reversed(messages):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        text = content if isinstance(content, str) else memory_engine.message_text(item)
        if text.strip():
            query = text
            break
    if not query:
        return ""
    try:
        block, _ids = memory_engine.build_context(query, settings)
    except Exception:
        return ""
    return block


def agent_profile_prompt(settings: dict[str, Any]) -> str:
    """Turn the user-configured agent profile into stable runtime guidance."""
    language = {"auto": "Reply in the user's language", "th": "Reply in Thai", "en": "Reply in English"}.get(str(settings.get("response_language", "auto")), "Reply in the user's language")
    questions = "Ask back when the information is missing or the request is ambiguous" if settings.get("ask_clarifying_questions", True) else "Avoid asking back and state the assumptions used"
    markdown = "Use Markdown when it improves readability" if settings.get("use_markdown", True) else "Do not use complex Markdown"
    return "Agent profile guidance:\n" + "\n".join((
        f"- Name to introduce yourself with: {str(settings.get('agent_name') or 'Mux')[:80]}",
        f"- Role: {str(settings.get('agent_role') or '')[:500]}",
        f"- Response tone: {str(settings.get('response_style') or '')[:500]}",
        f"- Language: {language}", f"- Format: {markdown}", f"- Asking for more information: {questions}",
    ))


def build_system_prompt(
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    include_memory_review: bool = True,
) -> str:
    """Assemble the system prompt with the memory block before tool rules.

    The block sits before the skill and tool instructions: a stored note must
    never occupy the position the model treats as the strongest instruction.
    """
    memory_review = (
        f"Memory review guidance:\n{settings.get('memory_review', '')}"
        if include_memory_review and settings.get("memory_review")
        else ""
    )
    parts = (
        settings.get("system_prompt", ""),
        agent_profile_prompt(settings),
        memory_review,
        memory_context_block(messages, settings),
        skills_prompt(settings),
        TOOL_INSTRUCTIONS,
    )
    return "\n\n".join(part for part in parts if part)
