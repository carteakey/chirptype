#!/bin/bash
set -euo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/com.chirptype.plist"
BIN_PATH="$HOME/.local/bin/chirptype"

install_chirptype() {
    if ! command -v uv &>/dev/null; then
        echo "Error: uv not found. Install from https://docs.astral.sh/uv/"
        exit 1
    fi

    echo "Installing chirptype..."
    uv tool install .

    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chirptype</string>
    <key>ProgramArguments</key>
    <array>
        <string>${BIN_PATH}</string>
        <string>--quiet</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/chirptype.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/chirptype.log</string>
</dict>
</plist>
PLIST

    launchctl load "$PLIST_PATH"
    launchctl start com.chirptype
    echo "Done. ChirpType installed and started. It will auto-start at login."
    echo "Logs: tail -f /tmp/chirptype.log"
}

uninstall_chirptype() {
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    uv tool uninstall chirptype 2>/dev/null || true
    echo "ChirpType uninstalled."
}

case "${1:-install}" in
    install)   install_chirptype ;;
    uninstall) uninstall_chirptype ;;
    *)
        echo "Usage: $0 [install|uninstall]"
        exit 1
        ;;
esac
