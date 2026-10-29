import socket

from ..common.lineio import CRLFB, LineReader, dot_stuff


class SMTPError(Exception):
    pass


class SMTPClient:
    def __init__(self, host, port, timeout=60):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.reader = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.reader = LineReader(self.sock)
        self._expect("220")
        return self

    def _reply(self):
        lines = []
        while True:
            raw = self.reader.readline()
            if raw is None:
                raise SMTPError("connection closed by server")
            line = raw.decode("utf-8", "replace")
            lines.append(line)
            if len(line) < 4 or line[3] != "-":
                return line[:3], lines

    def _expect(self, code):
        got, lines = self._reply()
        if not got.startswith(code):
            raise SMTPError("expected %s, got %r" % (code, lines[-1]))
        return got, lines

    def _cmd(self, text, code):
        self.sock.sendall(text.encode("utf-8") + CRLFB)
        return self._expect(code)

    def ehlo(self, name="localmail-client"):
        return self._cmd("EHLO %s" % name, "250")

    def send_message(self, sender, rcpts, data):
        self._cmd("MAIL FROM:<%s>" % sender, "250")
        for rcpt in rcpts:
            self._cmd("RCPT TO:<%s>" % rcpt, "250")
        self._cmd("DATA", "354")
        body = data if data.endswith(CRLFB) else data + CRLFB
        self.sock.sendall(dot_stuff(body) + b"." + CRLFB)
        return self._expect("250")

    def quit(self):
        try:
            self._cmd("QUIT", "221")
        finally:
            self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def send_mail(host, port, sender, rcpts, data, helo="localmail-client"):
    client = SMTPClient(host, port).connect()
    try:
        client.ehlo(helo)
        client.send_message(sender, rcpts, data)
        client.quit()
    except (SMTPError, OSError):
        client.close()
        raise
    return True
