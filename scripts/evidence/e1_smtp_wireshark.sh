#!/usr/bin/env bash
# Evidence 1: one real SMTP exchange on TCP 2525, captured on loopback with tshark.
source "$(dirname "$0")/_common.sh"

PCAP="$EVID/e1_smtp.pcapng"
STREAM="$EVID/e1_smtp_stream.txt"
TSHARK_ERR="$EVID/e1_tshark.err"
CAPTURE_SECS=10   # tshark stops itself: a native Windows process cannot be sent SIGINT

case "$(uname -s)" in
    Darwin) IFACE=lo0 ;;
    Linux) IFACE=lo ;;
    *) IFACE='\Device\NPF_Loopback' ;;   # the Npcap loopback adapter
esac

capture_fix() {
    case "$(uname -s)" in
    Darwin) cat <<'EOF'
Capturing on lo0 needs read access to /dev/bpf*. Fix it once, then rerun this script:
  A) Wireshark .dmg -> run "Install ChmodBPF.pkg" -> log out and back in, or
  B) sudo dseditgroup -o edit -a "$USER" -t user access_bpf   (group made by ChmodBPF)
     sudo chgrp access_bpf /dev/bpf* && sudo chmod g+rw /dev/bpf*   (lasts until reboot)
EOF
    ;;
    Linux) echo 'Capturing needs the wireshark group: sudo usermod -aG wireshark "$USER", then log in again.' ;;
    *) echo 'Capturing on loopback needs Npcap installed with "Support loopback traffic" ticked (the Wireshark installer offers it).' ;;
    esac
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
    title "EVIDENCE 1 — SMTP command-reply exchange on TCP 2525 (tshark on loopback)"
    local tshark
    if ! tshark="$(find_tshark)"; then
        echo "tshark not found (PATH, /Applications/Wireshark.app or C:\\Program Files\\Wireshark)."
        echo "Install Wireshark: https://www.wireshark.org/download.html  (or: brew install --cask wireshark)"
        capture_fix
        exit 1
    fi

    clean_state
    start_servers "$EVID/e1_server.log"
    rm -f "$PCAP"
    "$tshark" -i "$IFACE" -a duration:"$CAPTURE_SECS" -f "tcp port 2525" -w "$PCAP" \
        >"$TSHARK_ERR" 2>&1 &
    local tpid=$!
    for _ in $(seq 100); do
        grep -q "Capturing on" "$TSHARK_ERR" && break
        if ! kill -0 "$tpid" 2>/dev/null; then break; fi
        sleep 0.1
    done
    if ! grep -q "Capturing on" "$TSHARK_ERR"; then
        echo "tshark could not capture on $IFACE:"
        sed 's/^/  /' "$TSHARK_ERR"
        if grep -qi "permission\|don't have\|access\|no such device" "$TSHARK_ERR"; then capture_fix; fi
        kill "$tpid" 2>/dev/null || true   # may already have exited
        stop_servers
        exit 1
    fi

    mkdir -p "$ROOT/data/e1"
    printf 'Hello Kapish,\r\nthis tiny file travels inline.\r\n' >"$ROOT/data/e1/hello.txt"
    "$PY" -m localmail.client.cli send --user suyash --password "$(password_of suyash)" \
        --to kapish@localmail --subject "Evidence 1 - SMTP on port 2525" \
        --body "Captured on loopback with tshark." --attach "$ROOT/data/e1/hello.txt" 2>/dev/null
    echo "waiting for the ${CAPTURE_SECS}s capture to end ..."
    wait "$tpid" || true
    stop_servers

    "$tshark" -r "$PCAP" -d tcp.port==2525,smtp -q -z follow,tcp,ascii,0 | tr -d '\r' >"$STREAM"
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
