#!/usr/bin/env bash
# ติดตั้ง AI Web แบบอัตโนมัติ (Termux / Linux / macOS)
#
# ใช้งาน:
#   bash install.sh
#
# สคริปต์จะสร้าง .venv ติดตั้ง dependencies สร้าง .env จาก .env.example
# และเตรียมโฟลเดอร์ที่จำเป็น โดยไม่เขียนทับ .env หรือการตั้งค่าเดิม

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

# ---------- 1. ตรวจสอบ Python ----------
PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
[ -n "$PYTHON_BIN" ] || die "ไม่พบ Python — ติดตั้งก่อน: pkg install python (Termux) หรือ sudo apt install python3 python3-venv"

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  die "ต้องใช้ Python 3.10 ขึ้นไป (พบ $("$PYTHON_BIN" --version 2>&1))"
fi
info "ใช้ $("$PYTHON_BIN" --version 2>&1) ที่ $(command -v "$PYTHON_BIN")"

# ---------- 2. สร้าง virtual environment ----------
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  info "สร้าง .venv"
  "$PYTHON_BIN" -m venv .venv || die "สร้าง .venv ไม่สำเร็จ — บน Debian/Ubuntu ให้ติดตั้ง python3-venv"
else
  info "พบ .venv เดิม ใช้ต่อ"
fi

VENV_PY="$APP_DIR/.venv/bin/python"
[ -x "$VENV_PY" ] || die "ไม่พบ $VENV_PY"

# ---------- 3. ติดตั้ง dependencies ----------
info "อัปเดต pip"
"$VENV_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

info "ติดตั้ง dependencies จาก requirements.txt (อาจใช้เวลาสักครู่)"
"$VENV_PY" -m pip install --quiet -r requirements.txt || die "ติดตั้ง dependencies ไม่สำเร็จ — ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่"

# ---------- 4. ไฟล์ตั้งค่าและโฟลเดอร์ ----------
if [ ! -f .env ]; then
  cp .env.example .env
  info "สร้าง .env จาก .env.example"
else
  info "พบ .env เดิม ไม่เขียนทับ"
fi

mkdir -p logs history

chmod +x start_web.sh 2>/dev/null || true

# ---------- 5. คำสั่ง startweb (Termux) ----------
LINKED=""
if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ] && [ -d /data/data/com.termux ]; then
  ln -sf "$APP_DIR/start_web.sh" "$PREFIX/bin/startweb" && LINKED="$PREFIX/bin/startweb"
fi

# ---------- 6. สรุป ----------
ok "ติดตั้งเสร็จสิ้น"
printf '\n'
printf 'ขั้นตอนถัดไป:\n'
printf '  1) ใส่ API key ของผู้ให้บริการใน %s\n' "$APP_DIR/.env"
printf '  2) เริ่มเซิร์ฟเวอร์:  ./start_web.sh --start\n'
if [ -n "$LINKED" ]; then
  printf '     หรือใช้คำสั่งสั้น:  startweb --start  (ติดตั้งไว้ที่ %s)\n' "$LINKED"
fi
printf '  3) เปิดเว็บที่ http://127.0.0.1:5000\n'
printf '     เครื่องอื่นในวงเดียวกันใช้ http://<IP-ของเครื่องนี้>:5000\n'
printf '\n'
printf 'หมายเหตุ: ระบบไม่มีหน้า login — เปิดใช้เฉพาะเครือข่ายที่เชื่อถือได้\n'
