#!/usr/bin/env bash
# Install two LaunchAgents:
#   com.nmp-dsci.pt-collect  — every 5 minutes: `pt collect && pt rollup`
#     (plus `pt sync push` when PT_S3_BUCKET is set, and a daily narrative
#     refresh on the Claude subscription when ~/.env has CLAUDE_CODE_OAUTH_TOKEN)
#   com.nmp-dsci.pt-refresh  — every 30 minutes, but `pt refresh` itself no-ops
#     until the UTC day turns, so the full re-read and rebuild happens once per
#     UTC day. Checking the date beats a fixed local hour: launchd calendar
#     intervals are local, so DST would drift them twice a year.
# Logs to ~/.pt/collect.log and ~/.pt/refresh.log.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
UV="$(command -v uv)"
PLIST="$HOME/Library/LaunchAgents/com.nmp-dsci.pt-collect.plist"
mkdir -p "$HOME/.pt"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nmp-dsci.pt-collect</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd "$REPO" &amp;&amp; "$UV" run pt collect &amp;&amp; { "$UV" run pt screen-backfill --days 3 || true; } &amp;&amp; "$UV" run pt rollup &amp;&amp; { [ -z "\${PT_S3_BUCKET:-}" ] || "$UV" run pt sync push; } &amp;&amp; { [ ! -f "$HOME/.env" ] || { set -a; . "$HOME/.env"; set +a; "$UV" run pt weekly --max-age-hours 24; }; }</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/.pt/collect.log</string>
  <key>StandardErrorPath</key><string>$HOME/.pt/collect.log</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict></plist>
PL
REFRESH_PLIST="$HOME/Library/LaunchAgents/com.nmp-dsci.pt-refresh.plist"
cat > "$REFRESH_PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nmp-dsci.pt-refresh</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd "$REPO" &amp;&amp; { [ ! -f "$HOME/.env" ] || { set -a; . "$HOME/.env"; set +a; }; } &amp;&amp; "$UV" run pt refresh &amp;&amp; { [ -z "\${PT_S3_BUCKET:-}" ] || "$UV" run pt sync push; }</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/.pt/refresh.log</string>
  <key>StandardErrorPath</key><string>$HOME/.pt/refresh.log</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict></plist>
PL
# The commands above are shell, but they live inside XML: every `&&` has to be
# written `&amp;&amp;`. launchd's own parser tolerates a raw `&`, so a malformed
# plist still loads and runs — which is exactly why it goes unnoticed. Lint both
# files here so a future edit that forgets the escaping fails loudly instead.
for p in "$PLIST" "$REFRESH_PLIST"; do
  plutil -lint "$p" >/dev/null || { echo "malformed plist: $p" >&2; exit 1; }
done

# Register with the modern domain API. `launchctl load` is deprecated and does
# not reliably keep a job registered in the GUI domain — both agents were found
# silently unloaded two days after a `load`, with every source gone stale and
# nothing reporting it. `bootstrap` plus an explicit `enable` is the supported
# path, and `enable` also clears a label that was disabled by a previous
# `launchctl disable` (that flag is persistent and survives reinstalling).
DOMAIN="gui/$(id -u)"
for p in "$PLIST" "$REFRESH_PLIST"; do
  label="$(basename "$p" .plist)"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  launchctl enable "$DOMAIN/$label"
  launchctl bootstrap "$DOMAIN" "$p"
done

# Registering is not the same as running, so confirm rather than assume.
failed=0
for label in "$(basename "$PLIST" .plist)" "$(basename "$REFRESH_PLIST" .plist)"; do
  if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    echo "loaded   $label"
  else
    echo "FAILED to load $label" >&2
    failed=1
  fi
done
[ "$failed" -eq 0 ] || exit 1

echo "installed $PLIST (every 5 min; log: ~/.pt/collect.log)"
echo "installed $REFRESH_PLIST (checks every 30 min, full refresh once per UTC day; log: ~/.pt/refresh.log)"
echo "check it any time with: uv run pt status"
