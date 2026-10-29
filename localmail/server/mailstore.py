import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser

from ..config import data_dir

try:
    import fcntl

    def _flock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _funlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
except ImportError:
    import msvcrt

    def _flock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _funlock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _decode(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _headers(data):
    msg = BytesHeaderParser().parsebytes(data)
    return msg.get("From", ""), _decode(msg.get("Subject", ""))


class MailStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = data_dir(cfg)
        self.db_path = os.path.join(self.root, "index.db")
        self._locks = {}
        self._guard = threading.Lock()
        os.makedirs(self.root, exist_ok=True)
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _write(self, sql, params=(), many=False):
        conn = self._conn()
        try:
            with conn:
                conn.executemany(sql, params) if many else conn.execute(sql, params)
        finally:
            conn.close()

    def _query(self, sql, params=()):
        conn = self._conn()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _init_db(self):
        self._write(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, "
            "filename TEXT NOT NULL, size INTEGER NOT NULL, sender TEXT, "
            "subject TEXT, received_at TEXT, deleted INTEGER NOT NULL DEFAULT 0)")
        self._write("CREATE INDEX IF NOT EXISTS idx_user ON messages(user, deleted)")

    def _lock_for(self, user):
        with self._guard:
            if user not in self._locks:
                self._locks[user] = threading.Lock()
            return self._locks[user]

    def maildir(self, user):
        box = os.path.join(self.root, "mail", user)
        for sub in ("tmp", "new", "cur"):
            os.makedirs(os.path.join(box, sub), exist_ok=True)
        return box

    def store_with_lock(self, user, msg):
        # per-mailbox threading lock + lock file: concurrent deliveries cannot corrupt a mailbox
        data = msg if isinstance(msg, bytes) else msg.encode("utf-8")
        box = self.maildir(user)
        name = "%d.%s.localmail" % (int(time.time()), uuid.uuid4().hex)
        sender, subject = _headers(data)
        received = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock_for(user):
            with open(os.path.join(box, "lock"), "a+b") as lockfh:
                _flock(lockfh)
                try:
                    tmp = os.path.join(box, "tmp", name)
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, os.path.join(box, "new", name))
                    self._write(
                        "INSERT INTO messages (user, filename, size, sender, subject,"
                        " received_at, deleted) VALUES (?,?,?,?,?,?,0)",
                        (user, name, len(data), sender, subject, received))
                finally:
                    _funlock(lockfh)
        return name

    def list_messages(self, user):
        return [tuple(r) for r in self._query(
            "SELECT id, filename, size FROM messages WHERE user=? AND deleted=0 ORDER BY id",
            (user,))]

    def _path(self, user, filename):
        box = self.maildir(user)
        for sub in ("new", "cur"):
            candidate = os.path.join(box, sub, filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def read_message(self, user, filename):
        path = self._path(user, filename)
        if path is None:
            raise FileNotFoundError(filename)
        with open(path, "rb") as fh:
            return fh.read()

    def mark_retrieved(self, user, filenames):
        # Maildir semantics: a retrieved message moves from new/ to cur/
        box = self.maildir(user)
        with self._lock_for(user):
            for name in filenames:
                src = os.path.join(box, "new", name)
                if os.path.exists(src):
                    os.replace(src, os.path.join(box, "cur", name))

    def commit_deletes(self, user, filenames):
        if not filenames:
            return 0
        with self._lock_for(user):
            for name in filenames:
                path = self._path(user, name)
                if path:
                    os.remove(path)
            self._write("UPDATE messages SET deleted=1 WHERE user=? AND filename=?",
                        [(user, n) for n in filenames], many=True)
        return len(filenames)

    def stat(self, user):
        rows = self.list_messages(user)
        return len(rows), sum(r[2] for r in rows)

    def index_count(self, user, include_deleted=False):
        sql = "SELECT COUNT(*) FROM messages WHERE user=?"
        if not include_deleted:
            sql += " AND deleted=0"
        return self._query(sql, (user,))[0][0]
