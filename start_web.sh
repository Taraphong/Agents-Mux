#!/bin/bash
# Start / check / restart the AI Web server (Termux and Linux).
#
# Usage:
#   startweb --check     Check whether the server is running
#   startweb --start     Start the server if it is stopped
#   startweb --restart   Stop and start the server (use after every deploy)
#   startweb --stop      Stop the server
#   startweb --pair      Generate a single-use Pairing Key (web auth)
#   startweb --make-cert [ip]  Create a self-signed HTTPS certificate
#
# ติดตั้งเป็นคำสั่งสั้น (ทำครั้งเดียวบน Termux):
#   ln -sf ~/ai-web/start_web.sh "$PREFIX/bin/startweb"

set -u

# Resolve symlinks so the documented install works:
#   ln -sf ~/ai-web/start_web.sh "$PREFIX/bin/startweb"
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
APP_FILE="$APP_DIR/app.py"
LOG_FILE="${AI_WEB_LOG:-$APP_DIR/debug-ai-web.log}"
PORT="${PORT:-5000}"

# Use a [p] character class so pgrep never matches this script's own command
# line (otherwise --restart could kill the shell that is running it).
SERVER_PATTERN='[p]ython[0-9.]* .*[a]pp\.py'

if [ -x "$APP_DIR/.venv/bin/python" ]; then
  PYTHON="$APP_DIR/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python || true)"
fi

server_pids() {
  pgrep -f "$SERVER_PATTERN" 2>/dev/null || true
}

is_running() {
  [ -n "$(server_pids)" ]
}

pid_list() {
  server_pids | tr '\n' ' ' | sed 's/ *$//'
}

process_start_epoch() {
  local pid="$1" etimes start_ticks btime hz
  # Termux/Android blocks /proc/stat, but ps -o etimes works there.
  etimes="$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')"
  case "$etimes" in
    ''|*[!0-9]*) ;;
    *) echo $(( $(date +%s) - etimes )); return 0 ;;
  esac
  # /proc/<pid> is created when the process starts.
  if start_ticks="$(stat -c %Y "/proc/$pid" 2>/dev/null)"; then
    [ -n "$start_ticks" ] && { echo "$start_ticks"; return 0; }
  fi
  start_ticks="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" || return 1
  [ -n "$start_ticks" ] || return 1
  btime="$(awk '/^btime/ {print $2}' /proc/stat 2>/dev/null)" || return 1
  [ -n "$btime" ] || return 1
  hz="$(getconf CLK_TCK 2>/dev/null || echo 100)"
  echo $((btime + start_ticks / hz))
}

file_mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || true
}

# Flask runs with debug=False, so app.py and Jinja templates are loaded once
# at startup. If deployed files are newer than the process, new features will
# not appear until the server is restarted.
warn_if_stale() {
  local pid epoch latest=0 file mtime
  for file in "$APP_FILE" "$APP_DIR/templates/index.html"; do
    [ -f "$file" ] || continue
    mtime="$(file_mtime "$file")"
    if [ -n "$mtime" ] && [ "$mtime" -gt "$latest" ]; then
      latest="$mtime"
    fi
  done
  [ "$latest" -gt 0 ] || return 0
  for pid in $(server_pids); do
    epoch="$(process_start_epoch "$pid")" || continue
    [ -n "$epoch" ] || continue
    if [ "$epoch" -lt "$latest" ]; then
      echo "⚠️  โค้ดใหม่กว่ารอบที่ process เริ่มทำงาน — รัน --restart เพื่อให้ feature ใหม่ขึ้น"
      return 0
    fi
  done
}

tls_scheme() {
  if [ -f "$APP_DIR/.env" ] && grep -Eq '^[[:space:]]*AI_WEB_TLS_(CERT|KEY)=[^[:space:]]' "$APP_DIR/.env"; then
    echo "https"
  else
    echo "http"
  fi
}

status_line() {
  echo "✅ Running (PID: $(pid_list)) — $(tls_scheme)://127.0.0.1:$PORT"
}

start_server() {
  local i
  if is_running; then
    status_line
    warn_if_stale
    return 0
  fi
  if [ ! -f "$APP_FILE" ]; then
    echo "❌ ไม่พบไฟล์ $APP_FILE"
    return 1
  fi
  if [ -z "$PYTHON" ]; then
    echo "❌ ไม่พบ python3 หรือ .venv/bin/python"
    return 1
  fi
  cd "$APP_DIR" || return 1
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PYTHON" app.py >>"$LOG_FILE" 2>&1 </dev/null &
  else
    nohup "$PYTHON" app.py >>"$LOG_FILE" 2>&1 </dev/null &
    disown 2>/dev/null || true
  fi
  for i in $(seq 1 20); do
    sleep 0.25
    is_running && break
  done
  if is_running; then
    status_line
    echo "   log: $LOG_FILE"
    return 0
  fi
  echo "❌ เริ่มไม่สำเร็จ — ดู log: $LOG_FILE"
  tail -n 20 "$LOG_FILE" 2>/dev/null
  return 1
}

stop_server() {
  local i
  if ! is_running; then
    echo "❌ Stopped"
    return 0
  fi
  # shellcheck disable=SC2046
  kill $(server_pids) 2>/dev/null || true
  for i in $(seq 1 20); do
    sleep 0.25
    is_running || break
  done
  if is_running; then
    # shellcheck disable=SC2046
    kill -9 $(server_pids) 2>/dev/null || true
    sleep 0.5
  fi
  if is_running; then
    echo "❌ หยุดไม่สำเร็จ (PID: $(pid_list))"
    return 1
  fi
  echo "✅ Stopped"
}

make_cert() {
  local host="${1:-}" dir="$APP_DIR/certs" ip san cn
  if ! command -v openssl >/dev/null 2>&1; then
    echo "❌ ไม่พบ openssl — ติดตั้งก่อน: pkg install openssl-tool"
    return 1
  fi
  ip="$host"
  if [ -z "$ip" ]; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')"
  fi
  if [ -z "$ip" ]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [ -z "$ip" ]; then
    # Termux/Android: no `ip route` privileges, so read the interface address.
    ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127\./ {print $2; exit}')"
  fi
  if [ -z "$ip" ]; then
    ip="$(getprop dhcp.wlan0.ipaddress 2>/dev/null)"
  fi
  if [ -z "$ip" ]; then
    echo "❌ หา IP ของเครื่องไม่พบ — ระบุเอง: $(basename "$0") --make-cert 192.168.2.40"
    return 1
  fi
  cn="$ip"
  san="DNS:localhost,IP:127.0.0.1"
  [ "$ip" = "127.0.0.1" ] || san="$san,IP:$ip"
  mkdir -p "$dir" || return 1
  if ! openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$dir/key.pem" -out "$dir/cert.pem" \
    -subj "/CN=$cn" -addext "subjectAltName=$san" >/dev/null 2>&1; then
    echo "❌ สร้างใบรับรองไม่สำเร็จ (openssl เวอร์ชันนี้อาจไม่รองรับ -addext)"
    return 1
  fi
  chmod 600 "$dir/key.pem"
  echo "✅ สร้างใบรับรองแล้ว: $dir/cert.pem และ $dir/key.pem (ใช้ได้กับ $cn)"
  echo "   เพิ่มใน .env:"
  echo "   AI_WEB_TLS_CERT=$dir/cert.pem"
  echo "   AI_WEB_TLS_KEY=$dir/key.pem"
  echo "   แล้วรัน: $(basename "$0") --restart"
  echo "   หมายเหตุ: ใบรับรอง self-signed จะทำให้เบราว์เซอร์เตือนความปลอดภัยครั้งแรก"
}

pair_device() {
  if [ -z "$PYTHON" ]; then
    echo "❌ ไม่พบ python3 หรือ .venv/bin/python"
    return 1
  fi
  cd "$APP_DIR" || return 1
  "$PYTHON" app.py --pairing-key
}

check_server() {
  if is_running; then
    status_line
    warn_if_stale
  else
    echo "❌ Stopped"
    return 1
  fi
}

case "${1:-}" in
  --check) check_server ;;
  --start) start_server ;;
  --restart) stop_server && start_server ;;
  --stop) stop_server ;;
  --pair) pair_device ;;
  --make-cert) make_cert "${2:-}" ;;
  *)
    echo "ใช้: $(basename "$0") --check | --start | --restart | --stop | --pair | --make-cert [ip]"
    ;;
esac
