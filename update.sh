#!/bin/bash
# Pull the newest project files from GitHub and restart the server.
#
# Usage:
#   ./update.sh                 Download the main branch, install changed
#                               dependencies, restart, and check the server.
#   ./update.sh --branch dev    Use another branch.
#   ./update.sh --repo owner/repo
#   ./update.sh --no-restart    Copy files only (no restart or health check).
#   ./update.sh --dry-run       Show what would be updated without writing.
#   ./update.sh --help
#
# The updater only replaces app files (app.py, core/, services/, routes/,
# templates/, skills/, install scripts). It never touches .env,
# .app-settings.json, .app-auth.json, certs/, history/, logs/,
# the personal llm-wiki vault, scheduled-jobs.json, or .venv.
#
# Environment overrides:
#   AI_WEB_UPDATE_REPO     Default: Taraphong/Agents-mux
#   AI_WEB_UPDATE_BRANCH   Default: main
#   AI_WEB_UPDATE_TOKEN    GitHub token for a private repository (requires
#                          curl; it is only sent to GitHub over HTTPS)
#                          (or set GITHUB_TOKEN)
#   AI_WEB_UPDATE_URL      Full tarball URL (mirror or offline copy)

set -u

SCRIPT_PATH="${BASH_SOURCE[0]}"
for _ in 1 2 3 4 5 6 7 8; do
  [ -L "$SCRIPT_PATH" ] || break
  _target="$(readlink "$SCRIPT_PATH" 2>/dev/null)" || break
  case "$_target" in
    /*) SCRIPT_PATH="$_target" ;;
    *) SCRIPT_PATH="$(dirname "$SCRIPT_PATH")/$_target" ;;
  esac
done
APP_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"

REPO="${AI_WEB_UPDATE_REPO:-Taraphong/Agents-mux}"
BRANCH="${AI_WEB_UPDATE_BRANCH:-main}"
RESTART=1
DRY_RUN=0

# Files and folders that make up the running app. Anything not listed here is
# machine-specific data and must survive an update untouched.
APP_FILES="app.py requirements.txt install.sh start_web.sh update.sh .env.example"
APP_DIRS="templates skills core services routes"

say() {
  printf '%s\n' "$*"
}

die() {
  say "❌ $*" >&2
  exit 1
}

usage() {
  sed -n '2,22p' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --branch)
      [ "$#" -ge 2 ] || die "--branch requires a branch name"
      BRANCH="$2"
      shift 2
      ;;
    --repo)
      [ "$#" -ge 2 ] || die "--repo requires owner/repo"
      REPO="$2"
      shift 2
      ;;
    --no-restart)
      RESTART=0
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1 (use --help for usage)"
      ;;
  esac
done

case "$REPO" in
  */*) ;;
  *) die "--repo must look like owner/repo" ;;
esac
case "$BRANCH" in
  ""|*[!A-Za-z0-9._/-]*) die "Invalid branch name: $BRANCH" ;;
esac

[ -f "$APP_DIR/app.py" ] || die "app.py not found in $APP_DIR — run this script from the project folder"

UPDATE_TOKEN="${AI_WEB_UPDATE_TOKEN:-${GITHUB_TOKEN:-}}"

# The token is only ever sent to GitHub's own HTTPS endpoints; a custom
# AI_WEB_UPDATE_URL mirror must never inherit the GitHub credential.
is_github_update_url() {
  case "$1" in
    https://api.github.com/*|https://github.com/*|https://codeload.github.com/*) return 0 ;;
    *) return 1 ;;
  esac
}

fetch_to() {
  local url="$1" output="$2" token=""
  if [ -n "$UPDATE_TOKEN" ] && is_github_update_url "$url"; then
    token="$UPDATE_TOKEN"
  fi
  if command -v curl >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      # --proto/--proto-redir keep every hop on HTTPS, so the credential is
      # never sent over plain HTTP after a redirect.
      curl -fsSL --proto '=https' --proto-redir '=https' --retry 2 --max-time 180 \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.github+json" \
        "$url" -o "$output"
    else
      curl -fsSL --retry 2 --max-time 180 "$url" -o "$output"
    fi
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      # wget re-sends headers after a redirect and cannot restrict the scheme
      # of later hops, so authenticated downloads need curl.
      say "❌ Downloading a private repo needs curl — install it first: pkg install curl" >&2
      return 1
    fi
    wget -q -T 180 -O "$output" "$url"
    return $?
  fi
  say "❌ curl or wget was not found — install one first: pkg install curl" >&2
  return 1
}

TMP_ROOT="${TMPDIR:-/tmp}"
mkdir -p "$TMP_ROOT" 2>/dev/null || true
WORK_DIR="$(mktemp -d "$TMP_ROOT/ai-web-update.XXXXXX")" || die "Could not create the temporary folder"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT INT TERM

ARCHIVE_URL="${AI_WEB_UPDATE_URL:-}"
if [ -z "$ARCHIVE_URL" ]; then
  if [ -n "$UPDATE_TOKEN" ]; then
    # Private repositories need the API tarball endpoint plus a token.
    ARCHIVE_URL="https://api.github.com/repos/$REPO/tarball/$BRANCH"
  else
    ARCHIVE_URL="https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
  fi
fi
say "⬇️  Fetching $REPO ($BRANCH)"
if ! fetch_to "$ARCHIVE_URL" "$WORK_DIR/source.tar.gz"; then
  die "Download failed: $ARCHIVE_URL (check the network, the repo/branch name, or AI_WEB_UPDATE_TOKEN for a private repo)"
fi
[ -s "$WORK_DIR/source.tar.gz" ] || die "The downloaded file is empty"

mkdir -p "$WORK_DIR/source"
if ! tar -xzf "$WORK_DIR/source.tar.gz" -C "$WORK_DIR/source" 2>"$WORK_DIR/tar.log"; then
  cat "$WORK_DIR/tar.log" >&2 2>/dev/null || true
  die "Could not extract the archive (tar is required: pkg install tar)"
fi

set -- "$WORK_DIR"/source/*/
[ -d "${1:-}" ] || die "No project folder was found in the downloaded archive"
SOURCE_DIR="${1%/}"
[ -f "$SOURCE_DIR/app.py" ] || die "The downloaded files have no app.py — check the repo/branch"

say "📦 Source: $REPO@$BRANCH"
say "📁 Destination: $APP_DIR"

# Keep the old dependency list so the updater can tell whether pip must run.
OLD_REQUIREMENTS=""
if [ -f "$APP_DIR/requirements.txt" ]; then
  cp -f "$APP_DIR/requirements.txt" "$WORK_DIR/old-requirements.txt" 2>/dev/null \
    && OLD_REQUIREMENTS="$WORK_DIR/old-requirements.txt"
fi

for file in $APP_FILES; do
  [ -f "$SOURCE_DIR/$file" ] || continue
  if [ -f "$APP_DIR/$file" ] && cmp -s "$SOURCE_DIR/$file" "$APP_DIR/$file"; then
    say "   = $file (unchanged)"
    continue
  fi
  say "   → $file"
  if [ "$DRY_RUN" -eq 0 ]; then
    cp -f "$SOURCE_DIR/$file" "$APP_DIR/$file.new" && mv -f "$APP_DIR/$file.new" "$APP_DIR/$file" || die "Could not copy $file"
  fi
done

for dir in $APP_DIRS; do
  [ -d "$SOURCE_DIR/$dir" ] || continue
  # The loop owns only the app's own code, never user data: skills is merged,
  # and core/services/routes hold nothing machine-specific.

  say "   → $dir/"
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$APP_DIR/$dir"
    # Merge instead of replacing the folder so user-created skills survive.
    cp -R "$SOURCE_DIR/$dir/." "$APP_DIR/$dir/" || die "Could not copy $dir"
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  say "🔍 Dry run finished — no files were written"
  exit 0
fi

chmod +x "$APP_DIR/start_web.sh" "$APP_DIR/install.sh" "$APP_DIR/update.sh" 2>/dev/null || true

# Reinstall dependencies only when requirements.txt actually changed, so a
# normal code update does not spend minutes in pip on a phone.
DEPS_CHANGED=0
if [ -n "$OLD_REQUIREMENTS" ] && [ -f "$APP_DIR/requirements.txt" ]; then
  cmp -s "$OLD_REQUIREMENTS" "$APP_DIR/requirements.txt" || DEPS_CHANGED=1
fi
# requirements.txt is already replaced when pip runs, so a failed install
# cannot be detected by comparing files next time; the marker forces a retry.
DEPS_MARKER="$APP_DIR/.deps-pending"
if [ -f "$DEPS_MARKER" ]; then
  DEPS_CHANGED=1
fi
if [ "${AI_WEB_UPDATE_FORCE_DEPS:-0}" = "1" ]; then
  DEPS_CHANGED=1
fi

if [ "$DEPS_CHANGED" -eq 1 ]; then
  if [ -x "$APP_DIR/.venv/bin/python" ]; then
    PYTHON="$APP_DIR/.venv/bin/python"
  else
    PYTHON="$(command -v python3 || command -v python || true)"
  fi
  if [ -n "$PYTHON" ]; then
    say "🐍 requirements.txt changed — installing dependencies"
    # Record the pending install before running pip and clear it only on
    # success, so the next update retries a failed installation.
    : > "$DEPS_MARKER" 2>/dev/null || true
    (cd "$APP_DIR" && "$PYTHON" -m pip install -r requirements.txt) || die "Could not install the dependencies (it will retry on the next update)"
    rm -f "$DEPS_MARKER"
  else
    say "⚠️  python not found — skipping dependency install (run install.sh yourself)"
  fi
fi

if [ "$RESTART" -eq 1 ]; then
  [ -x "$APP_DIR/start_web.sh" ] || die "No runnable start_web.sh found"
  say "🔁 Restarting the server"
  "$APP_DIR/start_web.sh" --restart || die "restart failed — see logs/ai-web.log"
  "$APP_DIR/start_web.sh" --check || die "The server did not answer after the restart"
else
  say "ℹ️  Skipped the restart (run ./start_web.sh --restart when ready)"
fi

say "✅ Update finished"
