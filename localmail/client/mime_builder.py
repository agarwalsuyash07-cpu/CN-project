import re
import uuid
from email import encoders
from email.header import Header, decode_header, make_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.policy import compat32
from email.utils import formatdate, make_msgid

WIRE = compat32.clone(linesep="\r\n")


def _ascii_header(value):
    # header values must be ASCII on the wire: RFC 2047 encoded-word otherwise
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return Header(value, "utf-8").encode()


def decode_hdr(value):
    # unfold first: older Pythons fold long headers (e.g. a 64-char SHA-256) onto a new line
    value = re.sub(r"\r?\n[ \t]+", " ", value or "").strip()
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value


def attachment_part(filename, data):
    part = MIMEBase("application", "octet-stream")
    part.set_payload(data)
    encoders.encode_base64(part)
    try:
        filename.encode("ascii")
        part.add_header("Content-Disposition", "attachment", filename=filename)
    except UnicodeEncodeError:
        # RFC 2231 for non-ASCII names: filename*=utf-8''...
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
    return part


def build_message(sender, to, subject, body, attachments=(), headers=None):
    msg = MIMEMultipart("mixed", boundary="LocalMail-%s" % uuid.uuid4().hex)
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = _ascii_header(subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="localmail")
    for key, value in (headers or {}).items():
        msg[key] = _ascii_header(str(value))
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for filename, data in attachments:
        msg.attach(attachment_part(filename, data))
    return msg


def to_wire(msg):
    return msg.as_bytes(policy=WIRE)


def parse_message(raw):
    msg = BytesParser(policy=compat32).parsebytes(raw)
    out = {
        "from": decode_hdr(msg.get("From", "")),
        "to": decode_hdr(msg.get("To", "")),
        "subject": decode_hdr(msg.get("Subject", "")),
        "date": msg.get("Date", ""),
        "headers": {k: decode_hdr(v) for k, v in msg.items()},
        "body": "",
        "attachments": [],
    }
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        is_body = part.get_content_type() == "text/plain" and "attachment" not in disposition
        if is_body and not out["body"]:
            payload = part.get_payload(decode=True) or b""
            out["body"] = payload.decode(part.get_content_charset() or "utf-8", "replace")
        else:
            name = part.get_filename() or "attachment.bin"
            out["attachments"].append((name, part.get_payload(decode=True) or b""))
    return out
