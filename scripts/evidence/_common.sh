# Sourced by scripts/evidence/eN_*.sh. Not meant to be run on its own.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
EVID="$ROOT/evidence"
PIDFILE="$EVID/.server.pid"
PY="${PYTHON:-python3}"
PORTS="2525 1110 8000"
mkdir -p "$EVID"

title() {
    local rule
    rule="$(printf '%*s' 72 '' | tr ' ' '=')"
    printf '%s\n%s\n%s\n' "$rule" "$1" "$rule"
}

listeners() {
    local port
    for port in $PORTS; do
        lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    done | sort -u
}

stop_servers() {
    local pid
    if [ -f "$PIDFILE" ]; then
        # the pid file can outlive its process (reboot, Ctrl-C); a dead pid is fine
        kill "$(cat "$PIDFILE")" 2>/dev/null || true
        rm -f "$PIDFILE"
    fi
    for pid in $(listeners); do
        if ps -o command= -p "$pid" | grep -q "localmail"; then
            kill "$pid"
        else
            echo "error: a LocalMail port ($PORTS) is held by another program:" >&2
            ps -o pid=,command= -p "$pid" >&2
            exit 1
        fi
    done
    for _ in $(seq 50); do
        [ -z "$(listeners)" ] && return 0
        sleep 0.1
    done
    echo "error: LocalMail ports still busy after stopping servers" >&2
    exit 1
}

clean_state() {
    stop_servers
    rm -rf "$ROOT/data" "$ROOT/downloads"
}

# start_servers <logfile>: run_server in the background, wait until all three ports listen
start_servers() {
    local log="$1" port ready
    nohup "$PY" -m localmail.server.run_server >"$log" 2>&1 &
    echo $! >"$PIDFILE"
    for _ in $(seq 100); do
        ready=1
        for port in $PORTS; do
            lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || ready=0
        done
        [ "$ready" = 1 ] && return 0
        sleep 0.1
    done
    echo "error: servers did not start; last lines of $log:" >&2
    tail -5 "$log" >&2
    exit 1
}

password_of() {
    "$PY" -c 'import sys; from localmail.config import CONFIG; print(CONFIG["users"][sys.argv[1]])' "$1"
}
