#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="/tmp/chirptype.pid"
LOG_FILE="/tmp/chirptype.out"

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Already running (PID: $(cat "$PID_FILE"))"
        return
    fi
    cd "$SCRIPT_DIR"
    nohup uv run python chirptype.py --quiet > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Started (PID: $!)"
}

stop() {
    if [ -f "$PID_FILE" ] && kill "$(cat "$PID_FILE")" 2>/dev/null; then
        rm "$PID_FILE"
        echo "Stopped"
    else
        echo "Not running"
    fi
}

case "${1:-start}" in
    start)  start ;;
    stop)   stop ;;
    logs)   tail -f "$LOG_FILE" ;;
    *)      echo "Usage: $0 [start|stop|logs]" ;;
esac
