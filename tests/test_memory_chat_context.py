"""Tests for wiring the memory block into a chat system prompt.

Both the web chat and the Discord agent call build_system_prompt(), so these
check the shared seam: the newest user turn is the query, the block sits before
the tool rules, and a broken memory store never breaks the prompt.
"""

import uuid

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"


def chat_settings(**overrides):
    memory = {
        "retrieval": True,
        "retrieval_items": 4,
        "retrieval_chars": 800,
        "llm": False,
    }
    memory.update(overrides)
    return {
        "system_prompt": "You are a helpful assistant.",
        "memory_review": "Check the earlier conversation for continuity.",
        "skills": [],
        "memory": memory,
    }


def remember(engine, text, *, score=0.8):
    item = {
        "id": str(uuid.uuid4()),
        "text": text,
        "score": score,
        "theme": "topic",
        "conversation_id": CONVERSATION_ID,
        "norm_hash": engine._hash(engine.compare_text(text).lower()),
    }
    assert engine.promote([item], limit=10)
    return item["id"]


def test_the_newest_user_message_is_used_as_the_query(engine, monkeypatch):
    import app

    seen = []

    def fake_context(query, settings):
        seen.append(query)
        return "MEMORY BLOCK", ["id"]

    monkeypatch.setattr(engine, "build_context", fake_context)
    messages = [
        {"role": "user", "content": "an older question"},
        {"role": "assistant", "content": "an older answer"},
        {"role": "user", "content": "the newest question"},
    ]

    assert app.memory_context_block(messages, chat_settings()) == "MEMORY BLOCK"
    assert seen == ["the newest question"]


def test_a_turn_without_user_text_gets_no_block(engine):
    import app

    messages = [{"role": "assistant", "content": "a greeting"}]

    assert app.memory_context_block(messages, chat_settings()) == ""


def test_the_block_sits_before_the_tool_instructions(engine):
    import app

    remember(engine, "the deploy key lives in the safe")
    prompt = app.build_system_prompt(
        chat_settings(), [{"role": "user", "content": "where is the deploy key"}]
    )

    assert "the deploy key lives in the safe" in prompt
    assert prompt.index("the deploy key lives in the safe") < prompt.index(app.TOOL_INSTRUCTIONS)
    assert prompt.startswith("You are a helpful assistant.")


def test_retrieval_off_leaves_the_prompt_clean(engine):
    import app

    remember(engine, "the deploy key lives in the safe")
    prompt = app.build_system_prompt(
        chat_settings(retrieval=False),
        [{"role": "user", "content": "where is the deploy key"}],
    )

    assert "the deploy key lives in the safe" not in prompt
    assert "Long-term memory" not in prompt
    assert "You are a helpful assistant." in prompt


def test_discord_can_skip_the_memory_review_guidance(engine):
    import app

    prompt = app.build_system_prompt(
        chat_settings(),
        [{"role": "user", "content": "hello"}],
        include_memory_review=False,
    )

    assert "Check the earlier conversation" not in prompt
    assert "You are a helpful assistant." in prompt


def test_the_chat_route_sends_memories_to_the_provider(engine, monkeypatch):
    import app as app_module
    from routes import index as index_routes

    remember(engine, "the deploy key lives in the safe")
    sent = {}

    def fake_provider(messages, settings):
        sent["messages"] = messages
        return "hello", {}

    settings = chat_settings()
    settings.update({"provider": "openai", "model": "test-model", "base_url": ""})
    monkeypatch.setattr(index_routes, "rate_limit_response", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(index_routes, "load_settings", lambda: settings)
    monkeypatch.setattr(index_routes, "call_provider", fake_provider)
    monkeypatch.setattr(index_routes, "log_event", lambda *_args, **_kwargs: None)

    with app_module.app.test_request_context(
        "/api/chat",
        method="POST",
        json={"messages": [{"role": "user", "content": "where is the deploy key"}]},
    ):
        response = index_routes.chat()

    assert response.status_code == 200
    system = sent["messages"][0]
    assert system["role"] == "system"
    assert "the deploy key lives in the safe" in system["content"]


def test_a_broken_memory_store_still_builds_a_prompt(engine, monkeypatch):
    import app

    def broken(*_args, **_kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(engine, "build_context", broken)

    prompt = app.build_system_prompt(
        chat_settings(), [{"role": "user", "content": "where is the deploy key"}]
    )

    assert "You are a helpful assistant." in prompt
    assert app.TOOL_INSTRUCTIONS in prompt
