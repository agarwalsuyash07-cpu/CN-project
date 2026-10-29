import socket
import threading
from email.utils import formatdate

from ..common.lineio import CRLFB, LineReader, log, log_line, recv_lines, send

TAG = "SMTP"


def parse_addr(arg):
    # "FROM:<suyash@localmail>" / "TO:<kapish@localmail> SIZE=123" -> "suyash@localmail"
    _, _, rest = arg.partition(":")
    rest = rest.strip()
    if rest.startswith("<"):
        end = rest.find(">")
        if end < 0:
            return None
        return rest[1:end].strip() or None
    return rest.split()[0] if rest else None


def mailbox_exists(addr, cfg):
    user, _, domain = addr.partition("@")
    return domain.lower() == cfg["domain"].lower() and user in cfg["users"]


def read_until_dot(reader, limit):
    # reads to <CRLF>.<CRLF>, undoes dot-stuffing, keeps draining after the limit trips
    lines, total, oversize = [], 0, False
    while True:
        raw = reader.readline()
        if raw is None or raw == b".":
            break
        if raw.startswith(b"."):
            raw = raw[1:]
        total += len(raw) + 2
        if total > limit:
            oversize = True
        else:
            lines.append(raw)
    data = CRLFB.join(lines)
    return (data + CRLFB if data else b""), oversize


def store_with_lock(store, user, data):
    return store.store_with_lock(user, data)


def add_received(data, sender, rcpts, peer, domain):
    header = "Received: from %s by %s (LocalMail SMTP) for %s; %s" % (
        peer[0], domain, " ".join(rcpts), formatdate(localtime=True))
    return header.encode("utf-8") + CRLFB + data


def greet(conn, cmd, arg, peer, cfg):
    if cmd == "HELO":
        send(conn, "250 OK", TAG)
        return
    send(conn, "250-%s Hello %s" % (cfg["domain"], arg.strip() or peer[0]), TAG)
    send(conn, "250-SIZE %d" % cfg["hard_max"], TAG)
    send(conn, "250 OK", TAG)


def handle_client(conn, peer, cfg, store):
    reader = LineReader(conn)
    send(conn, "220 %s SMTP ready" % cfg["domain"], TAG)
    state, sender, rcpts = "INIT", None, []
    for line in recv_lines(reader):
        log_line(TAG, "C", line)
        cmd, _, arg = line.partition(" ")
        cmd = cmd.strip().upper()
        if cmd in ("EHLO", "HELO"):
            greet(conn, cmd, arg, peer, cfg)
            state, sender, rcpts = "READY", None, []
        elif cmd == "MAIL":
            addr = parse_addr(arg)
            if state != "READY":
                send(conn, "503 Bad sequence of commands", TAG)
            elif addr is None:
                send(conn, "501 Syntax error", TAG)
            else:
                sender, rcpts, state = addr, [], "MAIL"
                send(conn, "250 OK", TAG)
        elif cmd == "RCPT":
            addr = parse_addr(arg)
            if state not in ("MAIL", "RCPT"):
                send(conn, "503 Bad sequence of commands", TAG)
            elif addr is None:
                send(conn, "501 Syntax error", TAG)
            elif not mailbox_exists(addr, cfg):
                send(conn, "550 No such user", TAG)
            else:
                rcpts.append(addr)
                state = "RCPT"
                send(conn, "250 OK", TAG)
        elif cmd == "DATA":
            if state != "RCPT":
                send(conn, "503 Bad sequence of commands", TAG)
                continue
            send(conn, "354 End data with <CRLF>.<CRLF>", TAG)
            data, oversize = read_until_dot(reader, cfg["hard_max"])
            log_line(TAG, "C", "<%d bytes of message data>" % len(data))
            if oversize:
                send(conn, "552 Message size exceeds limit", TAG)
            else:
                data = add_received(data, sender, rcpts, peer, cfg["domain"])
                for rcpt in rcpts:
                    store_with_lock(store, rcpt.partition("@")[0], data)
                send(conn, "250 Message accepted", TAG)
            sender, rcpts, state = None, [], "READY"
        elif cmd == "RSET":
            sender, rcpts = None, []
            state = "READY" if state != "INIT" else "INIT"
            send(conn, "250 OK", TAG)
        elif cmd == "NOOP":
            send(conn, "250 OK", TAG)
        elif cmd == "QUIT":
            send(conn, "221 Bye", TAG)
            break
        elif cmd:
            send(conn, "500 Command not recognized", TAG)
        else:
            send(conn, "501 Syntax error", TAG)


class SMTPServer:
    # one thread per connection, raw TCP sockets
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.sock = None
        self.port = cfg["smtp_port"]
        self._stop = False

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.cfg["host"], self.cfg["smtp_port"]))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        return self.port

    def _accept(self):
        while not self._stop:
            try:
                conn, peer = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn, peer), daemon=True).start()

    def _serve(self, conn, peer):
        try:
            handle_client(conn, peer, self.cfg, self.store)
        except OSError as exc:
            log.warning("[%s] connection from %s dropped: %s", TAG, peer[0], exc)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop = True
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
