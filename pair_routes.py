"""Routes for the pairing page and the device-auth API.

The handlers were split out of app.py so the page-specific code stays in one
place; shared helpers, the settings store, the auth store and the Flask app
remain in app.py, which registers this blueprint.
"""
from flask import Blueprint, jsonify, redirect, render_template, request

from app import (
    AUTH_ENABLED,
    AUTH_LOCK,
    AUTH_PAIRING_TTL_MINUTES,
    AUTH_SESSION_COOKIE,
    AUTH_SESSION_COOKIE_HTTP,
    AUTH_SESSION_COOKIE_NAMES,
    AUTH_SESSION_DAYS,
    app,
    auth_now,
    auth_session_tokens,
    consume_pairing_key,
    create_auth_session,
    current_auth_session,
    generate_pairing_key,
    hash_auth_token,
    hmac,
    load_auth_state,
    log_event,
    no_store,
    pairing_attempt_allowed,
    prune_auth_state,
    record_pairing_failure,
    revoke_auth_session,
    save_auth_state,
)

pair_bp = Blueprint("pair", __name__)


@pair_bp.get("/pair")
def pair_page():
    """Render the pairing page where a client submits the server key."""
    if current_auth_session():
        return redirect("/")
    return render_template("pair/pair.html", ttl_minutes=AUTH_PAIRING_TTL_MINUTES, session_days=AUTH_SESSION_DAYS)


@pair_bp.get("/api/auth/status")
def auth_status():
    """Report whether this device is paired without exposing any secret."""
    session = current_auth_session() if AUTH_ENABLED else None
    return no_store(jsonify({
        "enabled": AUTH_ENABLED,
        "authenticated": bool(session) or not AUTH_ENABLED,
        "session": {
            "id": session.get("id"),
            "label": session.get("label", ""),
            "created_at": session.get("created_at"),
            "last_seen_at": session.get("last_seen_at"),
            "expires_at": session.get("expires_at"),
        } if session else None,
    }))


@pair_bp.post("/api/auth/pair")
def auth_pair():
    """Exchange a valid single-use pairing key for a session cookie."""
    if not AUTH_ENABLED:
        return jsonify({"ok": True, "redirect": "/"})
    body = request.get_json(silent=True) or {}
    client_ip = request.remote_addr or "unknown"
    if not pairing_attempt_allowed(client_ip):
        return jsonify({"error": "Too many pairing attempts. Please wait a few minutes and try again."}), 429
    if not consume_pairing_key(body.get("key")):
        record_pairing_failure(client_ip)
        return jsonify({"error": "This Pairing Key is invalid, expired, or already used."}), 401
    token = create_auth_session(
        label=str(body.get("label") or ""),
        user_agent=request.headers.get("User-Agent", ""),
        client_ip=client_ip,
    )
    log_event("auth.paired", "จับคู่อุปกรณ์ใหม่สำเร็จ", ip=client_ip)
    response = jsonify({"ok": True, "redirect": "/"})
    cookie_name = AUTH_SESSION_COOKIE if request.is_secure else AUTH_SESSION_COOKIE_HTTP
    response.set_cookie(
        cookie_name,
        token,
        max_age=AUTH_SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
        path="/",
    )
    # Drop a leftover cookie from the other scheme so an old token cannot be
    # picked up later when the app runs over the other protocol.
    other_name = AUTH_SESSION_COOKIE_HTTP if request.is_secure else AUTH_SESSION_COOKIE
    response.delete_cookie(other_name, path="/", secure=request.is_secure, samesite="Lax")
    return response


@pair_bp.get("/api/auth/sessions")
def auth_sessions_list():
    """List paired devices so the owner can review and revoke them."""
    current = current_auth_session() or {}
    now = auth_now()
    with AUTH_LOCK:
        state = load_auth_state()
        prune_auth_state(state, now)
        save_auth_state(state)
        items = [{
            "id": item.get("id"),
            "label": item.get("label", ""),
            "created_at": item.get("created_at"),
            "last_seen_at": item.get("last_seen_at"),
            "expires_at": item.get("expires_at"),
            "current": item.get("id") == current.get("id"),
        } for item in state["sessions"]]
    items.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    return no_store(jsonify({"items": items, "auth_enabled": AUTH_ENABLED}))


@pair_bp.post("/api/auth/pairing-keys")
def auth_create_pairing_key():
    """Generate a fresh pairing key for a new device from an authorized session."""
    if not AUTH_ENABLED:
        return jsonify({"error": "Web auth is disabled. Set AI_WEB_AUTH=on to use pairing keys."}), 400
    body = request.get_json(silent=True) or {}
    record = generate_pairing_key(str(body.get("label") or ""))
    log_event("auth.pairing_key", "สร้าง Pairing Key ใหม่")
    return jsonify({"ok": True, **record}), 201


@pair_bp.post("/api/auth/logout")
def auth_logout():
    """Revoke this device's session and clear its cookies."""
    digests = [hash_auth_token(token) for token in auth_session_tokens()]
    if digests:
        with AUTH_LOCK:
            state = load_auth_state()
            remaining = [
                item for item in state["sessions"]
                if not any(
                    hmac.compare_digest(str(item.get("token_hash") or ""), digest)
                    for digest in digests
                )
            ]
            if len(remaining) != len(state["sessions"]):
                state["sessions"] = remaining
                save_auth_state(state)
    response = jsonify({"ok": True, "redirect": "/pair"})
    for name in AUTH_SESSION_COOKIE_NAMES:
        response.delete_cookie(name, path="/", secure=request.is_secure, samesite="Lax")
    return response


@pair_bp.delete("/api/auth/sessions/<session_id>")
def auth_revoke_session(session_id: str):
    """Revoke one paired device by id."""
    if not revoke_auth_session(session_id):
        return jsonify({"error": "Device not found"}), 404
    log_event("auth.revoked", "ยกเลิกอุปกรณ์ที่เชื่อมต่อ", session=session_id)
    return jsonify({"ok": True})
