#!/bin/bash
# notifier/run_discord_bot.sh
#
# Keeps notifier/discord_bot.py running, restarting it if it ever crashes
# or loses its Discord connection. Intended to be started once at boot.

REPO_ROOT="/home/tankionlinefirstseargent/projects/dota-website"
PYTHON_BIN="/home/tankionlinefirstseargent/.pyenv/shims/python"
LOGFILE="$REPO_ROOT/logs/discord_bot_wrapper.log"

mkdir -p "$REPO_ROOT/logs"
cd "$REPO_ROOT" || exit 1

while true; do
    echo "=== $(date): starting discord_bot.py ===" >> "$LOGFILE"
    "$PYTHON_BIN" notifier/discord_bot.py >> "$LOGFILE" 2>&1
    echo "=== $(date): discord_bot.py exited, restarting in 10s ===" >> "$LOGFILE"
    sleep 10
done
