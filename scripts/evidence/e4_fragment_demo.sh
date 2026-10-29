#!/usr/bin/env bash
# Evidence 4: the demo with server logs sent to evidence/e4_server.log; the screen shows
# only [CLIENT] lines (tier decision, fragments, reassembly, SHA-256) and the results table.
source "$(dirname "$0")/_common.sh"

main() {
    title "EVIDENCE 4 — 15 MB file fragmented, reassembled, SHA-256 verified"
    clean_state   # the demo starts its own servers on the configured ports
    "$PY" scripts/demo.py --quiet-server "$EVID/e4_server.log"
}

main 2>&1 | tee "$EVID/e4_client.txt"
