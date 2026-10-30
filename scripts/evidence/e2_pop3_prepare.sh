#!/usr/bin/env bash
# Evidence 2: leaves ONE small mail in yashraj's mailbox and the servers running,
# then prints the netcat session to type by hand.
source "$(dirname "$0")/_common.sh"

main() {
    title "EVIDENCE 2 — POP3 session over netcat (port 1110)"
    clean_state
    start_servers "$EVID/e2_server.log"

    # a plain RFC 5322 text mail (no MIME/base64) sent by our own SMTP client, so RETR
    # shows readable text; the CLI would wrap the body as MIME base64
    "$PY" - <<'EOF'
from email.utils import formatdate
from localmail.client.smtp_client import send_mail
from localmail.config import CONFIG
body = "\r\n".join([
    "From: suyash@localmail",
    "To: yashraj@localmail",
    "Subject: Evidence 2 - POP3 over netcat",
    "Date: " + formatdate(localtime=True),
    "",
    "Hi Yashraj,",
    "",
    "This plain-text mail is waiting in your mailbox on TCP 1110.",
    "RETR it by hand, DELE it, then QUIT.",
    "",
    "-- Suyash",
])
send_mail(CONFIG["host"], CONFIG["smtp_port"], "suyash@localmail",
          ["yashraj@localmail"], body.encode("utf-8"))
EOF

    local files size
    files=("$ROOT"/data/mail/yashraj/new/*)
    size=$(wc -c <"${files[0]}" | tr -d ' ')
    if [ "${#files[@]}" -ne 1 ] || [ "$size" -ge 1536 ]; then
        echo "error: expected 1 mail under 1.5 KB, found ${#files[@]} file(s), first is $size bytes" >&2
        exit 1
    fi
    echo "servers running (pid $(cat "$PIDFILE")), log: evidence/e2_server.log"
    echo "yashraj has 1 message waiting ($size bytes), so RETR 1 fits on one screen."
    cat <<EOF

In a NEW terminal type (one command per line, wait for each reply):

    $(nc_command) 1110
    USER yashraj
    PASS $(password_of yashraj)
    STAT
    LIST
    RETR 1
    DELE 1
    QUIT

Then prove DELE was committed at QUIT - reconnect and expect "+OK 0 0":

    $(nc_command) 1110
    USER yashraj
    PASS $(password_of yashraj)
    STAT
    QUIT

(both send CRLF like a real client; the server also accepts plain "nc" with bare LF.
 scripts/nc.py stands in for nc on Windows, which ships without one.)
Stop the servers afterwards: scripts/evidence/stop_servers.sh
EOF
}

main 2>&1 | tee "$EVID/e2_prepare.txt"
