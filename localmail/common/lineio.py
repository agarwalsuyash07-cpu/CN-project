import logging

CRLF = "\r\n"
CRLFB = b"\r\n"
LOG_LIMIT = 120

log = logging.getLogger("localmail")


def setup_logging(level=logging.INFO):
    logging.basicConfig(level=level, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log.setLevel(level)


def truncate(text, limit=LOG_LIMIT):
    flat = text.replace("\r\n", "\\r\\n").replace("\n", "\\n")
    if len(flat) <= limit:
        return flat
    return "%s... <%d chars total>" % (flat[:limit], len(flat))


def log_line(tag, direction, text):
    # every protocol log line goes through here, so the password is masked in one place
    if text[:5].upper() == "PASS ":
        text = "PASS ****"
    log.info("[%s] %s: %s", tag, direction, truncate(text))


class LineReader:
    # buffered reader: survives partial socket reads, splits on LF and drops a trailing CR
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.eof = False

    def readline(self):
        while True:
            cut = self.buf.find(b"\n")
            if cut >= 0:
                line, self.buf = self.buf[:cut], self.buf[cut + 1:]
                return line[:-1] if line.endswith(b"\r") else line
            if self.eof:
                if not self.buf:
                    return None
                line, self.buf = self.buf, b""
                return line
            chunk = self.sock.recv(8192)
            if chunk:
                self.buf += chunk
            else:
                self.eof = True


def recv_lines(reader):
    # yields decoded protocol lines until the peer closes the connection
    while True:
        raw = reader.readline()
        if raw is None:
            return
        yield raw.decode("utf-8", "replace")


def send(sock, text, tag=None):
    sock.sendall(text.encode("utf-8") + CRLFB)
    if tag:
        log_line(tag, "S", text)


def send_bytes(sock, data):
    sock.sendall(data)


def dot_stuff(data):
    # RFC 5321 transparency: a body line starting with "." gets one extra dot
    out = []
    for line in data.split(CRLFB):
        out.append(b"." + line if line.startswith(b".") else line)
    return CRLFB.join(out)
