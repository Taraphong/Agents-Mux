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
# The updater only replaces app files (app.py, templates/, skills/, install
# scripts). It never touches .env, .app-settings.json, .app-auth.json,
# certs/, history/, logs/, scheduled-jobs.json, or .venv.
#
# Environment overrides:
#   AI_WEB_UPDATE_REPO     Default: Taraphong/Agents-mux
#   AI_WEB_UPDATE_BRANCH   Default: main
#   AI_WEB_UPDATE_TOKEN    GitHub token for a private repository
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
APP_DIRS="templates skills"

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
      [ "$#" -ge 2 ] || die "--branch ต้องระบุชื่อ branch"
      BRANCH="$2"
      shift 2
      ;;
    --repo)
      [ "$#" -ge 2 ] || die "--repo ต้องระบุ owner/repo"
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
      die "ไม่รู้จักตัวเลือก: $1 (ใช้ --help เพื่อดูวิธีใช้)"
      ;;
  esac
done

case "$REPO" in
  */*) ;;
  *) die "--repo ต้องอยู่ในรูป owner/repo" ;;
esac
case "$BRANCH" in
  ""|*[!A-Za-z0-9._/-]*) die "ชื่อ branch ไม่ถูกต้อง: $BRANCH" ;;
esac

[ -f "$APP_DIR/app.py" ] || die "ไม่พบ app.py ใน $APP_DIR — รันสคริปต์นี้จากโฟลเดอร์โปรเจกต์"

UPDATE_TOKEN="${AI_WEB_UPDATE_TOKEN:-${GITHUB_TOKEN:-}}"

fetch_to() {
  local url="$1" output="$2"
  if command -v curl >/dev/null 2>&1; then
    if [ -n "$UPDATE_TOKEN" ]; then
      curl -fsSL --retry 2 --max-time 180 \
        -H "Authorization: Bearer $UPDATE_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "$url" -o "$output"
    else
      curl -fsSL --retry 2 --max-time 180 "$url" -o "$output"
    fi
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    if [ -n "$UPDATE_TOKEN" ]; then
      wget -q -T 180 --header="Authorization: Bearer $UPDATE_TOKEN" -O "$output" "$url"
    else
      wget -q -T 180 -O "$output" "$url"
    fi
    return $?
  fi
  say "❌ ไม่พบ curl หรือ wget — ติดตั้งก่อน: pkg install curl" >&2
  return 1
}

TMP_ROOT="${TMPDIR:-/tmp}"
mkdir -p "$TMP_ROOT" 2>/dev/null || true
WORK_DIR="$(mktemp -d "$TMP_ROOT/ai-web-update.XXXXXX")" || die "สร้างโฟลเดอร์ชั่วคราวไม่สำเร็จ"
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
say "⬇️  กำลังดึง $REPO ($BRANCH)"
if ! fetch_to "$ARCHIVE_URL" "$WORK_DIR/source.tar.gz"; then
  die "ดาวน์โหลดไม่สำเร็จ: $ARCHIVE_URL (ตรวจสอบอินเทอร์เน็ต ชื่อ repo/branch หรือ AI_WEB_UPDATE_TOKEN สำหรับ repo ส่วนตัว)"
fi
[ -s "$WORK_DIR/source.tar.gz" ] || die "ไฟล์ที่ดาวน์โหลดว่างเปล่า"

mkdir -p "$WORK_DIR/source"
if ! tar -xzf "$WORK_DIR/source.tar.gz" -C "$WORK_DIR/source" 2>"$WORK_DIR/tar.log"; then
  cat "$WORK_DIR/tar.log" >&2 2>/dev/null || true
  die "แตกไฟล์ไม่สำเร็จ (ต้องมี tar: pkg install tar)"
fi

set -- "$WORK_DIR"/source/*/
[ -d "${1:-}" ] || die "ไม่พบโฟลเดอร์โปรเจกต์ในไฟล์ที่ดาวน์โหลด"
SOURCE_DIR="${1%/}"
[ -f "$SOURCE_DIR/app.py" ] || die "ไฟล์ที่ดาวน์โหลดไม่มี app.py — ตรวจสอบ repo/branch"

say "📦 แหล่งข้อมูล: $REPO@$BRANCH"
say "📁 ปลายทาง: $APP_DIR"

# Keep the old dependency list so the updater can tell whether pip must run.
OLD_REQUIREMENTS=""
if [ -f "$APP_DIR/requirements.txt" ]; then
  cp -f "$APP_DIR/requirements.txt" "$WORK_DIR/old-requirements.txt" 2>/dev/null \
    && OLD_REQUIREMENTS="$WORK_DIR/old-requirements.txt"
fi

for file in $APP_FILES; do
  [ -f "$SOURCE_DIR/$file" ] || continue
  if [ -f "$APP_DIR/$file" ] && cmp -s "$SOURCE_DIR/$file" "$APP_DIR/$file"; then
    say "   = $file (ไม่เปลี่ยน)"
    continue
  fi
  say "   → $file"
  if [ "$DRY_RUN" -eq 0 ]; then
    cp -f "$SOURCE_DIR/$file" "$APP_DIR/$file.new" && mv -f "$APP_DIR/$file.new" "$APP_DIR/$file" || die "คัดลอก $file ไม่สำเร็จ"
  fi
done

for dir in $APP_DIRS; do
  [ -d "$SOURCE_DIR/$dir" ] || continue
  say "   → $dir/"
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$APP_DIR/$dir"
    # Merge instead of replacing the folder so user-created skills survive.
    cp -R "$SOURCE_DIR/$dir/." "$APP_DIR/$dir/" || die "คัดลอก $dir ไม่สำเร็จ"
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  say "🔍 Dry run เสร็จแล้ว — ไม่มีการเขียนไฟล์"
  exit 0
fi

chmod +x "$APP_DIR/start_web.sh" "$APP_DIR/install.sh" "$APP_DIR/update.sh" 2>/dev/null || true

# Reinstall dependencies only when requirements.txt actually changed, so a
# normal code update does not spend minutes in pip on a phone.
DEPS_CHANGED=0
if [ -n "$OLD_REQUIREMENTS" ] && [ -f "$APP_DIR/requirements.txt" ]; then
  cmp -s "$OLD_REQUIREMENTS" "$APP_DIR/requirements.txt" || DEPS_CHANGED=1
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
    say "🐍 requirements.txt เปลี่ยน — กำลังติดตั้ง dependencies"
    (cd "$APP_DIR" && "$PYTHON" -m pip install -r requirements.txt) || die "ติดตั้ง dependencies ไม่สำเร็จ"
  else
    say "⚠️  ไม่พบ python — ข้ามการติดตั้ง dependencies (รัน install.sh เอง)"
  fi
fi

if [ "$RESTART" -eq 1 ]; then
  [ -x "$APP_DIR/start_web.sh" ] || die "ไม่พบ start_web.sh ที่รันได้"
  say "🔁 กำลัง restart เซิร์ฟเวอร์"
  "$APP_DIR/start_web.sh" --restart || die "restart ไม่สำเร็จ — ดู log ที่ logs/ai-web.log"
  "$APP_DIR/start_web.sh" --check || die "เซิร์ฟเวอร์ไม่ตอบหลัง restart"
else
  say "ℹ️  ข้ามการ restart (ใช้ ./start_web.sh --restart เมื่อพร้อม)"
fi

say "✅ อัพเดทเสร็จแล้ว"
