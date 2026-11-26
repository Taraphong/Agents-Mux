"""The conversation-title endpoint over a scripted provider.

A new chat is named by one cheap model call. These tests pin the answers the
page depends on: a clean title on success, a 502 when the model answers empty
or the provider fails, and the retry that moves to the configured fallback
model before giving up (otherwise the page would keep the raw first message
even though a working fallback is configured).
"""

from types import SimpleNamespace

import pytest
import requests
from flask import Flask

import routes.index as index_routes
from core.messages import status_message
from core.providers import ProviderEmptyResponse

QUESTION = "ช่วยอธิบายสั้น ๆ ว่า SQLite กับ PostgreSQL ต่างกันอย่างไร"


def http_error(status: int) -> requests.HTTPError:
    """Build the error a provider call raises for one HTTP status."""
    response = requests.Response()
    response.status_code = status
    response.url = "https://provider.example/models/test:generateContent"
    return requests.HTTPError(f"{status} from the provider", response=response)


@pytest.fixture()
def title_app(monkeypatch):
    """Expose /api/history/title with a scripted provider and collected settings."""
    state = SimpleNamespace(
        settings={
            "provider": "openai",
            "model": "gpt-test",
            "base_url": "https://primary.example/v1",
            "fallback_enabled": False,
            "fallback_provider": "gemini",
            "fallback_model": "gemini-fallback",
            "thinking_level": "high",
            "max_tokens": 4096,
            "temperature": 0.9,
        },
        calls=[],
        logs=[],
        answers=[],
    )

    def fake_call_provider(messages, settings):
        state.calls.append({"messages": messages, "settings": dict(settings)})
        answer = state.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer, {"total_tokens": 3}

    def fake_log_event(event, message, **details):
        state.logs.append({"event": event, "details": {**details, "message": message}})

    monkeypatch.setattr(index_routes, "load_settings", lambda: dict(state.settings))
    monkeypatch.setattr(index_routes, "call_provider", fake_call_provider)
    monkeypatch.setattr(index_routes, "log_event", fake_log_event)
    # The budget is shared through a module global, so one test could otherwise
    # spend another test's allowance.
    monkeypatch.setattr(index_routes, "rate_limit_response", lambda bucket: None)

    app = Flask(__name__)
    app.register_blueprint(index_routes.index_bp)
    state.client = app.test_client()
    return state


def request_title(title_app, **body):
    payload = {"question": QUESTION, "lang": "th", **body}
    return title_app.client.post("/api/history/title", json=payload)


def test_a_successful_summary_returns_one_clean_title(title_app):
    title_app.answers = ["  **หัวข้อ: SQLite กับ PostgreSQL ต่างกันอย่างไร**  \n"]

    response = request_title(title_app)

    assert response.status_code == 200
    assert response.get_json() == {"title": "SQLite กับ PostgreSQL ต่างกันอย่างไร"}
    assert len(title_app.calls) == 1
    call = title_app.calls[0]
    # The question is the only user turn; the naming instruction is the system turn.
    assert [message["role"] for message in call["messages"]] == ["system", "user"]
    assert call["messages"][1]["content"] == QUESTION
    assert "หัวข้อ" in call["messages"][0]["content"]
    # A title is one cheap line: no thinking budget and a small output cap,
    # whatever the chat settings say.
    assert call["settings"]["thinking_level"] == "off"
    assert call["settings"]["max_tokens"] == 200
    assert call["settings"]["temperature"] == 0.2
    assert [entry["event"] for entry in title_app.logs] == []


def test_the_requested_chat_model_names_the_conversation(title_app):
    title_app.answers = ["หัวข้อจากโมเดลที่เลือก"]

    response = request_title(title_app, model="gemini-x")

    assert response.status_code == 200
    assert title_app.calls[0]["settings"]["model"] == "gemini-x"


def test_an_empty_answer_is_reported_as_a_failed_summary(title_app):
    title_app.answers = ["   "]

    response = request_title(title_app)

    assert response.status_code == 502
    assert response.get_json()["error"] == status_message("th", "title_generation_failed")
    assert [entry["event"] for entry in title_app.logs] == ["title.empty"]
    assert len(title_app.calls) == 1


def test_a_provider_with_no_text_reports_a_failed_summary(title_app):
    title_app.answers = [ProviderEmptyResponse("Gemini response contained no text", "SAFETY")]

    response = request_title(title_app)

    assert response.status_code == 502
    assert response.get_json()["error"] == status_message("th", "title_generation_failed")
    assert [entry["event"] for entry in title_app.logs] == ["title.failed"]
    assert len(title_app.calls) == 1


def test_a_provider_failure_without_a_fallback_answers_502(title_app):
    title_app.answers = [http_error(500)]

    response = request_title(title_app)

    assert response.status_code == 502
    assert response.get_json()["error"] == status_message("th", "title_generation_failed")
    assert [entry["event"] for entry in title_app.logs] == ["title.failed"]
    # Nothing is retried when no fallback model is configured.
    assert len(title_app.calls) == 1


def test_a_busy_primary_model_retries_on_the_fallback_model(title_app):
    title_app.settings.update(
        {"fallback_enabled": True, "fallback_provider": "gemini", "fallback_model": "gemini-fallback"}
    )
    title_app.answers = [http_error(503), "หัวข้อจากโมเดลสำรอง"]

    response = request_title(title_app)

    assert response.status_code == 200
    assert response.get_json() == {"title": "หัวข้อจากโมเดลสำรอง"}
    assert len(title_app.calls) == 2
    retry = title_app.calls[1]["settings"]
    assert retry["provider"] == "gemini"
    assert retry["model"] == "gemini-fallback"
    # A Base URL belongs to the primary provider, so it cannot follow the retry.
    assert retry["base_url"] == ""
    assert retry["thinking_level"] == "off"
    assert title_app.logs == [
        {
            "event": "title.retry",
            "details": {
                "message": "The primary model could not name the conversation, retrying on the fallback",
                "status": 503,
            },
        }
    ]


def test_an_authentication_error_is_not_retried(title_app):
    title_app.settings.update(
        {"fallback_enabled": True, "fallback_provider": "gemini", "fallback_model": "gemini-fallback"}
    )
    title_app.answers = [http_error(401)]

    response = request_title(title_app)

    assert response.status_code == 502
    assert [entry["event"] for entry in title_app.logs] == ["title.failed"]
    assert len(title_app.calls) == 1


def test_a_fallback_pointing_at_the_same_model_is_not_used(title_app):
    title_app.settings.update(
        {
            "fallback_enabled": True,
            "fallback_provider": "openai",
            "fallback_model": "gpt-test",
            "provider": "openai",
            "model": "gpt-test",
        }
    )
    title_app.answers = [http_error(503)]

    response = request_title(title_app)

    assert response.status_code == 502
    assert [entry["event"] for entry in title_app.logs] == ["title.failed"]
    assert len(title_app.calls) == 1


def test_the_question_is_required(title_app):
    response = title_app.client.post("/api/history/title", json={"question": "  ", "lang": "th"})

    assert response.status_code == 400
    assert title_app.calls == []
