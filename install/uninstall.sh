#!/bin/bash
set -euo pipefail
keep=0
case "${1:---purge}" in --purge) ;; --keep-data) keep=1;; *) echo 'Use --purge or --keep-data' >&2; exit 1;; esac
root=$(cd "$(dirname "$0")" && pwd -P)
expected="${ANYBOT_DATA_DIR:-$HOME/Library/Application Support/codex-any-bot}"
[[ "$expected" = /* && "$(basename "$root")" = codex-any-bot && ! -L "$expected" ]] || { echo 'Unexpected installation directory' >&2; exit 1; }
expected=$(cd "$expected" && pwd -P)
[ "$root" = "$expected" ] || { echo 'Run the installed uninstaller' >&2; exit 1; }
marker="$root/ownership.json"
[ "$(/usr/bin/plutil -extract app raw -o - "$marker")" = codex-any-bot ] || { echo 'Ownership marker missing' >&2; exit 1; }
autostart=$(/usr/bin/plutil -extract autostart raw -o - "$marker")
exe=''
if [ -f "$root/current.json" ]; then exe=$(/usr/bin/plutil -extract executable raw -o - "$root/current.json"); fi
if [ ! -x "$exe" ]; then
  for candidate in "$root"/versions/*/codex-any-bot; do
    if [ -x "$candidate" ]; then exe="$candidate"; break; fi
  done
fi
if [ -x "$exe" ]; then
  case "$exe" in "$root"/versions/*/codex-any-bot) ;; *) echo 'Unexpected executable path' >&2; exit 1;; esac
  "$exe" stop-local
fi
label='com.codex-any-bot.agent'
if [ "$autostart" = 1 ] || [ "$autostart" = true ]; then
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
fi
if [ "$keep" = 1 ]; then echo "Stopped and removed autostart. Data retained at $root"; exit 0; fi
cloud_pending=0; cache_pending=0
if [ -x "$exe" ]; then
  "$exe" forget || cloud_pending=1
  "$exe" clean-cache || cache_pending=1
elif [ -f "$root/config.json" ]; then
  cloud_pending=1
fi
[ "$(cd "$root" && pwd -P)" = "$expected" ] && [ "$(/usr/bin/plutil -extract app raw -o - "$marker")" = codex-any-bot ] || exit 1
rm -rf "$root"
echo 'Local client, versions, configuration, logs, cache and autostart removed.'
if [ "$cloud_pending" = 1 ]; then echo 'Cloud binding could not be removed. Use Telegram > Machine settings > Remove device.' >&2; fi
if [ "$cache_pending" = 1 ]; then echo 'Some identified legacy temporary files could not be removed; see the paths printed above.' >&2; fi
