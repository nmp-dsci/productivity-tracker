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
    <string>cd "$REPO" && "$UV" run pt collect && { "$UV" run pt screen-backfill --days 3 || true; } && "$UV" run pt rollup && { [ -z "\${PT_S3_BUCKET:-}" ] || "$UV" run pt sync push; } && { [ ! -f "$HOME/.env" ] || { set -a; . "$HOME/.env"; set +a; "$UV" run pt weekly --max-age-hours 24; }; }</string>
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
    <string>cd "$REPO" && { [ ! -f "$HOME/.env" ] || { set -a; . "$HOME/.env"; set +a; }; } && "$UV" run pt refresh && { [ -z "\${PT_S3_BUCKET:-}" ] || "$UV" run pt sync push; }</string>
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
launchctl unload "$REFRESH_PLIST" 2>/dev/null || true
launchctl load "$REFRESH_PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed $PLIST (every 5 min; log: ~/.pt/collect.log)"
echo "installed $REFRESH_PLIST (checks every 30 min, full refresh once per UTC day; log: ~/.pt/refresh.log)"
