#!/bin/bash
# Start AI Web server on Termux
# Usage: startweb
#       startweb --check    Check if running
#       startweb --start    Start if stopped

case "$1" in
  --check) pgrep -f "python3 app.py" >/dev/null 2>&1 && echo "✅ Running" || echo "❌ Stopped" ;;
  --start) pgrep -f "python3 app.py" || python3 app.py & sleep 1 && pgrep -f "python3 app.py" && echo "✅ Started" || echo "❌ Failed" ;;
  *) echo "ใช้: startweb --check | startweb --start" ;;
esac