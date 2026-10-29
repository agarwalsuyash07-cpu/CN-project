import argparse
import hashlib
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from localmail.client import tiering                                   # noqa: E402
from localmail.client.reassembly import downloads_dir, fetch_inbox     # noqa: E402
from localmail.common.lineio import log, setup_logging                 # noqa: E402
from localmail.config import CONFIG, MB, data_dir, human              # noqa: E402
from localmail.server.run_server import start_all                     # noqa: E402

FILES = [("रिपोर्ट_é.txt", 500 * 1024), ("midsize.pdf", 5 * MB), ("big.bin", 15 * MB)]


def make_files(directory):
    os.makedirs(directory, exist_ok=True)
    made = []
    for name, size in FILES:
        path = os.path.join(directory, name)
        with open(path, "wb") as fh:
            fh.write(os.urandom(size))
        made.append(path)
    return made


def sha256_path(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_client(record):
    return record.getMessage().startswith("[CLIENT]")


def quiet_server_logging(server_log):
    # [CLIENT] lines to the screen, every server line ([SMTP]/[POP3]/[HTTP]) to server_log
    os.makedirs(os.path.dirname(os.path.abspath(server_log)), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    to_file = logging.FileHandler(server_log, "w", encoding="utf-8")
    to_file.addFilter(lambda record: not is_client(record))
    to_screen = logging.StreamHandler(sys.stdout)
    to_screen.addFilter(is_client)
    for handler in (to_file, to_screen):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 scripts/demo.py")
    parser.add_argument("--quiet-server", nargs="?", const="evidence/e4_server.log",
                        metavar="LOGFILE",
                        help="show only [CLIENT] lines; write server lines to LOGFILE "
                             "(default evidence/e4_server.log)")
    args = parser.parse_args(argv)
    # logging goes to stderr; line-buffer stdout so the two stay in order when piped
    sys.stdout.reconfigure(line_buffering=True)
    if args.quiet_server:
        quiet_server_logging(args.quiet_server)
    else:
        setup_logging()
    cfg = CONFIG
    store, smtp, pop3, ref = start_all(cfg)
    print("\n== servers up: SMTP tcp/%d  POP3 tcp/%d  refstore http://%s:%d/ref ==\n"
          % (smtp.port, pop3.port, cfg["host"], ref.port))

    paths = make_files(os.path.join(data_dir(cfg), "demo"))
    print("== sending 3 files from suyash to kapish ==\n")
    sent = tiering.send(cfg, "suyash", "kapish@localmail", "Second Review demo",
                        "Three attachments, one per transfer tier.", paths)

    print("\n== fetching as kapish over POP3 ==\n")
    rows = fetch_inbox(cfg, "kapish", "kapish123")

    saved = {}
    for row in rows:
        for path in row["saved"]:
            saved[os.path.basename(path)] = (path, row)

    header = ("FILE", "SIZE", "TIER", "FRAGMENTS", "SHA-256 MATCH", "SAVED PATH")
    line = "%-20s %10s  %-10s %-10s %-14s %s"
    outbox = downloads_dir("kapish")
    print("\n" + "=" * 112)
    print(line % header)
    print("=" * 112)
    for source, record in zip(paths, sent):
        name = os.path.basename(source)
        path, row = saved.get(name, (None, None))
        if path is None:
            print(line % (name, human(record["size"]), record["tier"],
                          record["fragments"] or "-", "NOT SAVED",
                          row["status"] if row else "missing"))
            continue
        match = "yes" if sha256_path(path) == record["sha256"] else "NO"
        print(line % (name, human(record["size"]), record["tier"],
                      record["fragments"] or "-", match,
                      os.path.relpath(path, os.path.dirname(outbox))))
    print("=" * 112)
    print("%d physical mails collapsed to %d logical inbox message(s)"
          % (store.index_count("kapish"), len(rows)))
    print("downloads: %s\n" % outbox)

    smtp.stop()
    pop3.stop()
    ref.stop()


if __name__ == "__main__":
    main()
