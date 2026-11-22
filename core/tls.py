"""TLS configuration and the threaded HTTPS server.

The certificate helpers read the AI_WEB_TLS_* variables, write them back to
.env and build the server that handshakes per connection.
"""

import ipaddress
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler, load_ssl_context

from core.config import ADHOC_CERT_FILE, ADHOC_KEY_FILE, CERT_DIR, ENV_FILE
from core.log import log_event


def configured_certificate_pair() -> tuple[str, str] | None:
    """Return a usable certificate pair the server can actually serve.

    `certs/cert.pem` + `certs/key.pem` (what --make-cert writes) win. When they
    are absent, keep a pair that is already configured in .env instead of
    refusing to save the mode the server is running with right now.
    """
    default_cert = CERT_DIR / "cert.pem"
    default_key = CERT_DIR / "key.pem"
    if default_cert.is_file() and default_key.is_file():
        return str(default_cert), str(default_key)
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    if cert and key and Path(cert).is_file() and Path(key).is_file():
        return cert, key
    return None


def server_tls_state() -> dict[str, Any]:
    """Describe the TLS mode the server will use on its next start."""
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    adhoc = os.getenv("AI_WEB_TLS_ADHOC", "").strip().lower() in {"1", "true", "yes", "on"}
    # An explicit ad-hoc request wins, so the saved certificate pair can stay in
    # .env while ad-hoc mode runs and still be reused afterwards.
    if adhoc:
        kind = "adhoc"
    elif cert and key:
        kind = "cert"
    else:
        kind = "none"
    return {
        "mode": "https" if kind != "none" else "http",
        "kind": kind,
        "cert_exists": bool(cert) and Path(cert).is_file(),
        "key_exists": bool(key) and Path(key).is_file(),
        # True when saving "HTTPS with certificate files" would succeed: either
        # certs/cert.pem + certs/key.pem exist, or the pair in .env is usable.
        "pair_available": configured_certificate_pair() is not None,
        "adhoc": adhoc,
    }
TLS_ENV_KEYS = ("AI_WEB_TLS_CERT", "AI_WEB_TLS_KEY", "AI_WEB_TLS_ADHOC")
TLS_ENV_LOCK = threading.Lock()


def apply_tls_environment(values: dict[str, str]) -> None:
    """Mirror a saved TLS mode into this process environment.

    load_dotenv() only fills variables when the process starts, so without this
    the running server keeps the old AI_WEB_TLS_* values in its environment.
    A restart started from the web page inherits them, and because an exported
    variable wins over .env, switching back to HTTP would never take effect.

    The caller keeps the certificate pair in AI_WEB_TLS_CERT/KEY while ad-hoc
    mode runs, and tls_configuration() lets AI_WEB_TLS_ADHOC win over that
    pair, so re-selecting "HTTPS with certificate files" reuses the same paths
    instead of losing them.
    """
    for key in TLS_ENV_KEYS:
        value = values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def update_env_file(values: dict[str, str]) -> None:
    """Update keys in .env atomically; an empty value removes the key.

    Only the three AI_WEB_TLS_* keys are ever written, and the rest of the
    file (API keys included) is preserved byte for byte.
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OSError(f"Could not read the .env file: {exc}") from exc
    pending = dict(values)
    output: list[str] = []
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = pattern.match(line)
        key = match.group(1) if match else ""
        if key and key in pending:
            value = pending.pop(key)
            if value:
                output.append(f"{key}={value}")
            continue
        output.append(line)
    for key, value in pending.items():
        if value:
            output.append(f"{key}={value}")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ENV_FILE.with_name(f".{ENV_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output).strip("\n") + "\n")
        os.replace(temp_path, ENV_FILE)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def tls_configuration() -> Any:
    """Return a Werkzeug ssl_context for HTTPS, or None to serve plain HTTP.

    Precedence matches start_web.sh: an explicit ad-hoc request wins over a
    saved certificate pair, so the pair can be kept in .env while ad-hoc mode
    runs and be reused when the user switches back.
    """
    adhoc = os.getenv("AI_WEB_TLS_ADHOC", "").strip().lower() in {"1", "true", "yes", "on"}
    cert = os.getenv("AI_WEB_TLS_CERT", "").strip()
    key = os.getenv("AI_WEB_TLS_KEY", "").strip()
    if adhoc:
        return "adhoc"
    if cert or key:
        if not (cert and key):
            raise SystemExit("Set AI_WEB_TLS_CERT and AI_WEB_TLS_KEY together")
        missing = [path for path in (cert, key) if not Path(path).is_file()]
        if missing:
            raise SystemExit(f"Certificate/key files not found: {', '.join(missing)}")
        return (cert, key)
    return None
TLS_HANDSHAKE_TIMEOUT_SECONDS = 10
# Seconds close() may spend delivering a response that is still queued.
RESPONSE_LINGER_SECONDS = 5


class DrainingRequestHandler(WSGIRequestHandler):
    """Deliver the whole response before the connection is closed.

    Werkzeug always answers with ``Connection: close`` and then closes the
    socket. On Termux, closing a socket that still holds a large body that has
    not been acknowledged yet aborts delivery, so the browser waits forever on
    a half-loaded page (the chat page is ~248 KB). SO_LINGER makes close()
    block until the peer has the bytes, or the linger timeout expires.
    """

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_LINGER,
                struct.pack("ii", 1, RESPONSE_LINGER_SECONDS),
            )
        except OSError:
            pass


def adhoc_certificate() -> tuple[str, str]:
    """Create (once) and reuse a self-signed certificate for ad-hoc HTTPS.

    Werkzeug's ad-hoc context needs the optional `cryptography` package, which
    a Termux install does not have, so the server died on startup with
    "Using ad-hoc certificates requires the cryptography library". openssl is
    already required for --make-cert, so generate the pair with it instead and
    keep the files under certs/ so a restart hands the browser the same
    certificate instead of a new warning every time.
    """
    if ADHOC_CERT_FILE.is_file() and ADHOC_KEY_FILE.is_file():
        return str(ADHOC_CERT_FILE), str(ADHOC_KEY_FILE)
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "openssl was not found, so the ad-hoc certificate cannot be created — install it with pkg install openssl-tool "
            "or run ./start_web.sh --make-cert and choose the certificate mode"
        )
    names = ["localhost", "127.0.0.1"]
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    if hostname and hostname not in names:
        names.append(hostname)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            address = probe.getsockname()[0]
    except OSError:
        address = ""
    if address and address not in names:
        names.append(address)
    try:
        ipaddress.ip_address(names[0])
        common_name = hostname or "localhost"
    except ValueError:
        common_name = names[0]
    san = ",".join(
        f"IP:{name}" if _is_ip_address(name) else f"DNS:{name}" for name in names
    )
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    temp_key = ADHOC_KEY_FILE.with_name(f".{ADHOC_KEY_FILE.name}.{uuid.uuid4().hex}.tmp")
    temp_cert = ADHOC_CERT_FILE.with_name(f".{ADHOC_CERT_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        result = subprocess.run(
            [
                openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                "-days", "3650",
                "-keyout", str(temp_key), "-out", str(temp_cert),
                "-subj", f"/CN={common_name}",
                "-addext", f"subjectAltName={san}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not create the ad-hoc certificate: {result.stderr.strip()[:300]}"
            )
        os.chmod(temp_key, 0o600)
        os.replace(temp_cert, ADHOC_CERT_FILE)
        os.replace(temp_key, ADHOC_KEY_FILE)
    finally:
        for leftover in (temp_key, temp_cert):
            leftover.unlink(missing_ok=True)
    log_event(
        "system.adhoc_cert",
        "Created an ad-hoc HTTPS certificate",
        names=", ".join(names),
    )
    return str(ADHOC_CERT_FILE), str(ADHOC_KEY_FILE)


def _is_ip_address(value: str) -> bool:
    """Report whether a name is a literal IP address for the certificate SAN."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def build_tls_context(ssl_context: Any) -> Any:
    """Turn a tls_configuration() value into a ready ssl.SSLContext."""
    if isinstance(ssl_context, tuple):
        return load_ssl_context(*ssl_context)
    try:
        return load_ssl_context(*adhoc_certificate())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Could not create the ad-hoc HTTPS certificate: {exc}") from exc


class TLSServer(ThreadedWSGIServer):
    """Threaded WSGI server that performs the TLS handshake per connection.

    Werkzeug wraps the listening socket itself, so a client that connects and
    sends no handshake bytes blocks accept() and with it every other client.
    Accepting the plain socket and handshaking in the request thread keeps the
    accept loop free and lets a stalled handshake time out.
    """

    def __init__(self, host: str, port: int, wsgi_app: Any, ssl_context: Any) -> None:
        super().__init__(
            host, port, wsgi_app, handler=DrainingRequestHandler, ssl_context=None
        )
        self.tls_context = ssl_context
        # Werkzeug uses ssl_context to report requests as HTTPS.
        self.ssl_context = ssl_context

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            request.settimeout(TLS_HANDSHAKE_TIMEOUT_SECONDS)
            request = self.tls_context.wrap_socket(request, server_side=True)
            request.settimeout(None)
        except (ssl.SSLError, OSError) as exc:
            self.log("info", f"TLS handshake failed for {client_address}: {exc}")
            try:
                request.close()
            except OSError:
                pass
            return
        super().process_request_thread(request, client_address)
