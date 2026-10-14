#!/bin/bash
set -euo pipefail
server=''; code=''; update=0; version='v0.1.1'
while [ "$#" -gt 0 ]; do
  case "$1" in
    --server) server="$2"; shift 2;;
    --code) code="$2"; shift 2;;
    --update) update=1; shift;;
    --version) version="$2"; shift 2;;
    *) echo 'Unknown option' >&2; exit 1;;
  esac
done
[ "$(uname -s)" = Darwin ] || { echo 'macOS only' >&2; exit 1; }
root="$HOME/Library/Application Support/codex-any-bot"
repo='https://github.com/a06342637/codex-any-bot/releases'
if [ "$update" = 0 ] && [ -f "$root/config.json" ]; then echo 'Already installed; use --update.' >&2; exit 1; fi
if [ "$update" = 0 ] && { [ -z "$server" ] || [ -z "$code" ]; }; then echo 'Server and Code are required.' >&2; exit 1; fi
stage=$(mktemp -d)
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
  rm -rf "$stage"
}
trap finish EXIT
if [ "$update" = 1 ]; then
  curl -fLsS "$repo/latest/download/manifest.json" -o "$stage/latest.json"
  version=$(/usr/bin/plutil -extract version raw -o - "$stage/latest.json")
fi
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid version' >&2; exit 1; }
release="$repo/download/$version"
curl -fLsS "$release/manifest.json" -o "$stage/manifest.json"
mv=$(/usr/bin/plutil -extract version raw -o - "$stage/manifest.json")
[ "$mv" = "$version" ] || { echo 'Manifest version mismatch' >&2; exit 1; }
arch=$(uname -m)
case "$arch" in arm64) asset='codex-any-bot-macos-arm64.tar.gz';; x86_64) asset='codex-any-bot-macos-x64.tar.gz';; *) echo 'Unsupported architecture' >&2; exit 1;; esac
# Checksums use an additional plist-safe asset key (no periods).
key=${asset//./_}
expected=$(/usr/bin/plutil -extract "checksums.$key" raw -o - "$stage/manifest.json")
curl -fLsS "$release/$asset" -o "$stage/$asset"
actual=$(shasum -a 256 "$stage/$asset" | awk '{print $1}')
[ "$expected" = "$actual" ] || { echo 'Archive checksum mismatch' >&2; exit 1; }
destination="$root/versions/$version-$(date +%s)"
mkdir -p "$destination" "$HOME/Library/LaunchAgents"
tar -xzf "$stage/$asset" -C "$destination"
exe="$destination/codex-any-bot"
chmod +x "$exe"
"$exe" --version
if [ "$update" = 1 ]; then "$exe" stop-local; fi
if [ "$update" = 0 ]; then "$exe" join --server "$server" --code "$code" --cwd "$PWD"; fi
if [ -f "$root/current.json" ]; then cp "$root/current.json" "$root/previous.json"; fi
/usr/bin/plutil -create json "$stage/current.json"
/usr/bin/plutil -insert executable -string "$exe" "$stage/current.json"
/usr/bin/plutil -insert version -string "$version" "$stage/current.json"
mv -f "$stage/current.json" "$root/current.json"
cp "$destination/uninstall.sh" "$root/uninstall.sh"
label='com.codex-any-bot.agent'
plist="$HOME/Library/LaunchAgents/$label.plist"
# plutil escapes paths correctly, including spaces and XML metacharacters.
/usr/bin/plutil -create xml1 "$stage/agent.plist"
/usr/bin/plutil -insert Label -string "$label" "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments -json "[]" "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments.0 -string "$exe" "$stage/agent.plist"
/usr/bin/plutil -insert ProgramArguments.1 -string run "$stage/agent.plist"
/usr/bin/plutil -insert RunAtLoad -bool YES "$stage/agent.plist"
/usr/bin/plutil -insert KeepAlive -bool NO "$stage/agent.plist"
/usr/bin/plutil -insert WorkingDirectory -string "$root" "$stage/agent.plist"
/usr/bin/plutil -insert StandardErrorPath -string "$root/launch-error.log" "$stage/agent.plist"
/usr/bin/plutil -insert StandardOutPath -string "$root/launch-output.log" "$stage/agent.plist"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
cp "$stage/agent.plist" "$plist"
rm -f "$root/stop.request"
launchctl bootstrap "gui/$(id -u)" "$plist"
echo 'Installed. The client starts in the background when you sign in.'
echo "Uninstall: bash \"$root/uninstall.sh\""
