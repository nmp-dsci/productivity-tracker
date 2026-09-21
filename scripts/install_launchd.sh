#!/usr/bin/env bash
# Install a LaunchAgent that runs `pt collect && pt rollup` every 5 minutes
# (and `pt sync push` when PT_S3_BUCKET is set), and refreshes the rolling
# narrative once a day on the Claude subscription when ~/.env has
# CLAUDE_CODE_OAUTH_TOKEN. Logs to ~/.pt/collect.log.
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
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed $PLIST (every 5 min; log: ~/.pt/collect.log)"
