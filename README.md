# LocalMail — Local Email Transfer System with MIME Attachment Support

Computer Networks mini-project (BACSE203), VIT.
Team: Suyash, Kapish, Yashraj.

A self-contained local mail system. The SMTP server (TCP 2525), the POP3 server (TCP 1110)
and both protocol clients are written by us directly on raw TCP sockets — no `aiosmtpd`, no
`smtplib`/`poplib` in production code. A small HTTP reference store (TCP 8000) backs the
mid-size attachment tier. Python 3.10+, standard library only.

Attachments are routed by a three-tier strategy decided on the **raw** file size, before
base64:

| Raw size | Tier | How it travels |
|---|---|---|
| ≤ 1 MB | inline | base64 part inside the mail |
| 1–10 MB | reference | HTTP `PUT /ref`; the mail carries only an ID + SHA-256 |
| 10–25 MB | fragment | 2 MB chunks, one SMTP message each, reassembled by the client |
| > 25 MB | rejected | client refuses; the server independently answers `552` |

---

## 1. Setup

No dependencies to install. Check your Python:

```
python3 --version          # must be 3.10 or newer
```

From the project root (`CN/`), start all three servers:

```
python3 -m localmail.server.run_server
```

```
16:24:50 [BOOT] SMTP tcp/2525  POP3 tcp/1110  refstore http://127.0.0.1:8000/ref  bound on 127.0.0.1
16:24:50 [BOOT] domain=localmail users=kapish,suyash,yashraj data=/…/CN/data
16:24:50 [BOOT] Ctrl-C to stop
```

Every protocol line is logged as `[SMTP] C:` / `[SMTP] S:` / `[POP3] C:` / `[POP3] S:` /
`[HTTP]` with a timestamp. DATA bodies and RETR content are truncated in the log. Leave this
window visible — it is the evidence for the protocol exchange.

### Users

Preloaded in `config.json`. Addresses are `<user>@localmail`.

| User | Password |
|---|---|
| suyash | suyash123 |
| kapish | kapish123 |
| yashraj | yashraj123 |

### Config

`config.json` at the project root; `localmail/config.py` supplies the same values as
defaults if the file is absent. `MB = 1024*1024`.

| Key | Default | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | bind address (`0.0.0.0` for LAN mode) |
| `smtp_port` / `pop3_port` / `ref_port` | 2525 / 1110 / 8000 | listening ports |
| `domain` | `localmail` | mail domain |
| `data_dir` | `data` | Maildir + SQLite index + reference blobs |
| `users` | 3 accounts | username → password |
| `inline_max` | 1 MB | inline ceiling |
| `reference_max` | 10 MB | reference ceiling |
| `hard_max` | 25 MB | absolute ceiling, also advertised as SMTP `SIZE` |
| `chunk_size` | 2 MB | fragment size |

### What lands on disk

```
data/mail/<user>/{tmp,new,cur}   Maildir: written to tmp, renamed into new atomically
data/index.db                    SQLite: messages(id,user,filename,size,sender,subject,received_at,deleted)
data/refstore/<id>               reference-tier blobs, id = uuid4 hex
downloads/<user>/                what the receiving client saved and hash-verified
```

---

## 2. Sending and fetching (CLI)

Two terminals: servers in one, client in the other.

```
python3 -m localmail.client.cli send \
    --user suyash --password suyash123 \
    --to kapish@localmail \
    --subject "Review 2 attachments" \
    --body "Three files, one per tier." \
    --attach report.pdf --attach big.bin
```

```
python3 -m localmail.client.cli fetch --user kapish --password kapish123
python3 -m localmail.client.cli fetch --user kapish --password kapish123 --delete
```

`--delete` removes inline mails, reference mails, and fragment mails belonging to a group
that reassembled **and** passed SHA-256. A fragment group that is still incomplete is left
on the server so a later fetch can finish it — otherwise a fetch that raced an in-flight
15 MB transfer would destroy it. The client prints
`[CLIENT] holding k fragment mails on server` when this happens.

Reassembly runs immediately on retrieval: reference files are downloaded with
`GET /ref/<id>` and hash-checked, and a fragment group is grouped by `X-Fragment-ID`,
ordered by `X-Fragment-Index`, joined, and verified against `X-File-SHA256`. Eight fragment
mails show up as **one** logical inbox row. On a missing fragment or a hash mismatch nothing
is saved and the row reads `incomplete: waiting for k of n fragments` or
`incomplete: SHA-256 mismatch`.

### GUI

```
python3 -m localmail.client.gui
python3 -m localmail.client.gui --user kapish --password kapish123   # logs in on launch
```

`--host` pre-fills the server field (LAN mode).

Login (server host / username / password) → inbox list (from, subject, date, tier, fragment
count, attachment count, status) → message view with the attachment list and **Open** (OS
default app: `open` on macOS, `os.startfile` on Windows) and **Save**. **Compose** shows a
per-file tier preview before you send; the status bar reports the tier used. Non-ASCII
filenames work throughout.

Each Refresh is a complete connect → fetch → `QUIT` cycle, so the GUI never holds the POP3
mailbox lock against the CLI.

---

## 3. Running the demo

```
python3 scripts/demo.py
```

Starts the servers in-process, generates a 500 KB file with a non-ASCII name, a 5 MB file and
a 15 MB file, sends all three from suyash to kapish, fetches as kapish, and prints:

```
================================================================================================================
FILE                       SIZE  TIER       FRAGMENTS  SHA-256 MATCH  SAVED PATH
================================================================================================================
रिपोर्ट_é.txt          500.0 KB  inline     -          yes            kapish/रिपोर्ट_é.txt
midsize.pdf              5.0 MB  reference  -          yes            kapish/midsize.pdf
big.bin                 15.0 MB  fragment   8          yes            kapish/big.bin
================================================================================================================
10 physical mails collapsed to 3 logical inbox message(s)
```

`python3 scripts/demo.py --quiet-server [LOGFILE]` shows only the `[CLIENT]` lines and the table,
and writes every `[SMTP]`/`[POP3]`/`[HTTP]` line to LOGFILE (default `evidence/e4_server.log`).

If ports 2525/1110/8000 are already taken, stop the other `run_server` first — the demo
binds the configured ports.

---

## 4. Single-host vs LAN mode

### Single host (default)

`host` is `127.0.0.1`. Servers and clients run on the same machine; nothing leaves the
loopback interface.

### LAN mode (two or three machines)

1. On the **server** machine, set `host` to `0.0.0.0` in `config.json` so the listeners
   accept connections from the network, then start `run_server`.
2. Allow the inbound connection when the OS firewall prompts (macOS: "Do you want the
   application python3 to accept incoming network connections?" → Allow. Windows: tick
   Private networks in the Windows Defender Firewall dialog).
3. Find the server's LAN IP — `ipconfig getifaddr en0` on macOS, `ipconfig` on Windows.
4. On each **client** machine, point the client at that IP with `--host`.

Example lab setup, all on one `/24`:

| Role | Address | Netmask | Gateway |
|---|---|---|---|
| Server (SMTP 2525, POP3 1110, refstore 8000) | 192.168.1.10 | 255.255.255.0 | 192.168.1.1 |
| Client A (suyash) | 192.168.1.21 | 255.255.255.0 | 192.168.1.1 |
| Client B (kapish) | 192.168.1.22 | 255.255.255.0 | 192.168.1.1 |

```
# on 192.168.1.21
python3 -m localmail.client.cli send --user suyash --password suyash123 \
    --to kapish@localmail --subject "from client A" --body hello \
    --attach big.bin --host 192.168.1.10

# on 192.168.1.22
python3 -m localmail.client.cli fetch --user kapish --password kapish123 --host 192.168.1.10
```

In the GUI, type `192.168.1.10` into the "Server host" field on the login screen.
`--smtp-port`, `--pop3-port` and `--ref-port` override the ports if you moved them.

Both machines must reach the server on all three ports — the reference tier needs TCP 8000
as much as the mail ports. Check with `nc -vz 192.168.1.10 8000`.

### Platform notes

Tested on macOS (Apple Silicon) and Windows. The only platform-specific code is the mailbox
lock file (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) and the GUI **Open** button
(`open` vs `os.startfile`). Both pick the right branch automatically.

---

## 5. Manual protocol sessions (netcat)

The servers accept bare-LF line endings as well as CRLF, so plain `nc` works by hand.
Verified on macOS: `nc localhost 1110` (bare LF) and `nc -c localhost 1110` (`-c` sends CRLF,
like a real mail client) give identical replies. The evidence scripts use `nc -c`.

### SMTP on 2525

```
$ nc localhost 2525
220 localmail SMTP ready
EHLO client.local
250-localmail Hello client.local
250-SIZE 26214400
250 OK
MAIL FROM:<suyash@localmail>
250 OK
RCPT TO:<kapish@localmail>
250 OK
DATA
354 End data with <CRLF>.<CRLF>
From: suyash@localmail
Subject: typed by hand

hello from netcat
.
250 Message accepted
QUIT
221 Bye
```

Type the single `.` on its own line to end the message. Other replies worth showing:
`RCPT TO:<nobody@localmail>` → `550 No such user`; `RCPT TO:` before `MAIL FROM:` →
`503 Bad sequence of commands`; a nonsense verb → `500 Command not recognized`.

### POP3 on 1110

```
$ nc localhost 1110
+OK POP3 ready
USER kapish
+OK user accepted
PASS kapish123
+OK logged in
STAT
+OK 1 214
LIST
+OK 1 messages (214 octets)
1 214
.
RETR 1
+OK 214 octets
Received: from 127.0.0.1 by localmail (LocalMail SMTP) for kapish@localmail; …
From: suyash@localmail
Subject: typed by hand

hello from netcat
.
DELE 1
+OK message 1 marked deleted
QUIT
+OK Bye
```

`DELE` only marks. The deletion is committed when `QUIT` moves the session into the UPDATE
state — close the terminal instead of typing `QUIT` and the message is still there next time.

### Reference store on 8000

The reference tier is easiest to exercise through the client path: `python3 scripts/demo.py`
performs a `PUT /ref` and a `GET /ref/<id>`, and the `[HTTP]` log lines show both with the
id and the byte count. To drive it by hand:

```
python3 - <<'EOF'
from localmail.client.tiering import upload_to_store
from localmail.client.reassembly import http_get
rid = upload_to_store("127.0.0.1", 8000, "note.txt", b"hello ref store")
print("id:", rid, "->", http_get("127.0.0.1", 8000, rid))
EOF
```

---

## 6. Tests

```
python3 -m unittest discover -v
```

89 tests. `smtplib` and `poplib` appear **only** in `tests/test_reference_clients.py`, as
stdlib reference clients proving our servers are RFC-compliant. Coverage:

| Module | What it locks down |
|---|---|
| `test_smtp.py` | exact 220/250/354/221/550/552/503/500/501 strings, EHLO multiline, RSET/NOOP, `rcpts` reset after DATA, dot-stuffing, Maildir layout, index row, `Received:` header, one store call per recipient |
| `test_pop3.py` | `+OK POP3 ready`, `+OK logged in`, STAT format, `PASS ****` in the log and no password anywhere in it, LIST/RETR/UIDL terminators, dot-stuffed RETR, DELE-commit-at-QUIT, dropped connection deletes nothing, one session per mailbox |
| `test_mime.py` | MIME-Version, multipart/mixed, unique boundary, text/plain first, every attachment octet-stream + base64 + Content-Disposition, RFC 2231 non-ASCII filenames, CRLF-only wire format |
| `test_tiering.py` | tier boundaries at exactly 1 MB, 1 MB+1, 10 MB, 10 MB+1, 25 MB, 25 MB+1; 2 MB split; reference download + hash verify; out-of-order, missing and corrupted fragments; the `--delete` hold policy |
| `test_refstore.py` | PUT/GET round trip, distinct ids, 404 on missing and on malformed ids |
| `test_concurrency.py` | 20 threads delivering into one mailbox: every message intact, index count exact, `tmp/` left clean |
| `test_reference_clients.py` | smtplib and poplib drive our servers end to end |
| `test_gui.py` | inbox date column shortened to fit, unparseable dates shown as-is |

---

## 7. Wireshark capture

All three protocols run on loopback in single-host mode, so capture the loopback interface:

- **macOS** — interface `lo0`
- **Windows** — the "Adapter for loopback traffic capture" that Npcap installs (install
  Npcap with the loopback option enabled)

Display filter:

```
tcp.port == 2525 || tcp.port == 1110 || tcp.port == 8000
```

Start the capture, run `python3 scripts/demo.py` (or a hand-typed `nc` session), stop the
capture. Right-click any 2525 packet → **Follow → TCP Stream** to read the whole
`EHLO → MAIL FROM → RCPT TO → DATA → 250 → QUIT` exchange as plain text.

In LAN mode capture the real interface (`en0` / Ethernet) instead of loopback; the same
display filter applies.

---

## 8. Evidence capture guide

See [EVIDENCE.md](EVIDENCE.md): one script per evidence item in `scripts/evidence/`, what to
click, what each screenshot must show, and a caption for the report.

---

## 9. Known limits

- **Plaintext `USER` / `PASS`.** POP3 credentials cross the wire unencrypted, and passwords
  sit in `config.json` in the clear. The server log masks them as `PASS ****`. Fine for a closed lab, not for anything real.
- **No TLS.** Neither SMTP nor POP3 offers STARTTLS; the HTTP reference store is plain HTTP.
- **No internet relay, no DNS/MX.** Only `@localmail` addresses on one host or one LAN. Mail
  for any other domain is refused with `550 No such user`.
- **No SMTP AUTH.** Any host that can reach port 2525 can submit mail. The CLI checks the
  sender's password locally before sending, which is a convenience, not a security control.
- **No spam filtering.**
- **The reference store never expires blobs.** `data/refstore/` grows until deleted by hand,
  and a blob is readable by anyone who knows its 32-character id.
- **Deliberately out of scope:** TLS, internet relay, DNS/MX, spam filtering, and falling
  back to an existing mail server.
