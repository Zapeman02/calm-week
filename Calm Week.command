#!/bin/zsh
cd "$(dirname "$0")"
URL="http://localhost:8765"
if ! curl -s "$URL/api/heartbeat" >/dev/null; then
  nohup python3 BE/server.py >data/server.log 2>&1 &
  for i in {1..50}; do curl -s "$URL/api/heartbeat" >/dev/null && break; sleep 0.1; done
fi
for app in "Chromium" "Google Chrome" "Brave Browser" "Microsoft Edge"; do
  if open -Ra "$app" 2>/dev/null; then
    open -na "$app" --args --app="$URL"
    exit 0
  fi
done
open -a Safari "$URL"
