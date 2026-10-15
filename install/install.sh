#!/bin/bash
set -euo pipefail
server=''; code=''; update=0; version='v0.2.1'; autostart=1; launch=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --server) server="$2"; shift 2;;
    --code) code="$2"; shift 2;;
    --update) update=1; shift;;
    --version) version="$2"; shift 2;;
    --no-autostart) autostart=0; shift;;
    --no-launch) launch=0; shift;;
    *) echo 'Unknown option' >&2; exit 1;;
  esac
done
[ "$(uname -s)" = Darwin ] || { echo 'macOS only' >&2; exit 1; }
root="${ANYBOT_DATA_DIR:-$HOME/Library/Application Support/codex-any-bot}"
[[ "$root" = /* && "$(basename "$root")" = codex-any-bot && ! -L "$root" ]] || { echo 'Unexpected installation directory' >&2; exit 1; }
if [ -d "$root" ]; then root=$(cd "$root" && pwd -P); fi
for relative in ownership.json config.json current.json previous.json cache versions; do
  [ ! -L "$root/$relative" ] || { echo 'Refusing a linked application path' >&2; exit 1; }
done
marker="$root/ownership.json"
registered=0
if [ -f "$marker" ]; then
  [ "$(/usr/bin/plutil -extract app raw -o - "$marker")" = codex-any-bot ] && [ "$(/usr/bin/plutil -extract schema raw -o - "$marker")" = 1 ] || { echo 'Unsupported ownership marker' >&2; exit 1; }
  saved_autostart=$(/usr/bin/plutil -extract autostart raw -o - "$marker")
  if [ "$saved_autostart" = 1 ] || [ "$saved_autostart" = true ]; then registered=1; fi
elif [ -d "$root" ] && [ -n "$(ls -A "$root")" ]; then
  [ "$update" = 1 ] || { echo 'Non-empty directory has no ownership marker; its files were not changed.' >&2; exit 1; }
  legacy_token=$(/usr/bin/plutil -extract token raw -o - "$root/config.json" 2>/dev/null) || exit 1
  legacy_id=$(/usr/bin/plutil -extract device_id raw -o - "$root/config.json" 2>/dev/null) || exit 1
  legacy_server=$(/usr/bin/plutil -extract server raw -o - "$root/config.json" 2>/dev/null) || exit 1
  legacy_protocol=$(/usr/bin/plutil -extract protocol raw -o - "$root/config.json" 2>/dev/null) || exit 1
  legacy_exe=$(/usr/bin/plutil -extract executable raw -o - "$root/current.json" 2>/dev/null) || exit 1
  [[ "$legacy_token" =~ ^[a-f0-9]{64}$ && "$legacy_id" =~ ^[a-f0-9]{16}$ && "$legacy_server" = https://* && "$legacy_protocol" = 1 ]] || { echo 'Cannot verify legacy ownership' >&2; exit 1; }
  case "$legacy_exe" in "$root"/versions/*/codex-any-bot) ;; *) echo 'Invalid legacy executable' >&2; exit 1;; esac
  legacy_part="$legacy_exe"
  while [ "$legacy_part" != "$root" ]; do
    [ ! -L "$legacy_part" ] || { echo 'Linked legacy executable refused' >&2; exit 1; }
    legacy_part=$(dirname "$legacy_part")
  done
  [ -f "$legacy_exe" ] || exit 1
  legacy_parent=$(cd "$(dirname "$legacy_exe")" && pwd -P)
  case "$legacy_parent" in "$root"/versions/*) ;; *) exit 1;; esac
  unset legacy_token
  registered=1
fi
repo='https://github.com/a06342637/codex-any-bot/releases'
if [ "$update" = 0 ] && [ -f "$root/config.json" ]; then echo 'Already installed; update from Telegram or use --update.' >&2; exit 1; fi
created_root=0
if [ ! -d "$root" ]; then created_root=1; fi
mkdir -p "$root/cache"
[ ! -L "$root/cache" ] || { echo 'Refusing linked cache directory' >&2; exit 1; }
if [ ! -f "$marker" ]; then printf '{"app":"codex-any-bot","schema":1,"autostart":%s}\n' "$registered" > "$marker"; fi
stage=$(mktemp -d "$root/cache/install.XXXXXX")
rollback=''
if [ "$update" = 1 ] && [ -f "$root/current.json" ]; then
  rollback=$(/usr/bin/plutil -extract executable raw -o - "$root/current.json")
fi
finish() {
  result=$?
  if [ "$result" != 0 ] && [ -n "$rollback" ] && [ -x "$rollback" ]; then
    rm -f "$root/stop.request"
    nohup "$rollback" run </dev/null >>"$root/update-error.log" 2>&1 &
  fi
  case "$stage" in "$root"/cache/install.*) [ ! -L "$stage" ] && rm -rf "$stage";; *) echo 'Unexpected staging path' >&2;; esac
  if [ "$created_root" = 1 ] && [ ! -f "$root/uninstall.sh" ] && [ ! -f "$root/config.json" ]; then
    if [ ! -L "$root" ] && [ "$(/usr/bin/plutil -extract app raw -o - "$root/ownership.json")" = codex-any-bot ]; then rm -rf "$root"; fi
  fi
  if [ "$result" != 0 ]; then
    echo "Installation did not finish. Log: $root/agent.log" >&2
    echo "Cleanup: bash \"$root/uninstall.sh\" --purge" >&2
  fi
}
trap finish EXIT
if [ "$update" = 1 ]; then
  curl -fLsS "$repo/latest/download/manifest.json" -o "$stage/latest.json"
  version=$(/usr/bin/plutil -extract version raw -o - "$stage/latest.json")
fi
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid version' >&2; exit 1; }
release="$repo/download/$version"
curl -fLsS "$release/manifest.json" -o "$stage/manifest.json"
manifest_version=$(/usr/bin/plutil -extract version raw -o - "$stage/manifest.json")
[ "$manifest_version" = "$version" ] || { echo 'Manifest version mismatch' >&2; exit 1; }
case "$(uname -m)" in arm64) asset='codex-any-bot-macos-arm64.tar.gz';; x86_64) asset='codex-any-bot-macos-x64.tar.gz';; *) echo 'Unsupported architecture' >&2; exit 1;; esac
key=${asset//./_}
expected=$(/usr/bin/plutil -extract "checksums.$key" raw -o - "$stage/manifest.json")
curl -fLsS "$release/$asset" -o "$stage/$asset"
actual=$(shasum -a 256 "$stage/$asset" | awk '{print $1}')
[ "$expected" = "$actual" ] || { echo 'Archive checksum mismatch' >&2; exit 1; }
destination="$root/versions/$version-$(uuidgen)"
mkdir -p "$destination"
tar -xzf "$stage/$asset" -C "$destination"
exe="$destination/codex-any-bot"
chmod +x "$exe"
cp "$destination/uninstall.sh" "$root/uninstall.sh"
"$exe" --version
if [ "$update" = 1 ]; then
  "$exe" stop-local
else
  args=(setup --cwd "$PWD")
  if [ -n "$code" ]; then args=(join --code "$code" --cwd "$PWD"); fi
  if [ -n "$server" ]; then args+=(--server "$server"); fi
  "$exe" "${args[@]}"
fi
if [ -f "$root/current.json" ]; then cp "$root/current.json" "$root/previous.json"; fi
/usr/bin/plutil -create xml1 "$stage/current.plist"
/usr/bin/plutil -insert executable -string "$exe" "$stage/current.plist"
/usr/bin/plutil -insert version -string "$version" "$stage/current.plist"
/usr/bin/plutil -convert json -o "$stage/current.json" "$stage/current.plist"
label='com.codex-any-bot.agent'
plist="$HOME/Library/LaunchAgents/$label.plist"
/usr/bin/plutil -create xml1 "$stage/agent.plist"
/usr/bin/plutil -insert Label -string "$label" "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments -json '[]' "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments.0 -string "$exe" "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments.1 -string run "$stage/agent.plist"
/usr/bin/plutil -insert RunAtLoad -bool YES "$stage/agent.plist"
/usr/bin/plutil -insert KeepAlive -bool NO "$stage/agent.plist"
/usr/bin/plutil -insert WorkingDirectory -string "$root" "$stage/agent.plist"
/usr/bin/plutil -insert StandardErrorPath -string "$root/launch-error.log" "$stage/agent.plist"
/usr/bin/plutil -insert StandardOutPath -string "$root/launch-output.log" "$stage/agent.plist"
/usr/bin/plutil -lint "$stage/agent.plist" >/dev/null
if [ "$autostart" = 1 ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  cp "$stage/agent.plist" "$plist"
  registered=1
fi
printf '{"app":"codex-any-bot","schema":1,"autostart":%s}\n' "$registered" > "$stage/ownership.json"
mv -f "$stage/ownership.json" "$marker"
mv -f "$stage/current.json" "$root/current.json"
rm -f "$root/stop.request"
if [ "$launch" = 1 ]; then
  if [ "$autostart" = 1 ]; then launchctl bootstrap "gui/$(id -u)" "$plist"
  else nohup "$exe" run </dev/null >/dev/null 2>&1 & fi
  "$exe" wait-online --timeout 20 || true
fi
echo "Install directory: $root"
echo "Log: $root/agent.log"
echo "Config (private): $root/config.json"
echo "Status: \"$exe\" status"
echo "Uninstall: bash \"$root/uninstall.sh\" --purge"
