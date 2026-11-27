#!/usr/bin/env bash
# Install AI Web automatically (Termux / Linux / macOS)
#
# Usage:
#   bash install.sh
#
# The script creates .venv, installs dependencies, creates .env from .env.example,
# and prepares the required folders without overwriting .env or existing settings.

set -eu

APP_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

info() { printf '📦 %s\n' "$1"; }
ok() { printf '✅ %s\n' "$1"; }
die() {
  printf '❌ %s\n' "$1" >&2
  exit 1
}

case "${1:-}" in
  -h|--help)
    sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

# ---------- 1. Check Python / the existing .venv ----------
VENV_PY="$APP_DIR/.venv/bin/python"

venv_ok() {
  [ -x "$VENV_PY" ] &&
    "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

PYTHON_BIN=""
if [ -z "${PYTHON:-}" ] && venv_ok; then
  # Reinstalling on a prepared machine: the existing .venv works without Python on PATH.
  info "Found an existing .venv, reusing it ($("$VENV_PY" --version 2>&1))"
else
  PYTHON_BIN="${PYTHON:-}"
  PYTHON_TOO_OLD=""
  if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3 python; do
      command -v "$candidate" >/dev/null 2>&1 || continue
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
      fi
      PYTHON_TOO_OLD="$candidate"
    done
  fi

  if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$VENV_PY" ]; then
      die "An existing .venv is unusable and no Python was found on PATH — check .venv or install Python again"
    fi
    if [ -n "$PYTHON_TOO_OLD" ]; then
      die "Found $PYTHON_TOO_OLD but Python 3.10 or newer is required (found $("$PYTHON_TOO_OLD" --version 2>&1)) — install a newer Python or set PYTHON=/path/to/python3"
    fi
    die "Python not found — install it first: pkg install python (Termux) or sudo apt install python3 python3-venv"
  fi

  if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    die "Python 3.10 or newer is required (found $("$PYTHON_BIN" --version 2>&1))"
  fi
  info "Using $("$PYTHON_BIN" --version 2>&1) at $(command -v "$PYTHON_BIN")"
fi

# ---------- 2. Create the virtual environment ----------
if [ -n "$PYTHON_BIN" ]; then
  if [ -x "$VENV_PY" ]; then
    info "Updating .venv to use $("$PYTHON_BIN" --version 2>&1)"
    "$PYTHON_BIN" -m venv .venv || die "Failed to update .venv — on Debian/Ubuntu install python3-venv"
  else
    info "Creating .venv"
    "$PYTHON_BIN" -m venv .venv || die "Failed to create .venv — on Debian/Ubuntu install python3-venv"
  fi
fi

[ -x "$VENV_PY" ] || die "Not found: $VENV_PY"

# ---------- 3. Install dependencies ----------
info "Updating pip"
"$VENV_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

info "Installing dependencies from requirements.txt (this may take a while)"
"$VENV_PY" -m pip install --quiet -r requirements.txt || die "Failed to install dependencies — check your internet connection and try again"

# pip can succeed while the interpreter still cannot import the packages (a
# .venv rebuilt by another Python version keeps the old ones in a different
# lib/pythonX.Y folder). Stop here with one line instead of letting the first
# start write a ModuleNotFoundError traceback into logs/ai-web.log.
if ! "$VENV_PY" -c 'import flask, requests, dotenv' >/dev/null 2>&1; then
  die "Dependencies are installed but not importable by $VENV_PY — run: $VENV_PY -m pip install -r requirements.txt"
fi

# ---------- 4. Configuration file and folders ----------
if [ ! -f .env ]; then
  (umask 077; cp .env.example .env; chmod 600 .env)
  info "Created .env from .env.example"
else
  info "Found an existing .env, not overwriting it"
fi

mkdir -p logs history

chmod +x start_web.sh 2>/dev/null || true

# ---------- 5. startweb command (Termux) ----------
LINKED=""
if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ] && [ -d /data/data/com.termux ]; then
  ln -sf "$APP_DIR/start_web.sh" "$PREFIX/bin/startweb" && LINKED="$PREFIX/bin/startweb"
fi

# ---------- 6. Summary ----------
ok "Installation complete"
printf '\n'
printf 'Next steps:\n'
printf '  1) Add the provider API key to %s\n' "$APP_DIR/.env"
printf '  2) Start the server:  ./start_web.sh --start\n'
if [ -n "$LINKED" ]; then
  printf '     or use the short command:  startweb --start  (installed at %s)\n' "$LINKED"
fi
printf '  3) Open the web app at http://127.0.0.1:5000\n'
printf '     Other devices on the same network use http://<IP-of-this-machine>:5000\n'
printf '\n'
printf 'Note: the system uses a Pairing Key instead of a login page — open /pair and enter the key from ./start_web.sh --pair\n'
