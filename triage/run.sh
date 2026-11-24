#!/bin/sh
# Supervisor: restarts the bot if it crashes. Usage: TELEGRAM_BOT_TOKEN=... ./run.sh
cd "$(dirname "$0")" || exit 1
while true; do
  python3 bot.py
  echo "bot exited ($?), restarting in 5s" >&2
  sleep 5
done
