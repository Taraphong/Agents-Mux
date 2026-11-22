"""Assemble the Flask application and serve it.

The implementation lives in packages: ``core/`` holds settings, storage,
providers, tools and TLS; ``services/`` holds the scheduler and the Discord
bot; ``routes/`` holds the HTTP blueprints. This module creates the Flask app,
registers the request hooks and blueprints, and is the entrypoint for
``python app.py``.
"""

import os
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import ThreadedWSGIServer

load_dotenv()

# Imported after load_dotenv(): the module resolves AI_WEB_MEMORY_* paths at
# import time, so a value that exists only in .env must already be loaded.
import memory_engine  # noqa: E402

from core.auth import (  # noqa: E402
    AUTH_ENABLED,
    bootstrap_pairing_key,
    current_auth_session,
    generate_pairing_key,
    print_pairing_banner,
    revoke_all_auth_sessions,
)
from core.config import (  # noqa: E402
    AUTH_PUBLIC_PATHS,
    AUTH_PUBLIC_PREFIXES,
    AUTH_TRUST_PROXY,
    MUTATING_METHODS,
    TEMPLATES_ROOT,
)
from core.env import env_int  # noqa: E402
from core.http_cache import compress_response  # noqa: E402
from core.log import LOGGER, load_persisted_logs, log_event  # noqa: E402
from core.messages import request_language, status_message  # noqa: E402
from core.tls import (  # noqa: E402
    DrainingRequestHandler,
    TLSServer,
    build_tls_context,
    tls_configuration,
)
from core.tools import workspace_directory  # noqa: E402
from routes.index import index_bp  # noqa: E402
from routes.pair import pair_bp  # noqa: E402
from services.discord_bot import start_discord_bot  # noqa: E402
from services.scheduler import start_scheduler  # noqa: E402

app = Flask(__name__)
# Reject oversized bodies before they reach the JSON parser or the history writer.
app.config["MAX_CONTENT_LENGTH"] = env_int("AI_WEB_MAX_CONTENT_BYTES", 8 * 1024 * 1024, 64 * 1024)

if AUTH_TRUST_PROXY:
    # Honour X-Forwarded-Proto/Host when TLS terminates at a reverse proxy so
    # request.is_secure (and the Secure session cookie) reflects the client.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

load_persisted_logs()

try:
    workspace_directory()
except OSError as exc:
    LOGGER.warning("Could not create the AI workspace folder: %s", exc)


@app.before_request
def reject_cross_site_mutation():
    """Refuse state-changing requests that a browser sent from another site."""
    if request.method not in MUTATING_METHODS:
        return None
    # Sec-Fetch-Site is set by the browser and cannot be forged by page script,
    # so it catches a cross-site request even when the Origin comparison is
    # defeated by a spoofed or proxy-supplied Host / X-Forwarded-Host.
    fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if fetch_site in {"cross-site", "same-site"}:
        log_event("security.cross_site", "Rejected a cross-site request", path=request.path, method=request.method, site=fetch_site)
        return jsonify({"error": status_message(request_language(), "cross_origin")}), 403
    origin = request.headers.get("Origin", "").strip()
    if origin:
        parsed = urlsplit(origin)
        if not (parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request.host.lower()):
            log_event("security.cross_origin", "Rejected a request from another origin", path=request.path, method=request.method)
            return jsonify({"error": status_message(request_language(), "cross_origin")}), 403
    # Only a request that will actually be served counts as the owner being
    # active: recording it before these checks let rejected cross-site requests
    # postpone the nightly memory run. An unpaired client is rejected below.
    if not AUTH_ENABLED or current_auth_session():
        memory_engine.touch_activity()
    return None


@app.errorhandler(413)
def request_too_large(_error):
    """Answer an oversized upload with JSON instead of Werkzeug's HTML page."""
    return jsonify({"error": status_message(request_language(allow_body=False), "body_too_large")}), 413


@app.before_request
def require_web_auth():
    """Gate every page and API behind a paired device unless auth is disabled."""
    if not AUTH_ENABLED:
        return None
    path = request.path or ""
    if path in AUTH_PUBLIC_PATHS or path.startswith(AUTH_PUBLIC_PREFIXES):
        return None
    if current_auth_session():
        return None
    if path.startswith("/api/"):
        return jsonify({"error": status_message(request_language(), "pairing_required"), "auth_required": True}), 401
    return redirect("/pair", code=302)


def asset_url(page: str, filename: str) -> str:
    """Return a cache-busting URL for a page asset.

    The mtime in the query lets the asset be cached for a year: editing the
    file changes the URL, so the browser fetches the new version on reload.
    """
    try:
        version = (TEMPLATES_ROOT / page / filename).stat().st_mtime_ns
    except OSError:
        version = 0
    return f"/templates/{page}/{filename}?v={version}"


app.jinja_env.globals["asset_url"] = asset_url


@app.after_request
def gzip_rendered_pages(response):
    """Gzip rendered HTML so the chat page needs fewer round trips on a slow link."""
    if (response.mimetype or "").lower() == "text/html":
        return compress_response(response)
    return response


def auth_cli(argv: list[str]) -> bool:
    """Handle pairing-key CLI flags without starting the web server."""
    if "--pairing-key" not in argv and "--revoke-sessions" not in argv:
        return False
    if "--revoke-sessions" in argv:
        print(f"✅ Revoked every connected device ({revoke_all_auth_sessions()})", flush=True)
    if "--pairing-key" in argv:
        if not AUTH_ENABLED:
            print("Web auth is off — set AI_WEB_AUTH=on to create a Pairing Key", flush=True)
            return True
        label = "cli"
        if "--label" in argv:
            index = argv.index("--label")
            if index + 1 < len(argv):
                label = argv[index + 1]
        print_pairing_banner(generate_pairing_key(label))
    return True


if os.getenv("AI_WEB_ENABLE_SCHEDULER", "").strip().lower() in {"1", "true", "yes"}:
    start_scheduler()
    memory_engine.start_scheduler()

app.register_blueprint(pair_bp)
app.register_blueprint(index_bp)


if __name__ == "__main__":
    if auth_cli(sys.argv[1:]):
        raise SystemExit(0)
    start_scheduler()
    memory_engine.start_scheduler()
    start_discord_bot()
    print_pairing_banner(bootstrap_pairing_key())
    port = int(os.getenv("PORT", "5000"))
    ssl_context = tls_configuration()
    scheme = "https" if ssl_context else "http"
    print(f"🔒 Serving at {scheme}://<ip>:{port}" if ssl_context else f"🌐 Serving at http://<ip>:{port}", flush=True)
    if ssl_context:
        print("   Session cookies are marked Secure because request.is_secure is true", flush=True)
        # Handshake per connection so a client that never sends TLS data
        # cannot block the accept loop.
        server = TLSServer("0.0.0.0", port, app, build_tls_context(ssl_context))
        server.log_startup()
        server.serve_forever()
    else:
        server = ThreadedWSGIServer(
            "0.0.0.0", port, app, handler=DrainingRequestHandler
        )
        server.log_startup()
        server.serve_forever()
