import socket

from ..common.lineio import CRLFB, LineReader


class POP3Error(Exception):
    pass


class POP3Client:
    def __init__(self, host, port, timeout=60):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.reader = None
        self.greeting = ""

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.reader = LineReader(self.sock)
        self.greeting = self._ok()
        return self

    def _line(self):
        raw = self.reader.readline()
        if raw is None:
            raise POP3Error("connection closed by server")
        return raw.decode("utf-8", "replace")

    def _ok(self):
        line = self._line()
        if not line.startswith("+OK"):
            raise POP3Error(line)
        return line

    def _cmd(self, text):
        self.sock.sendall(text.encode("utf-8") + CRLFB)
        return self._ok()

    def _multiline(self):
        out = []
        while True:
            line = self._line()
            if line == ".":
                return out
            out.append(line)

    def user(self, name):
        return self._cmd("USER %s" % name)

    def pass_(self, password):
        return self._cmd("PASS %s" % password)

    def login(self, name, password):
        self.user(name)
        return self.pass_(password)

    def stat(self):
        parts = self._cmd("STAT").split()
        return int(parts[1]), int(parts[2])

    def list(self):
        self._cmd("LIST")
        return [(int(p[0]), int(p[1])) for p in (l.split() for l in self._multiline())]

    def retr(self, n):
        self._cmd("RETR %d" % n)
        chunks = []
        while True:
            raw = self.reader.readline()
            if raw is None:
                raise POP3Error("connection closed during RETR")
            if raw == b".":
                break
            if raw.startswith(b"."):
                raw = raw[1:]
            chunks.append(raw)
        return CRLFB.join(chunks) + (CRLFB if chunks else b"")

    def dele(self, n):
        return self._cmd("DELE %d" % n)

    def quit(self):
        try:
            return self._cmd("QUIT")
        finally:
            self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
