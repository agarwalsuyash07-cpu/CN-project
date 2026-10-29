#!/usr/bin/env bash
# Writes evidence/versions.txt and evidence/section_6_3_extracts.txt from the real code.
source "$(dirname "$0")/_common.sh"

SMTP=localmail/server/smtp_server.py
TIER=localmail/client/tiering.py

# fail loudly if the code moved, instead of pasting the wrong lines into the report
expect_line() {
    local file="$1" n="$2" text="$3"
    if [ "$(sed -n "${n}p" "$file")" != "$text" ]; then
        echo "error: $file:$n is no longer '$text' - update the ranges in $0" >&2
        exit 1
    fi
}

versions() {
    "$PY" --version
    local tshark
    tshark="$(command -v tshark || true)"
    [ -z "$tshark" ] && [ -x /Applications/Wireshark.app/Contents/MacOS/tshark ] &&
        tshark=/Applications/Wireshark.app/Contents/MacOS/tshark
    if [ -n "$tshark" ]; then "$tshark" --version | head -1; else echo "tshark: not installed"; fi
    sw_vers
}

extracts() {
    expect_line "$SMTP" 64 "def handle_client(conn, peer, cfg, store):"
    expect_line "$SMTP" 96 '        elif cmd == "DATA":'
    expect_line "$SMTP" 117 '        elif cmd == "QUIT":'
    expect_line "$TIER" 23 "def choose_tier(size, cfg):"
    echo "# SMTP connection handler — $SMTP, lines 64-119 (excerpt)"
    sed -n 64,71p "$SMTP"
    echo "        # ... lines 72-95: EHLO/HELO, MAIL FROM, RCPT TO (503 / 501 / 550 checks) ..."
    sed -n 96,110p "$SMTP"
    echo "        # ... lines 111-116: RSET, NOOP ..."
    sed -n 117,119p "$SMTP"
    echo
    echo "# Tier selection — $TIER, lines 23-31 (complete)"
    sed -n 23,31p "$TIER"
}

versions >"$EVID/versions.txt"
extracts >"$EVID/section_6_3_extracts.txt"
echo "wrote evidence/versions.txt and evidence/section_6_3_extracts.txt"
