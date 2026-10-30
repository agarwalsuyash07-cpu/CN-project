# Evidence capture — Second Review

Every screenshot is real output from the scripts below. Each script starts from a clean state
(it wipes `data/` and `downloads/` and restarts the servers) and saves its console output in
`evidence/`. Take the terminal shots in a wide window (about 200×55). Stop any servers left
running with `scripts/evidence/stop_servers.sh`.

**Windows:** run the scripts from Git Bash (`bash scripts/evidence/e2_pop3_prepare.sh`). They
use `netstat`/`taskkill` instead of `lsof`/`kill`, pick `python` when `python3` is only the
Microsoft Store stub, and E2 prints `python scripts/nc.py` in place of `nc -c`.

Report material, already generated (`scripts/evidence/make_report_material.sh` regenerates it):
`evidence/versions.txt`, `evidence/section_6_3_extracts.txt`, `evidence/checklist.md`.

---

## E1 — SMTP exchange on TCP 2525 (Wireshark)

**One-time setup:** install Wireshark (https://www.wireshark.org/download.html, or
`brew install --cask wireshark`) and run **Install ChmodBPF.pkg** from the .dmg, then log out
and back in. Without ChmodBPF, capturing on `lo0` fails because `/dev/bpf*` is root-only. The
script prints this fix if it hits that error.
On Windows, install Wireshark and tick **Install Npcap** with **Support loopback traffic**; the
script captures on `\Device\NPF_Loopback`. On Linux it captures on `lo`. The capture stops
itself after 10 s.

**Run:** `scripts/evidence/e1_smtp_wireshark.sh`
It captures `tcp port 2525` on `lo0` into `evidence/e1_smtp.pcapng` while the CLI sends ONE
small mail (suyash → kapish, with a tiny inline `hello.txt`). Then it prints TCP stream 0 with
the base64 body lines folded. The full text is in `evidence/e1_smtp_stream.txt`.

**Click:** open `evidence/e1_smtp.pcapng` in Wireshark → **Analyze → Decode As… → +**, set
Field *TCP port*, Value *2525*, Current *SMTP* → OK → right-click any packet → **Follow → TCP
Stream**.

**Screenshot must show:** `220 localmail SMTP ready`, `EHLO`, `MAIL FROM:<suyash@localmail>`,
`RCPT TO:<kapish@localmail>`, `DATA`, `354 End data with <CRLF>.<CRLF>`, the final `.`,
`250 Message accepted`, `QUIT`, `221 Bye`. Take a second shot of the terminal printout if you
want both.

**Caption:** *Evidence 1: SMTP command–reply exchange on TCP 2525 captured on the loopback
interface in Wireshark (Follow TCP Stream).*

---

## E2 — POP3 session over netcat on TCP 1110

**Run:** `scripts/evidence/e2_pop3_prepare.sh`
It leaves ONE plain-text mail (367 bytes) in yashraj's mailbox with the servers running, then
prints the lines to type.

**Type, in a NEW terminal** (wait for each reply):

```
nc -c localhost 1110
USER yashraj
PASS yashraj123
STAT
LIST
RETR 1
DELE 1
QUIT
```

Then reconnect to show the mailbox is empty: `nc -c localhost 1110`, `USER yashraj`,
`PASS yashraj123`, `STAT` → `+OK 0 0`, `QUIT`.
(`-c` sends CRLF like a mail client. Plain `nc`, which sends bare LF, gets the same replies.
On Windows type `python scripts/nc.py localhost 1110` instead of `nc -c localhost 1110`.)

**Screenshot must show:** `+OK POP3 ready`, `+OK logged in`, `+OK 1 367`, the LIST block ending
in `.`, `+OK 367 octets` with the readable message ending in `.`,
`+OK message 1 marked deleted`, `+OK Bye`, and the reconnect's `+OK 0 0`. Optional second
shot: `evidence/e2_server.log` shows `[POP3] C: PASS ****`.

**Caption:** *Evidence 2: manual POP3 session over netcat on TCP 1110 — USER/PASS, STAT, LIST,
RETR, DELE and QUIT; the reconnect shows DELE committed at QUIT.*

---

## E3 — GUI with an inline non-ASCII attachment, opened and saved

**Run:** `scripts/evidence/e3_gui_prepare.sh`
It sends kapish ONE mail, "Evidence 3 — inline non-ASCII attachment", whose only attachment is
`रिपोर्ट_é.txt` (2.4 KB of Hindi + English, inline tier). Then it opens the GUI already logged
in as kapish.

**Click:** the mail row → `रिपोर्ट_é.txt` in *Attachments* → **Open** (opens in TextEdit) →
**Save** → pick a folder (the status bar shows `saved to …`). Place the GUI and TextEdit side
by side.

**Screenshot must show:** the inbox row (`TIER inline`, `ATT 1`, `STATUS ok`, full date), the
message view, the attachment name in Devanagari, the TextEdit window titled `रिपोर्ट_é.txt`
with readable Hindi and English text, and the status bar.

**Caption:** *Evidence 3: Tkinter client showing an inline attachment with a non-ASCII
(Devanagari) filename, received over POP3, opened in the OS default app and saved.*

---

## E4 — 15 MB file fragmented, reassembled and SHA-256 verified

**Run:** `scripts/evidence/e4_fragment_demo.sh`
It runs `scripts/demo.py --quiet-server`. The screen shows only `[CLIENT]` lines and the
results table. Every server line goes to `evidence/e4_server.log`, and the screen text is saved
to `evidence/e4_client.txt`.

**Screenshot must show:** `big.bin 15.0 MB -> tier: fragment (8 fragments of 2.0 MB)`,
`sent fragment 1/8 … 8/8`, `received 8/8 fragments for …, reassembled 15.0 MB`,
`SHA-256 match: … -> saved …/big.bin`, and the table with `fragment 8 yes`.

**Caption:** *Evidence 4: a 15 MB file sent as eight 2 MB SMTP fragments, reassembled on POP3
retrieval and verified by SHA-256 (client log and results table).*

---

## E5 — Test suite

**Run:** `scripts/evidence/e5_tests.sh`
It runs `python3 -m unittest discover -v`. The full output is saved to `evidence/e5_tests.txt`;
the screen shows tests per module and the final verdict.

**Screenshot must show:** the per-module table (10 modules, 102 tests) and `Ran 102 tests in …s`
followed by `OK`.

**Caption:** *Evidence 5: automated unittest suite — 102 tests across SMTP, POP3, MIME, tiering,
reference store, concurrency, GUI Open/Save and date formatting, and stdlib reference clients, all passing.*
