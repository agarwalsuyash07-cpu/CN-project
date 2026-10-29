import os
import shutil
import socket
import tempfile
import unittest

from localmail.common.lineio import LineReader
from localmail.config import CONFIG
from localmail.server.run_server import start_all

HOST = "127.0.0.1"


def make_cfg(**overrides):
    cfg = dict(CONFIG)
    cfg["data_dir"] = tempfile.mkdtemp(prefix="localmail-test-")
    cfg["host"] = HOST
    cfg["smtp_port"] = 0
    cfg["pop3_port"] = 0
    cfg["ref_port"] = 0
    cfg.update(overrides)
    return cfg


def write_file(directory, name, size, fill=None):
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(fill if fill is not None else os.urandom(size))
    return path


class RawSession:
    # hand-driven protocol session, the netcat equivalent
    def __init__(self, port, host=HOST, timeout=15):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.reader = LineReader(self.sock)

    def line(self):
        raw = self.reader.readline()
        return None if raw is None else raw.decode("utf-8", "replace")

    def lines(self, count):
        return [self.line() for _ in range(count)]

    def cmd(self, text):
        self.sock.sendall(text.encode("utf-8") + b"\r\n")
        return self.line()

    def send_raw(self, data):
        self.sock.sendall(data)

    def until_dot(self):
        out = []
        while True:
            line = self.line()
            if line is None or line == ".":
                return out
            out.append(line)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class ServerCase(unittest.TestCase):
    overrides = {}

    def setUp(self):
        self.cfg = make_cfg(**self.overrides)
        self.store, self.smtp, self.pop3, self.ref = start_all(self.cfg)
        self.smtp_port = self.smtp.port
        self.pop3_port = self.pop3.port
        self.ref_port = self.ref.port
        self.work = tempfile.mkdtemp(prefix="localmail-work-")
        self.downloads = os.path.join(self.work, "downloads")

    def tearDown(self):
        self.smtp.stop()
        self.pop3.stop()
        self.ref.stop()
        shutil.rmtree(self.cfg["data_dir"], ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def deliver(self, body, sender="suyash@localmail", rcpt="kapish@localmail"):
        # minimal raw-socket delivery used to seed a mailbox
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO test")
        session.lines(2)
        session.cmd("MAIL FROM:<%s>" % sender)
        session.cmd("RCPT TO:<%s>" % rcpt)
        session.cmd("DATA")
        session.send_raw(body.encode("utf-8") + b"\r\n.\r\n")
        reply = session.line()
        session.cmd("QUIT")
        session.close()
        return reply
