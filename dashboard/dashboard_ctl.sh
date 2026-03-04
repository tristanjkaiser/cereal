#!/bin/bash
# Control the Cereal to-do dashboard via macOS launchd
# Usage: ./dashboard/dashboard_ctl.sh enable|disable|status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.goji.cereal-dashboard"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
SERVE_SCRIPT="$PROJECT_DIR/web/run.py"
LOG_FILE="$PROJECT_DIR/logs/dashboard.log"

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
        <string>$SERVE_SCRIPT</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DATABASE_URL</key>
        <string>${DATABASE_URL:-postgresql://localhost:5432/cereal}</string>
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
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
        echo "Dashboard enabled (auto-restarts on crash)"
        echo "URL:   http://localhost:5555"
        echo "Plist: $PLIST_DST"
        echo "Logs:  $LOG_FILE"
        ;;
    disable)
        launchctl unload "$PLIST_DST" 2>/dev/null
        rm -f "$PLIST_DST"
        echo "Dashboard disabled"
        ;;
    status)
        if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
            echo "Dashboard is ENABLED"
            launchctl list "$PLIST_NAME" 2>/dev/null
        else
            echo "Dashboard is DISABLED"
        fi
        ;;
    *)
        echo "Usage: $0 {enable|disable|status}"
        exit 1
        ;;
esac
