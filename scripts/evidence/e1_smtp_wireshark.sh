#!/usr/bin/env bash
# Evidence 1: one real SMTP exchange on TCP 2525, captured on lo0 with tshark.
source "$(dirname "$0")/_common.sh"

PCAP="$EVID/e1_smtp.pcapng"
STREAM="$EVID/e1_smtp_stream.txt"
TSHARK_ERR="$EVID/e1_tshark.err"

find_tshark() {
    command -v tshark 2>/dev/null && return 0
    local app=/Applications/Wireshark.app/Contents/MacOS/tshark
    [ -x "$app" ] && echo "$app" && return 0
    return 1
}

bpf_fix() {
    cat <<'EOF'
Capturing on lo0 needs read access to /dev/bpf*. Fix it once, then rerun this script:
  A) Wireshark .dmg -> run "Install ChmodBPF.pkg" -> log out and back in, or
  B) sudo dseditgroup -o edit -a "$USER" -t user access_bpf   (group made by ChmodBPF)
     sudo chgrp access_bpf /dev/bpf* && sudo chmod g+rw /dev/bpf*   (lasts until reboot)
EOF
}

# screen view of the stream: byte-count lines and base64 body lines are hidden
compact_stream() {
    awk '
        function flush() { if (n) { printf "        ... %d base64 lines omitted ...\n", n; n = 0 } }
        /^[ \t]*[0-9]+$/ { next }
        /^[ \t]*[A-Za-z0-9+\/]+=*[ \t]*$/ && length($0) >= 40 { n++; next }
        { flush(); print }
        END { flush() }
    ' "$1"
}

main() {
    title "EVIDENCE 1 — SMTP command-reply exchange on TCP 2525 (tshark on lo0)"
    local tshark
    if ! tshark="$(find_tshark)"; then
        echo "tshark not found (PATH or /Applications/Wireshark.app/Contents/MacOS/tshark)."
        echo "Install Wireshark: https://www.wireshark.org/download.html  (or: brew install --cask wireshark)"
        bpf_fix
        exit 1
    fi

    clean_state
    start_servers "$EVID/e1_server.log"
    rm -f "$PCAP"
    "$tshark" -i lo0 -f "tcp port 2525" -w "$PCAP" >"$TSHARK_ERR" 2>&1 &
    local tpid=$!
    for _ in $(seq 100); do
        grep -q "Capturing on" "$TSHARK_ERR" && break
        if ! kill -0 "$tpid" 2>/dev/null; then break; fi
        sleep 0.1
    done
    if ! grep -q "Capturing on" "$TSHARK_ERR"; then
        echo "tshark could not capture on lo0:"
        sed 's/^/  /' "$TSHARK_ERR"
        if grep -qi "permission\|don't have\|access" "$TSHARK_ERR"; then bpf_fix; fi
        kill "$tpid" 2>/dev/null || true   # may already have exited
        stop_servers
        exit 1
    fi

    mkdir -p "$ROOT/data/e1"
    printf 'Hello Kapish,\r\nthis tiny file travels inline.\r\n' >"$ROOT/data/e1/hello.txt"
    "$PY" -m localmail.client.cli send --user suyash --password "$(password_of suyash)" \
        --to kapish@localmail --subject "Evidence 1 - SMTP on port 2525" \
        --body "Captured on lo0 with tshark." --attach "$ROOT/data/e1/hello.txt" 2>/dev/null
    sleep 1
    kill -INT "$tpid"
    wait "$tpid" || true   # tshark exits non-zero on SIGINT on some builds; the pcap is complete
    stop_servers

    "$tshark" -r "$PCAP" -d tcp.port==2525,smtp -q -z follow,tcp,ascii,0 >"$STREAM"
    echo
    echo "Follow TCP stream 0 (full text in evidence/e1_smtp_stream.txt):"
    compact_stream "$STREAM"
    cat <<'EOF'

GUI screenshot: open evidence/e1_smtp.pcapng in Wireshark
  Analyze -> Decode As... -> + -> Field "TCP port", Value 2525, Current "SMTP" -> OK
  right-click any packet -> Follow -> TCP Stream
EOF
}

main 2>&1 | tee "$EVID/e1_smtp.txt"
