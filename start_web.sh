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
# Install as a short command (one-time on Termux):
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
# Keep the default log inside logs/, which is ignored by Git and excluded
# from the rsync deploy, so diagnostic output never ends up in the repo.
LOG_FILE="${AI_WEB_LOG:-$APP_DIR/logs/ai-web.log}"
PORT="${PORT:-5000}"

# Use a [p] character class so pgrep never matches this script's own command
# line (otherwise --restart could kill the shell that is running it).
SERVER_PATTERN='[p]ython[0-9.]* .*[a]pp\.py'

# Keep only processes that run from this project directory. Another project's
# `python app.py` must not be reported as this server or killed by --stop.
# When /proc/<pid>/cwd is unreadable (some Android builds) fall back to the
# previous pattern-only behaviour instead of losing the running server.

if [ -x "$APP_DIR/.venv/bin/python" ]; then
  PYTHON="$APP_DIR/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python || true)"
fi

server_pids() {
  local pid cwd
  for pid in $(pgrep -f "$SERVER_PATTERN" 2>/dev/null || true); do
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    if [ -n "$cwd" ] && [ "$cwd" != "$APP_DIR" ]; then
      continue
    fi
    echo "$pid"
  done
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

# Flask runs with debug=False, so app.py and the Jinja templates are loaded
# once at startup. If those deployed files are newer than the process, new
# features will not appear until the server is restarted. Page CSS and
# JavaScript (templates/<page>/*.css and *.js) are read from disk on every
# request, so they never need a restart.
warn_if_stale() {
  local pid epoch latest=0 file mtime
  while IFS= read -r file; do
    [ -f "$file" ] || continue
    mtime="$(file_mtime "$file")"
    if [ -n "$mtime" ] && [ "$mtime" -gt "$latest" ]; then
      latest="$mtime"
    fi
  done < <(printf '%s\n' "$APP_FILE"; find "$APP_DIR/templates" -type f -name '*.html' 2>/dev/null)
  [ "$latest" -gt 0 ] || return 0
  for pid in $(server_pids); do
    epoch="$(process_start_epoch "$pid")" || continue
    [ -n "$epoch" ] || continue
    if [ "$epoch" -lt "$latest" ]; then
      echo "⚠️  Code is newer than the running process — run --restart to load new features"
      return 0
    fi
  done
}

# Read one KEY=value entry from .env the way python-dotenv does for the common
# cases: the last entry wins, surrounding quotes are removed, and an unquoted
# value stops at a " #" comment.
dotenv_value() {
  local key="$1" line value
  [ -f "$APP_DIR/.env" ] || return 0
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$APP_DIR/.env" 2>/dev/null | tail -n 1)"
  [ -n "$line" ] || return 0
  value="${line#*=}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  case "$value" in
    \"*\") value="${value#\"}"; value="${value%%\"*}" ;;
    \'*\') value="${value#\'}"; value="${value%%\'*}" ;;
    *) value="${value%%[[:space:]]#*}" ;;
  esac
  printf '%s' "${value%"${value##*[![:space:]]}"}"
}

# Effective value app.py sees: an exported variable wins over .env because
# python-dotenv does not override the environment. Quotes are not part of the
# value, so a quoted empty string counts as empty.
tls_config_value() {
  local key="$1" value
  if value="$(printenv "$key")"; then
    :
  else
    value="$(dotenv_value "$key")"
  fi
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  case "$value" in
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
  esac
  printf '%s' "$value"
}

# Match tls_configuration() in app.py, including its precedence: certificate
# files first, then the adhoc certificate, otherwise plain HTTP.
tls_scheme() {
  local cert key adhoc
  cert="$(tls_config_value AI_WEB_TLS_CERT)"
  key="$(tls_config_value AI_WEB_TLS_KEY)"
  if [ -n "$cert" ] || [ -n "$key" ]; then
    # app.py refuses to start when only one of the pair is set.
    if [ -n "$cert" ] && [ -n "$key" ]; then
      echo "https"
    else
      echo "http"
    fi
    return 0
  fi
  adhoc="$(tls_config_value AI_WEB_TLS_ADHOC)"
  case "$(printf '%s' "$adhoc" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) echo "https" ;;
    *) echo "http" ;;
  esac
}

status_line() {
  echo "✅ Running (PID: $(pid_list)) — $(tls_scheme)://127.0.0.1:$PORT"
}

# A live PID is not proof that the server works: app.py can die during import
# (a missing dependency in .venv, for example) and still look alive for a few
# hundred milliseconds. Ask the port instead, so --start cannot report a
# healthy server that died on startup.
server_answers() {
  local scheme="${1:-$(tls_scheme)}"
  local max_time="${2:-2}"
  if command -v curl >/dev/null 2>&1; then
    curl -sk -o /dev/null --noproxy 127.0.0.1 --max-time "$max_time" "$scheme://127.0.0.1:$PORT/" 2>/dev/null
    return $?
  fi
  # Minimal Termux installs may not have curl; bash can still open the port.
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null
}

# True when something already listens on the port. app.py would then die on
# the bind, and the other program's answer could make a health check pass.
port_is_busy() {
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null
}

start_server() {
  local i misses=0 serving=0 scheme log_offset=0
  if is_running; then
    if server_answers; then
      status_line
      warn_if_stale
      return 0
    else
      echo "❌ Not answering on $(tls_scheme)://127.0.0.1:$PORT — process is alive but not responding"
      return 1
    fi
  fi
  if [ ! -f "$APP_FILE" ]; then
    echo "❌ App file not found: $APP_FILE"
    return 1
  fi
  if [ -z "$PYTHON" ]; then
    echo "❌ python3 or .venv/bin/python not found"
    return 1
  fi
  if port_is_busy; then
    echo "❌ Port $PORT is already in use by another program — stop it or run with PORT=<free port>"
    return 1
  fi
  cd "$APP_DIR" || return 1
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  # Only the output of this attempt is useful when it fails; older tracebacks
  # in the log would hide the real cause.
  if [ -f "$LOG_FILE" ]; then
    log_offset="$(wc -c <"$LOG_FILE" 2>/dev/null | tr -d ' ')"
    case "$log_offset" in ''|*[!0-9]*) log_offset=0 ;; esac
  fi
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PYTHON" app.py >>"$LOG_FILE" 2>&1 </dev/null &
  else
    nohup "$PYTHON" app.py >>"$LOG_FILE" 2>&1 </dev/null &
    disown 2>/dev/null || true
  fi
  scheme="$(tls_scheme)"
  # Wait for an answer, not just for a PID. 10 s is enough for Flask to import
  # on a phone; a process that exits twice in a row is a startup failure.
  START_SECONDS="$(date +%s)"
  END_TIME=$((START_SECONDS + 10))
  while [ "$(date +%s)" -lt "$END_TIME" ]; do
    sleep 0.25
    if ! is_running; then
      misses=$((misses + 1))
      [ "$misses" -ge 2 ] && break
      continue
    fi
    misses=0
    REMAINING=$((END_TIME - $(date +%s)))
    if [ "$REMAINING" -le 0 ]; then
      break
    fi
    if server_answers "$scheme" "$REMAINING"; then
      serving=1
      break
    fi
  done
  # Another process can hold the port while app.py dies on the bind, so a
  # single successful probe is not enough: confirm the process survives a
  # short settle window before reporting it as running.
  if [ "$serving" -eq 1 ]; then
    sleep 0.5
    if is_running; then
      status_line
      echo "   log: $LOG_FILE"
      return 0
    fi
  fi
  if is_running; then
    echo "❌ Not answering on $scheme://127.0.0.1:$PORT after 10s — see log: $LOG_FILE"
  else
    echo "❌ Failed to start (the process exited) — see log: $LOG_FILE"
  fi
  if [ "$log_offset" -gt 0 ]; then
    tail -c +$((log_offset + 1)) "$LOG_FILE" 2>/dev/null | tail -n 20
  else
    tail -n 20 "$LOG_FILE" 2>/dev/null
  fi
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
    echo "❌ Failed to stop (PID: $(pid_list))"
    return 1
  fi
  echo "✅ Stopped"
}

make_cert() {
  local host="${1:-}" dir="$APP_DIR/certs" ip san cn
  if ! command -v openssl >/dev/null 2>&1; then
    echo "❌ openssl not found — install it first: pkg install openssl-tool"
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
    echo "❌ Could not detect the machine IP — specify it: $(basename "$0") --make-cert 192.168.2.40"
    return 1
  fi
  cn="$ip"
  san="DNS:localhost,IP:127.0.0.1"
  [ "$ip" = "127.0.0.1" ] || san="$san,IP:$ip"
  mkdir -p "$dir" || return 1
  if ! openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$dir/key.pem" -out "$dir/cert.pem" \
    -subj "/CN=$cn" -addext "subjectAltName=$san" >/dev/null 2>&1; then
    echo "❌ Failed to create the certificate (this openssl version may not support -addext)"
    return 1
  fi
  chmod 600 "$dir/key.pem"
  echo "✅ Certificate created: $dir/cert.pem and $dir/key.pem (valid for $cn)"
  echo "   Add to .env:"
  echo "   AI_WEB_TLS_CERT=$dir/cert.pem"
  echo "   AI_WEB_TLS_KEY=$dir/key.pem"
  echo "   Then run: $(basename "$0") --restart"
  echo "   Note: a self-signed certificate makes the browser show a security warning on first visit"
}

pair_device() {
  if [ -z "$PYTHON" ]; then
    echo "❌ python3 or .venv/bin/python not found"
    return 1
  fi
  cd "$APP_DIR" || return 1
  "$PYTHON" app.py --pairing-key
}

check_server() {
  if is_running; then
    status_line
    if ! server_answers; then
      echo "⚠️  The process is alive but nothing answers on port $PORT — see log: $LOG_FILE"
      return 1
    fi
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
    echo "Usage: $(basename "$0") --check | --start | --restart | --stop | --pair | --make-cert [ip]"
    ;;
esac
