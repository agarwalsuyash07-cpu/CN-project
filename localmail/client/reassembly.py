import os
import socket

from ..common.lineio import CRLFB
from ..config import ROOT, human
from .mime_builder import parse_message
from .pop3_client import POP3Client
from .tiering import client_log, sha256_bytes


def http_get(host, port, ref_id):
    # raw-socket HTTP GET /ref/<id>
    request = "GET /ref/%s HTTP/1.0\r\nHost: %s:%d\r\n\r\n" % (ref_id, host, port)
    with socket.create_connection((host, port), timeout=120) as sock:
        sock.sendall(request.encode("ascii"))
        resp = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            resp += chunk
    headers, _, body = resp.partition(b"\r\n\r\n")
    status = headers.split(CRLFB)[0].decode("latin-1")
    if " 200" not in status:
        raise RuntimeError("reference store GET failed: %s" % status)
    return body


def downloads_dir(user, out_dir=None):
    path = out_dir or os.path.join(ROOT, "downloads", user)
    os.makedirs(path, exist_ok=True)
    return path


def _save(directory, name, data):
    path = os.path.join(directory, os.path.basename(name) or "attachment.bin")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _strip_prefix(subject):
    if subject.startswith("[fragment ") and "] " in subject:
        return subject.split("] ", 1)[1]
    return subject


def _handle_reference(msg, host, ref_port, target):
    headers = msg["headers"]
    ref_id = headers.get("X-Ref-ID", "")
    name = headers.get("X-Ref-Filename", "reference.bin")
    digest = headers.get("X-File-SHA256", "")
    try:
        data = http_get(host, ref_port, ref_id)
    except (OSError, RuntimeError) as exc:
        client_log("reference %s download failed: %s", ref_id, exc)
        return {"status": "incomplete: reference download failed", "attachments": [name]}
    got = sha256_bytes(data)
    if digest and got != digest:
        client_log("SHA-256 mismatch for %s (expected %s..., got %s...) -> not saved",
                   name, digest[:16], got[:16])
        return {"status": "incomplete: SHA-256 mismatch", "attachments": [name]}
    client_log("downloaded reference %s %s from the store (ref id %s)",
               name, human(len(data)), ref_id)
    path = _save(target, name, data)
    client_log("SHA-256 match: %s -> saved %s", got, path)
    return {"status": "ok", "saved": [path], "attachments": [name]}


def _handle_group(frag_id, items, target):
    first_msg = min(items, key=lambda it: int(it[1]["headers"].get("X-Fragment-Index", "0")))[1]
    headers = first_msg["headers"]
    total = int(headers.get("X-Fragment-Total", len(items)))
    name = headers.get("X-Original-Filename", "reassembled.bin")
    digest = headers.get("X-File-SHA256", "")
    row = {"numbers": sorted(n for n, _ in items), "from": first_msg["from"],
           "subject": _strip_prefix(first_msg["subject"]), "date": first_msg["date"],
           "tier": "fragment", "status": "ok", "saved": [], "attachments": [name],
           "fragments": "%d/%d" % (len(items), total), "body": first_msg["body"]}

    by_index = {}
    for _, msg in items:
        index = int(msg["headers"].get("X-Fragment-Index", "0"))
        by_index[index] = msg["attachments"][0][1] if msg["attachments"] else b""
    missing = [i for i in range(1, total + 1) if i not in by_index]
    if missing:
        row["status"] = "incomplete: waiting for %d of %d fragments" % (len(missing), total)
        client_log("%s for %s", row["status"], frag_id[:8])
        client_log("holding %d fragment mails on server", len(items))
        return row, False

    data = b"".join(by_index[i] for i in range(1, total + 1))
    client_log("received %d/%d fragments for %s, reassembled %s",
               total, total, frag_id[:8], human(len(data)))
    got = sha256_bytes(data)
    if digest and got != digest:
        row["status"] = "incomplete: SHA-256 mismatch"
        client_log("SHA-256 mismatch for %s (expected %s..., got %s...) -> not saved",
                   name, digest[:16], got[:16])
        return row, False
    path = _save(target, name, data)
    row["saved"] = [path]
    client_log("SHA-256 match: %s -> saved %s", got, path)
    return row, True


def process(cfg, user, messages, host=None, ref_port=None, out_dir=None):
    host = host or cfg["host"]
    ref_port = ref_port or cfg["ref_port"]
    target = downloads_dir(user, out_dir)
    rows, deletable, groups = [], [], {}

    for number, msg in messages:
        frag_id = msg["headers"].get("X-Fragment-ID")
        if frag_id:
            groups.setdefault(frag_id, []).append((number, msg))
            continue
        mode = msg["headers"].get("X-Transfer-Mode", "inline")
        row = {"numbers": [number], "from": msg["from"], "subject": msg["subject"],
               "date": msg["date"], "tier": mode, "status": "ok", "saved": [],
               "attachments": [], "fragments": "", "body": msg["body"]}
        if mode == "reference":
            row.update(_handle_reference(msg, host, ref_port, target))
        else:
            for name, data in msg["attachments"]:
                row["attachments"].append(name)
                row["saved"].append(_save(target, name, data))
                client_log("%s %s -> tier: inline, saved %s",
                           name, human(len(data)), row["saved"][-1])
        if row["status"] == "ok":
            deletable.extend(row["numbers"])
        rows.append(row)

    for frag_id, items in groups.items():
        row, complete = _handle_group(frag_id, items, target)
        rows.append(row)
        if complete:
            deletable.extend(row["numbers"])

    rows.sort(key=lambda r: min(r["numbers"]))
    return rows, sorted(deletable)


def fetch_inbox(cfg, user, password, host=None, pop3_port=None, ref_port=None,
                delete=False, out_dir=None):
    host = host or cfg["host"]
    pop3_port = pop3_port or cfg["pop3_port"]
    ref_port = ref_port or cfg["ref_port"]
    client = POP3Client(host, pop3_port).connect()
    try:
        client.login(user, password)
        count, total = client.stat()
        client_log("POP3 STAT: %d message(s), %d bytes", count, total)
        messages = []
        for number, _size in client.list():
            messages.append((number, parse_message(client.retr(number))))
        rows, deletable = process(cfg, user, messages, host, ref_port, out_dir)
        if delete:
            # only complete, hash-verified transfers are deleted; partial groups stay
            for number in deletable:
                client.dele(number)
            held = sum(len(r["numbers"]) for r in rows if r["status"] != "ok")
            client_log("marked %d message(s) deleted, held %d incomplete on server",
                       len(deletable), held)
        client.quit()
    except Exception:
        client.close()
        raise
    return rows
