#!/bin/bash
set -euo pipefail
root="$HOME/Library/Application Support/codex-any-bot"
label='com.codex-any-bot.agent'
if [ -f "$root/current.json" ]; then
  exe=$(/usr/bin/plutil -extract executable raw -o - "$root/current.json")
  "$exe" stop-local
fi
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$label.plist"
# The local stop marker is read by detached maintenance restarts too.
mkdir -p "$root"
touch "$root/stop.request"
sleep 3
if [ "${1:-}" = --purge ]; then
  case "$root" in "$HOME/Library/Application Support/codex-any-bot") rm -rf "$root";; *) exit 1;; esac
  echo 'Application data removed. Remove the machine card in Telegram too.'
else
  echo 'Client and autostart stopped; settings retained. Use --purge to remove application data.'
fi
