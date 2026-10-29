import hashlib
import json
import os
import socket
import uuid

from ..common.lineio import CRLFB, log
from ..config import human
from .mime_builder import _ascii_header, build_message, to_wire
from .smtp_client import send_mail

TAG = "CLIENT"


def client_log(fmt, *args):
    log.info("[%s] " + fmt, TAG, *args)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def choose_tier(size, cfg):
    # tier is decided on RAW bytes, before base64
    if size <= cfg["inline_max"]:
        return "inline"
    if size <= cfg["reference_max"]:
        return "reference"
    if size <= cfg["hard_max"]:
        return "fragment"
    return "reject"


def attach_inline(name, data):
    return (name, data)


def upload_to_store(host, port, filename, data):
    # raw-socket HTTP PUT /ref: every client in this project is written by us
    head = ("PUT /ref HTTP/1.0\r\nHost: %s:%d\r\nX-Filename: %s\r\n"
            "Content-Type: application/octet-stream\r\nContent-Length: %d\r\n\r\n"
            % (host, port, _ascii_header(filename), len(data)))
    with socket.create_connection((host, port), timeout=120) as sock:
        sock.sendall(head.encode("ascii") + data)
        resp = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            resp += chunk
    headers, _, body = resp.partition(b"\r\n\r\n")
    status = headers.split(CRLFB)[0].decode("latin-1")
    if " 201" not in status:
        raise RuntimeError("reference store PUT failed: %s" % status)
    return json.loads(body.decode("utf-8"))["id"]


def add_reference(headers, ref_id, filename, size, digest):
    headers["X-Transfer-Mode"] = "reference"
    headers["X-Ref-ID"] = ref_id
    headers["X-Ref-Filename"] = filename
    headers["X-File-Size"] = str(size)
    headers["X-File-SHA256"] = digest
    return headers


def split(data, chunk_size):
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def send_fragment(host, smtp_port, sender, to, subject, body, name, chunk,
                  index, total, frag_id, digest):
    headers = {
        "X-Transfer-Mode": "fragment",
        "X-Fragment-ID": frag_id,
        "X-Fragment-Index": str(index),
        "X-Fragment-Total": str(total),
        "X-File-SHA256": digest,
        "X-Original-Filename": name,
    }
    msg = build_message(sender, to, "[fragment %d/%d] %s" % (index, total, subject),
                        body if index == 1 else "",
                        [("%s.part%03d" % (name, index), chunk)], headers)
    send_mail(host, smtp_port, sender, [to], to_wire(msg))


def reject(reason):
    raise ValueError(reason)


def send(cfg, sender, to, subject, body, paths, host=None, smtp_port=None, ref_port=None):
    host = host or cfg["host"]
    smtp_port = smtp_port or cfg["smtp_port"]
    ref_port = ref_port or cfg["ref_port"]
    if "@" not in sender:
        sender = "%s@%s" % (sender, cfg["domain"])
    if "@" not in to:
        to = "%s@%s" % (to, cfg["domain"])

    inline, results = [], []
    for path in paths:
        with open(path, "rb") as fh:
            data = fh.read()
        name = os.path.basename(path)
        size = len(data)
        digest = sha256_bytes(data)
        tier = choose_tier(size, cfg)
        row = {"file": name, "size": size, "tier": tier, "fragments": 0, "sha256": digest}

        if tier == "reject":
            client_log("%s %s -> tier: rejected (%d bytes over the %d byte hard limit)",
                       name, human(size), size, cfg["hard_max"])
            reject("exceeds 25 MB limit")
        elif tier == "inline":
            client_log("%s %s -> tier: inline", name, human(size))
            inline.append(attach_inline(name, data))
        elif tier == "reference":
            ref_id = upload_to_store(host, ref_port, name, data)
            client_log("%s %s -> tier: reference (ref id %s)", name, human(size), ref_id)
            headers = add_reference({}, ref_id, name, size, digest)
            note = ("%s\n\n[LocalMail] %s (%s) was uploaded to the reference store as %s.\n"
                    "The receiving client downloads and hash-checks it on retrieval."
                    % (body, name, human(size), ref_id))
            send_mail(host, smtp_port, sender, [to],
                      to_wire(build_message(sender, to, subject, note, [], headers)))
            client_log("sent reference mail for %s (no attachment bytes in the mail)", name)
            row["ref_id"] = ref_id
        else:
            chunks = split(data, cfg["chunk_size"])
            frag_id = uuid.uuid4().hex
            row["fragments"] = len(chunks)
            row["fragment_id"] = frag_id
            client_log("%s %s -> tier: fragment (%d fragments of %s)",
                       name, human(size), len(chunks), human(cfg["chunk_size"]))
            for index, chunk in enumerate(chunks, 1):
                send_fragment(host, smtp_port, sender, to, subject, body, name, chunk,
                              index, len(chunks), frag_id, digest)
                client_log("sent fragment %d/%d (%s)", index, len(chunks), human(len(chunk)))
        results.append(row)

    if inline:
        send_mail(host, smtp_port, sender, [to],
                  to_wire(build_message(sender, to, subject, body, inline,
                                        {"X-Transfer-Mode": "inline"})))
        client_log("sent inline mail with %d attachment(s)", len(inline))
    elif not paths:
        send_mail(host, smtp_port, sender, [to],
                  to_wire(build_message(sender, to, subject, body, [], None)))
        client_log("sent mail with no attachments")
    return results


def preview(path, cfg):
    # used by the GUI compose window to show the tier before sending
    size = os.path.getsize(path)
    return os.path.basename(path), size, choose_tier(size, cfg)
