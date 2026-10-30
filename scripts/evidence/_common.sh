# Sourced by scripts/evidence/eN_*.sh. Not meant to be run on its own.
# Runs on macOS, Linux and Windows (Git Bash).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
EVID="$ROOT/evidence"
PIDFILE="$EVID/.server.pid"
PORTS="2525 1110 8000"
mkdir -p "$EVID"

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;;
    *) WINDOWS=0 ;;
esac

# on Windows "python3" is usually the Microsoft Store stub, which runs nothing
if [ -z "${PYTHON:-}" ]; then
    if python3 -c "" 2>/dev/null; then PYTHON=python3; else PYTHON=python; fi
fi
PY="$PYTHON"

title() {
    local rule
    rule="$(printf '%*s' 72 '' | tr ' ' '=')"
    printf '%s\n%s\n%s\n' "$rule" "$1" "$rule"
}

# listeners [port...]: pids listening on the ports (default: all LocalMail ports)
listeners() {
    local ports="${*:-$PORTS}" port
    if [ "$WINDOWS" = 1 ]; then
        netstat -ano -p tcp | tr -d '\r' | awk -v ports=" $ports " \
            '$3 == "0.0.0.0:0" && $5 != 0 { n = split($2, a, ":"); if (index(ports, " " a[n] " ")) print $5 }'
        # matched by the 0.0.0.0:0 peer, not the state: Windows can show a live listener as CLOSED
    else
        for port in $ports; do
            lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
        done
    fi | sort -u
}

command_of() {
    if [ "$WINDOWS" = 1 ]; then
        powershell.exe -NoProfile -Command \
            "(Get-CimInstance Win32_Process -Filter 'ProcessId=$1').CommandLine" | tr -d '\r'
    else
        ps -o command= -p "$1"
    fi
}

kill_pid() {
    if [ "$WINDOWS" = 1 ]; then
        taskkill //F //PID "$1" >/dev/null 2>&1
    else
        kill "$1" 2>/dev/null
    fi
}

stop_servers() {
    local pid
    if [ -f "$PIDFILE" ]; then
        # the pid file can outlive its process (reboot, Ctrl-C); a dead pid is fine
        kill_pid "$(cat "$PIDFILE")" || true
        rm -f "$PIDFILE"
    fi
    for pid in $(listeners); do
        if command_of "$pid" | grep -q "localmail"; then
            kill_pid "$pid" || true
        else
            echo "error: a LocalMail port ($PORTS) is held by another program:" >&2
            echo "$pid $(command_of "$pid")" >&2
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

# start_servers <logfile>: run_server in the background, wait until it reports all three bound
start_servers() {
    local log="$1" pid
    nohup "$PY" -m localmail.server.run_server >"$log" 2>&1 &
    pid=$!
    # Git Bash: $! is a bash pid; taskkill needs the Windows one
    cat "/proc/$pid/winpid" 2>/dev/null >"$PIDFILE" || echo "$pid" >"$PIDFILE"
    for _ in $(seq 100); do
        grep -q "\[BOOT\] Ctrl-C to stop" "$log" && return 0
        kill -0 "$pid" 2>/dev/null || break   # exited early, e.g. a port is already taken
        sleep 0.1
    done
    echo "error: servers did not start; last lines of $log:" >&2
    tail -5 "$log" >&2
    exit 1
}

password_of() {
    "$PY" -c 'import sys; from localmail.config import CONFIG; print(CONFIG["users"][sys.argv[1]])' "$1"
}

# nc_command: how to open a hand-typed session that sends CRLF like a mail client
nc_command() {
    if [ "$WINDOWS" = 1 ] || ! command -v nc >/dev/null; then
        echo "$PY scripts/nc.py localhost"
    else
        echo "nc -c localhost"
    fi
}

find_tshark() {
    command -v tshark 2>/dev/null && return 0
    local app
    for app in /Applications/Wireshark.app/Contents/MacOS/tshark "/c/Program Files/Wireshark/tshark.exe"; do
        [ -x "$app" ] && echo "$app" && return 0
    done
    return 1
}
