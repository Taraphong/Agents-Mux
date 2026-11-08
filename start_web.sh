#!/bin/bash
# Start / check / restart the AI Web server (Termux and Linux).
#
# Usage:
#   startweb --check     Check whether the server is running
#   startweb --start     Start the server if it is stopped
#   startweb --restart   Stop and start the server (use after every deploy)
#   startweb --stop      Stop the server
#
# ติดตั้งเป็นคำสั่งสั้น (ทำครั้งเดียวบน Termux):
#   ln -sf ~/ai-web/start_web.sh "$PREFIX/bin/startweb"

set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

status_line() {
  echo "✅ Running (PID: $(pid_list)) — http://127.0.0.1:$PORT"
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
  *)
    echo "ใช้: $(basename "$0") --check | --start | --restart | --stop"
    ;;
esac
