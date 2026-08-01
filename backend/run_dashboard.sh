#!/bin/bash
# LeadMind dashboard watchdog — keeps the Python web_dashboard.py alive forever.
# Started as a mini-service so the platform's process manager keeps it running.
LOG=/tmp/leadmind-dashboard.log

cd /home/z/my-project/leadmind-mcp
source .venv/bin/activate
export DEMO_MODE=true
export DEMO_RESET_INTERVAL_SEC=14400
export PORT=8000

echo "[$(date)] Watchdog starting web_dashboard.py (port 8000)..." >> "$LOG"

while true; do
    python -u web_dashboard.py >> "$LOG" 2>&1
    EXIT_CODE=$?
    echo "[$(date)] web_dashboard.py exited (code=$EXIT_CODE). Restarting in 2s..." >> "$LOG"
    sleep 2
done
