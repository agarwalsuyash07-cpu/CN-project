import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from ..common.lineio import REUSE_ADDR, log
from ..config import data_dir

TAG = "HTTP"
HEX = "0123456789abcdef"


def _valid_id(rid):
    # reject anything that is not a bare uuid4 hex: blocks path traversal
    return len(rid) == 32 and all(c in HEX for c in rid)


def ref_dir(cfg):
    path = os.path.join(data_dir(cfg), "refstore")
    os.makedirs(path, exist_ok=True)
    return path


class RefHandler(BaseHTTPRequestHandler):
    server_version = "LocalMailRefStore/1.0"

    def log_message(self, fmt, *args):
        log.info("[%s] %s %s", TAG, self.address_string(), fmt % args)

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        if self.path != "/ref":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        data = self.rfile.read(length)
        rid = uuid4().hex
        with open(os.path.join(ref_dir(self.server.cfg), rid), "wb") as fh:
            fh.write(data)
        log.info("[%s] PUT /ref -> id=%s name=%s %d bytes", TAG, rid,
                 self.headers.get("X-Filename", "-"), len(data))
        self._json(201, {"id": rid})

    def do_GET(self):
        prefix = "/ref/"
        if not self.path.startswith(prefix):
            self._json(404, {"error": "not found"})
            return
        rid = self.path[len(prefix):]
        path = os.path.join(ref_dir(self.server.cfg), rid)
        if not _valid_id(rid) or not os.path.exists(path):
            log.info("[%s] GET /ref/%s -> 404", TAG, rid)
            self._json(404, {"error": "not found"})
            return
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        log.info("[%s] GET /ref/%s -> 200 %d bytes", TAG, rid, len(data))


class _HTTPServer(ThreadingHTTPServer):
    allow_reuse_address = REUSE_ADDR


class RefStoreServer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.httpd = None
        self.port = cfg["ref_port"]

    def start(self):
        self.httpd = _HTTPServer((self.cfg["host"], self.cfg["ref_port"]), RefHandler)
        self.httpd.cfg = self.cfg
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
