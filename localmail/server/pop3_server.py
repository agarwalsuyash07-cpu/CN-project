import socket
import threading

from ..common.lineio import (CRLFB, LineReader, dot_stuff, log, log_line,
                             recv_lines, send, send_bytes)

TAG = "POP3"


class MailboxLocks:
    # a mailbox may be open in only one session at a time
    def __init__(self):
        self._guard = threading.Lock()
        self._open = set()

    def acquire(self, user):
        with self._guard:
            if user in self._open:
                return False
            self._open.add(user)
            return True

    def release(self, user):
        with self._guard:
            self._open.discard(user)


def _crlf(data):
    return data.replace(CRLFB, b"\n").replace(b"\n", CRLFB)


def _index(arg, msgs, marked):
    try:
        n = int(arg)
    except ValueError:
        return None
    return n if 1 <= n <= len(msgs) and n not in marked else None


def handle_client(conn, peer, cfg, store, locks):
    reader = LineReader(conn)
    send(conn, "+OK POP3 ready", TAG)
    state, user, locked = "AUTHORIZATION", None, None
    msgs, marked, retrieved = [], set(), set()
    try:
        for line in recv_lines(reader):
            log_line(TAG, "C", line)
            cmd, _, arg = line.partition(" ")
            cmd, arg = cmd.strip().upper(), arg.strip()

            if state == "AUTHORIZATION":
                if cmd == "USER":
                    user = arg
                    send(conn, "+OK user accepted", TAG)
                elif cmd == "PASS":
                    if not user or cfg["users"].get(user) != arg:
                        user = None
                        send(conn, "-ERR invalid credentials", TAG)
                    elif not locks.acquire(user):
                        send(conn, "-ERR mailbox already open in another session", TAG)
                    else:
                        locked = user
                        msgs = store.list_messages(user)
                        state = "TRANSACTION"
                        send(conn, "+OK logged in", TAG)
                elif cmd == "QUIT":
                    send(conn, "+OK Bye", TAG)
                    break
                elif cmd == "NOOP":
                    send(conn, "+OK", TAG)
                else:
                    send(conn, "-ERR command not valid in AUTHORIZATION state", TAG)
                continue

            if cmd == "STAT":
                live = [m for i, m in enumerate(msgs, 1) if i not in marked]
                send(conn, "+OK %d %d" % (len(live), sum(m[2] for m in live)), TAG)
            elif cmd == "LIST":
                if arg:
                    n = _index(arg, msgs, marked)
                    if n is None:
                        send(conn, "-ERR no such message", TAG)
                    else:
                        send(conn, "+OK %d %d" % (n, msgs[n - 1][2]), TAG)
                else:
                    live = [(i, m) for i, m in enumerate(msgs, 1) if i not in marked]
                    send(conn, "+OK %d messages (%d octets)"
                         % (len(live), sum(m[2] for _, m in live)), TAG)
                    for i, m in live:
                        send(conn, "%d %d" % (i, m[2]), TAG)
                    send(conn, ".", TAG)
            elif cmd == "UIDL":
                if arg:
                    n = _index(arg, msgs, marked)
                    if n is None:
                        send(conn, "-ERR no such message", TAG)
                    else:
                        send(conn, "+OK %d %s" % (n, msgs[n - 1][1]), TAG)
                else:
                    send(conn, "+OK unique-id listing follows", TAG)
                    for i, m in enumerate(msgs, 1):
                        if i not in marked:
                            send(conn, "%d %s" % (i, m[1]), TAG)
                    send(conn, ".", TAG)
            elif cmd == "RETR":
                n = _index(arg, msgs, marked)
                if n is None:
                    send(conn, "-ERR no such message", TAG)
                else:
                    data = store.read_message(user, msgs[n - 1][1])
                    body = _crlf(data)
                    if not body.endswith(CRLFB):
                        body += CRLFB
                    send(conn, "+OK %d octets" % len(data), TAG)
                    send_bytes(conn, dot_stuff(body))
                    send(conn, ".")
                    log_line(TAG, "S", "<%d octets of message content>." % len(data))
                    retrieved.add(msgs[n - 1][1])
            elif cmd == "DELE":
                n = _index(arg, msgs, marked)
                if n is None:
                    send(conn, "-ERR no such message", TAG)
                else:
                    marked.add(n)
                    send(conn, "+OK message %d marked deleted" % n, TAG)
            elif cmd == "RSET":
                marked.clear()
                send(conn, "+OK all deletion marks cleared", TAG)
            elif cmd == "NOOP":
                send(conn, "+OK", TAG)
            elif cmd == "QUIT":
                state = "UPDATE"
                store.mark_retrieved(user, sorted(retrieved))
                store.commit_deletes(user, [msgs[n - 1][1] for n in sorted(marked)])
                send(conn, "+OK Bye", TAG)
                break
            else:
                send(conn, "-ERR command not recognized", TAG)
    finally:
        # released without committing: a dropped connection must delete nothing
        if locked:
            locks.release(locked)


class POP3Server:
    # one thread per connection, raw TCP sockets
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.locks = MailboxLocks()
        self.sock = None
        self.port = cfg["pop3_port"]
        self._stop = False

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.cfg["host"], self.cfg["pop3_port"]))
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
            handle_client(conn, peer, self.cfg, self.store, self.locks)
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
