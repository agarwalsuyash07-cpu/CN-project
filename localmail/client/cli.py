import argparse
import sys

from ..common.lineio import setup_logging
from ..config import CONFIG, human
from . import tiering
from .pop3_client import POP3Error
from .reassembly import fetch_inbox
from .smtp_client import SMTPError


def _common(parser):
    parser.add_argument("--host", help="server address (LAN mode: the server's LAN IP)")
    parser.add_argument("--smtp-port", type=int)
    parser.add_argument("--pop3-port", type=int)
    parser.add_argument("--ref-port", type=int)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m localmail.client.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sender = sub.add_parser("send", help="send a message with optional attachments")
    sender.add_argument("--user", required=True)
    sender.add_argument("--password", required=True)
    sender.add_argument("--to", required=True)
    sender.add_argument("--subject", default="")
    sender.add_argument("--body", default="")
    sender.add_argument("--attach", action="append", default=[])
    _common(sender)

    fetcher = sub.add_parser("fetch", help="retrieve the inbox over POP3")
    fetcher.add_argument("--user", required=True)
    fetcher.add_argument("--password", required=True)
    fetcher.add_argument("--delete", action="store_true",
                         help="delete complete transfers on QUIT; partial groups are kept")
    _common(fetcher)

    args = parser.parse_args(argv)
    setup_logging()
    cfg = CONFIG

    if cfg["users"].get(args.user) != args.password:
        print("error: invalid credentials for %s" % args.user, file=sys.stderr)
        return 2

    if args.command == "send":
        try:
            rows = tiering.send(cfg, args.user, args.to, args.subject, args.body,
                                args.attach, host=args.host, smtp_port=args.smtp_port,
                                ref_port=args.ref_port)
        except ValueError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 1
        except (SMTPError, OSError) as exc:
            print("error: send failed: %s" % exc, file=sys.stderr)
            return 1
        print()
        print("%-28s %10s  %-10s %s" % ("FILE", "SIZE", "TIER", "DETAIL"))
        for row in rows:
            detail = "%d fragments" % row["fragments"] if row["fragments"] else \
                row.get("ref_id", "")
            print("%-28s %10s  %-10s %s" % (row["file"], human(row["size"]),
                                            row["tier"], detail))
        return 0

    try:
        rows = fetch_inbox(cfg, args.user, args.password, host=args.host,
                           pop3_port=args.pop3_port, ref_port=args.ref_port,
                           delete=args.delete)
    except (POP3Error, OSError) as exc:
        print("error: fetch failed: %s" % exc, file=sys.stderr)
        return 1
    print()
    print("Inbox for %s@%s - %d logical message(s)" % (args.user, cfg["domain"], len(rows)))
    print("%-24s %-32s %-10s %-6s %s" % ("FROM", "SUBJECT", "TIER", "FRAG", "STATUS"))
    print("-" * 104)
    for row in rows:
        print("%-24s %-32s %-10s %-6s %s" % (row["from"][:24], row["subject"][:32],
                                             row["tier"], row["fragments"] or "-",
                                             row["status"]))
        for path in row["saved"]:
            print("    saved: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
