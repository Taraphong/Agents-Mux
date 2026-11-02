import os
import json
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))

DEFAULT_SETTINGS = {
    "provider": os.getenv("AI_PROVIDER", "openai"),
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "base_url": "https://api.openai.com/v1",
    "system_prompt": "คุณเป็นผู้ช่วย AI ที่สุภาพ ชัดเจน และช่วยผู้ใช้ให้บรรลุเป้าหมาย",
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 1,
    "stream": False,
    "thinking_level": "off",
}

FALLBACK_MODELS = {
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini", "o3"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
}


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def list_models(provider: str, settings: dict[str, Any]) -> list[dict[str, str]]:
    key = get_api_key(provider)
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key จึงดึงรายการโมเดลไม่ได้")
    if provider == "gemini":
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key}, timeout=30)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [{"id": item["name"].removeprefix("models/"), "name": item.get("displayName", item["name"])} for item in models if "generateContent" in item.get("supportedGenerationMethods", [])]
    if provider == "anthropic":
        return [{"id": model, "name": model} for model in FALLBACK_MODELS["anthropic"]]
    base_url = settings.get("base_url", "https://api.openai.com/v1").rstrip("/")
    response = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    response.raise_for_status()
    models = response.json().get("data", [])
    return [{"id": item["id"], "name": item["id"]} for item in sorted(models, key=lambda item: item.get("id", ""))]


def get_api_key(provider: str) -> str:
    settings = load_settings()
    stored = settings.get("api_key", "")
    if stored:
        return stored
    return os.getenv({"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider, "OPENAI_API_KEY"), "")


def clean_messages(messages: list[dict[str, str]], settings: dict[str, Any]) -> list[dict[str, str]]:
    result = [{"role": "system", "content": settings.get("system_prompt", "")}] if settings.get("system_prompt") else []
    result.extend({"role": item.get("role", "user"), "content": item.get("content", "")} for item in messages)
    return result


def call_openai(messages: list[dict[str, str]], settings: dict[str, Any]) -> str:
    key = get_api_key(settings["provider"])
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า API key")

    base_url = settings.get("base_url", "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": settings["model"],
        "messages": messages,
        "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"],
        "top_p": settings["top_p"],
    }
    if settings.get("thinking_level") in {"low", "medium", "high"} and (settings["model"].startswith(("o", "gpt-5"))):
        payload["reasoning_effort"] = settings["thinking_level"]
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def call_gemini(messages: list[dict[str, str]], settings: dict[str, Any]) -> str:
    key = get_api_key("gemini")
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Gemini API key")

    contents: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "system":
            continue
        role = "model" if message["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message["content"]}]})

    model = settings["model"]
    generation_config = {
        "temperature": settings["temperature"],
        "topP": settings["top_p"],
        "maxOutputTokens": settings["max_tokens"],
    }
    thinking_level = settings.get("thinking_level", "off")
    if thinking_level in {"low", "medium", "high"}:
        if settings["model"].startswith("gemini-2.5"):
            generation_config["thinkingConfig"] = {"thinkingBudget": {"low": 1024, "medium": 4096, "high": 8192}[thinking_level]}
        else:
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        json={"contents": contents, "generationConfig": generation_config},
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_anthropic(messages: list[dict[str, str]], settings: dict[str, Any]) -> str:
    key = get_api_key("anthropic")
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Anthropic API key")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": settings["model"],
            "system": system,
            "messages": [m for m in messages if m["role"] != "system"],
            "max_tokens": settings["max_tokens"],
            "temperature": settings["temperature"],
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/settings")
def settings_get():
    settings = load_settings()
    key = get_api_key(settings["provider"])
    safe = {**settings, "api_key": "" if not key else "••••••••"}
    safe["has_api_key"] = bool(key)
    return jsonify(safe)


@app.get("/api/models")
def models_get():
    settings = load_settings()
    provider = request.args.get("provider", settings.get("provider", "openai")).lower()
    try:
        models = list_models(provider, settings)
        return jsonify({"provider": provider, "models": models, "source": "api"})
    except (requests.RequestException, RuntimeError, KeyError, TypeError) as exc:
        return jsonify({"provider": provider, "models": [], "source": "error", "error": str(exc)}), 502


@app.put("/api/settings")
def settings_put():
    body = request.get_json(silent=True) or {}
    current = load_settings()
    allowed = {"provider", "model", "base_url", "system_prompt", "temperature", "max_tokens", "top_p", "stream"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    if body.get("api_key") and body["api_key"] != "••••••••":
        current["api_key"] = body["api_key"]
    save_settings(current)
    return jsonify({"ok": True})


@app.post("/api/settings/test")
def settings_test():
    settings = load_settings()
    try:
        messages = clean_messages([{"role": "user", "content": "ตอบคำว่า OK สั้น ๆ"}], settings)
        provider = settings["provider"]
        if provider in {"gemini"}:
            answer = call_gemini(messages, settings)
        elif provider == "anthropic":
            answer = call_anthropic(messages, settings)
        else:
            answer = call_openai(messages, settings)
        return jsonify({"ok": True, "answer": answer})
    except (requests.RequestException, KeyError, IndexError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/settings/reset")
def settings_reset():
    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()
    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "กรุณาส่งข้อความ"}), 400

    try:
        settings = load_settings()
        provider = settings["provider"].lower()
        messages = clean_messages(messages, settings)
        if provider == "gemini":
            answer = call_gemini(messages, settings)
        elif provider == "anthropic":
            answer = call_anthropic(messages, settings)
        else:
            answer = call_openai(messages, settings)
        return jsonify({"answer": answer, "provider": provider})
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        return jsonify({"error": f"เรียก API ไม่สำเร็จ: {detail}"}), 502
    except (KeyError, IndexError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

