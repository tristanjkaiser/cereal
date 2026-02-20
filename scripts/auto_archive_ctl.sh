#!/bin/bash
# Control auto-archive scheduling via macOS launchd
# Usage: ./scripts/auto_archive_ctl.sh enable|disable|status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.goji.cereal-auto-archive"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
ARCHIVE_SCRIPT="$PROJECT_DIR/scripts/auto_archive.py"
LOG_FILE="$PROJECT_DIR/logs/auto_archive_launchd.log"

generate_plist() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$ARCHIVE_SCRIPT</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DATABASE_URL</key>
        <string>${DATABASE_URL:-postgresql://localhost:5432/cereal}</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
}

case "$1" in
    enable)
        if [ ! -x "$PYTHON_BIN" ]; then
            echo "Error: Python not found at $PYTHON_BIN"
            echo "Run: cd $PROJECT_DIR && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
            exit 1
        fi
        mkdir -p "$(dirname "$PLIST_DST")"
        mkdir -p "$PROJECT_DIR/logs"
        generate_plist > "$PLIST_DST"
        launchctl load "$PLIST_DST"
        echo "Auto-archive enabled (every 30 minutes)"
        echo "Plist: $PLIST_DST"
        echo "Logs:  $LOG_FILE"
        ;;
    disable)
        launchctl unload "$PLIST_DST" 2>/dev/null
        rm -f "$PLIST_DST"
        echo "Auto-archive disabled"
        ;;
    status)
        if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
            echo "Auto-archive is ENABLED"
            launchctl list "$PLIST_NAME" 2>/dev/null
        else
            echo "Auto-archive is DISABLED"
        fi
        ;;
    *)
        echo "Usage: $0 {enable|disable|status}"
        exit 1
        ;;
esac
