import os
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
SETTINGS_FILE = Path(os.getenv("AI_WEB_SETTINGS_FILE", ".app-settings.json"))
HISTORY_ROOT = Path(os.getenv("AI_WEB_HISTORY_DIR", "history"))

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


def find_history_file(conversation_id: str) -> Path | None:
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        return None
    for path in HISTORY_ROOT.rglob(f"*_{conversation_id}.json"):
        return path
    return None


def save_history(payload: dict[str, Any]) -> dict[str, Any]:
    conversation_id = payload.get("id") or ""
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", conversation_id):
        conversation_id = str(uuid.uuid4())
    now = datetime.now().astimezone()
    existing = find_history_file(conversation_id)
    existing_record = {}
    if existing and existing.exists():
        try:
            existing_record = json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_record = {}
    created_at = payload.get("created_at") or now.isoformat(timespec="seconds")
    path = existing or HISTORY_ROOT / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}_{conversation_id}.json"
    record = {
        "id": conversation_id,
        "title": (payload.get("title") or "บทสนทนาใหม่")[:100],
        "created_at": created_at,
        "updated_at": now.isoformat(timespec="seconds"),
        "locked": bool(existing_record.get("locked", False)),
        "pinned": bool(existing_record.get("pinned", False)),
        "messages": payload.get("messages", []),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


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
    for item in messages:
        content = item.get("content", "")
        attachment = item.get("attachment")
        if isinstance(attachment, dict) and attachment.get("name") and attachment.get("content"):
            content = f"{content}\n\n[ไฟล์แนบ: {attachment['name']}]\n```\n{attachment['content']}\n```"
        result.append({"role": item.get("role", "user"), "content": content})
    return result


def normalize_usage(usage: dict[str, Any] | None, input_key: str, output_key: str, total_key: str | None) -> dict[str, int] | None:
    """Map provider-specific usage fields to the fields shown in the UI."""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get(input_key)
    output_tokens = usage.get(output_key)
    total_tokens = usage.get(total_key) if total_key else None
    if not isinstance(input_tokens, int) and not isinstance(output_tokens, int) and not isinstance(total_tokens, int):
        return None
    result = {}
    if isinstance(input_tokens, int):
        result["input_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        result["output_tokens"] = output_tokens
    if isinstance(total_tokens, int):
        result["total_tokens"] = total_tokens
    elif result:
        result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
    return result


def call_openai(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
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
    return data["choices"][0]["message"]["content"], normalize_usage(data.get("usage"), "prompt_tokens", "completion_tokens", "total_tokens")


def call_gemini(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
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
    usage = data.get("usageMetadata", {})
    return data["candidates"][0]["content"]["parts"][0]["text"], normalize_usage(
        usage, "promptTokenCount", "candidatesTokenCount", "totalTokenCount"
    )


def call_anthropic(messages: list[dict[str, str]], settings: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
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
    data = response.json()
    usage = data.get("usage", {})
    return data["content"][0]["text"], normalize_usage(usage, "input_tokens", "output_tokens", None)


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


@app.get("/api/history")
def history_list():
    records = []
    if HISTORY_ROOT.exists():
        for path in HISTORY_ROOT.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                records.append({key: record.get(key) for key in ("id", "title", "created_at", "updated_at", "locked", "pinned")})
            except (OSError, json.JSONDecodeError):
                continue
    records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return jsonify({"items": records})


@app.get("/api/history/<conversation_id>")
def history_get(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


@app.patch("/api/history/<conversation_id>")
def history_update(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    record = json.loads(path.read_text(encoding="utf-8"))
    body = request.get_json(silent=True) or {}
    if record.get("locked") and "title" in body:
        return jsonify({"error": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนเปลี่ยนชื่อ"}), 423
    if "title" in body:
        title = str(body["title"]).strip()
        if title:
            record["title"] = title[:100]
    if "locked" in body:
        record["locked"] = bool(body["locked"])
    if "pinned" in body:
        record["pinned"] = bool(body["pinned"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify(record)


@app.delete("/api/history/<conversation_id>")
def history_delete(conversation_id: str):
    path = find_history_file(conversation_id)
    if not path or not path.exists():
        return jsonify({"error": "ไม่พบประวัติการสนทนา"}), 404
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("locked"):
        return jsonify({"error": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนลบ"}), 423
    path.unlink()
    return jsonify({"ok": True})


@app.post("/api/history")
def history_save():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("messages"), list):
        return jsonify({"error": "รูปแบบประวัติไม่ถูกต้อง"}), 400
    return jsonify(save_history(body))


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
            answer, _usage = call_gemini(messages, settings)
        elif provider == "anthropic":
            answer, _usage = call_anthropic(messages, settings)
        else:
            answer, _usage = call_openai(messages, settings)
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
        requested_thinking = body.get("thinking_level")
        if requested_thinking in {"off", "low", "medium", "high"}:
            settings["thinking_level"] = requested_thinking
        requested_model = body.get("model")
        if isinstance(requested_model, str) and requested_model.strip():
            settings["model"] = requested_model.strip()
        provider = settings["provider"].lower()
        messages = clean_messages(messages, settings)
        started_at = time.perf_counter()
        if provider == "gemini":
            answer, usage = call_gemini(messages, settings)
        elif provider == "anthropic":
            answer, usage = call_anthropic(messages, settings)
        else:
            answer, usage = call_openai(messages, settings)
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        return jsonify({"answer": answer, "provider": provider, "duration_ms": duration_ms, "usage": usage})
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        return jsonify({"error": f"เรียก API ไม่สำเร็จ: {detail}"}), 502
    except (KeyError, IndexError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

