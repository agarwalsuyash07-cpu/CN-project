import unittest
from email.parser import BytesParser
from email.policy import compat32

from localmail.client.mime_builder import build_message, parse_message, to_wire

NON_ASCII = "रिपोर्ट_é.txt"


class TestMIME(unittest.TestCase):
    def build(self, attachments=(), subject="report", body="body text", headers=None):
        return to_wire(build_message("suyash@localmail", "kapish@localmail",
                                     subject, body, attachments, headers))

    def parts(self, raw):
        return BytesParser(policy=compat32).parsebytes(raw).get_payload()

    def test_required_top_level_headers(self):
        head = self.build([("a.bin", b"x")]).split(b"\r\n\r\n", 1)[0].decode()
        self.assertIn("MIME-Version: 1.0", head)
        self.assertIn("Content-Type: multipart/mixed;", head)
        self.assertIn("boundary=", head)

    def test_boundary_is_unique_per_message(self):
        one = build_message("a@localmail", "b@localmail", "s", "b").get_boundary()
        two = build_message("a@localmail", "b@localmail", "s", "b").get_boundary()
        self.assertNotEqual(one, two)
        self.assertTrue(one.startswith("LocalMail-"))

    def test_body_part_comes_first(self):
        parts = self.parts(self.build([("a.bin", b"x"), ("b.bin", b"y")]))
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0].get_content_type(), "text/plain")

    def test_every_attachment_is_octet_stream_base64_attachment(self):
        parts = self.parts(self.build([("a.bin", b"\x00\xff"), (NON_ASCII, b"hello")]))
        attachments = parts[1:]
        self.assertEqual(len(attachments), 2)
        for part in attachments:
            self.assertEqual(part.get_content_type(), "application/octet-stream")
            self.assertEqual(part.get("Content-Transfer-Encoding"), "base64")
            self.assertTrue(part.get("Content-Disposition", "").startswith("attachment"))

    def test_rfc2231_used_for_non_ascii_filename(self):
        raw = self.build([(NON_ASCII, b"hello")])
        self.assertIn(b"filename*=utf-8''", raw)
        self.assertNotIn(NON_ASCII.encode("utf-8"), raw)

    def test_ascii_filename_stays_plain(self):
        self.assertIn(b'filename="plain.txt"', self.build([("plain.txt", b"hello")]))

    def test_non_ascii_filename_and_subject_round_trip(self):
        payload = bytes(range(256)) * 4
        parsed = parse_message(self.build([(NON_ASCII, payload)], subject="नमस्ते report"))
        self.assertEqual(parsed["subject"], "नमस्ते report")
        self.assertEqual(parsed["body"], "body text")
        self.assertEqual(parsed["attachments"], [(NON_ASCII, payload)])

    def test_binary_payload_survives_base64(self):
        payload = bytes(range(256))
        parsed = parse_message(self.build([("bin.dat", payload)]))
        self.assertEqual(parsed["attachments"][0][1], payload)

    def test_wire_format_is_crlf_only(self):
        raw = self.build([("a.bin", b"x" * 4096)])
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_custom_x_headers_survive(self):
        parsed = parse_message(self.build(
            [], headers={"X-Transfer-Mode": "reference", "X-Ref-ID": "a" * 32,
                         "X-Original-Filename": NON_ASCII}))
        self.assertEqual(parsed["headers"]["X-Transfer-Mode"], "reference")
        self.assertEqual(parsed["headers"]["X-Ref-ID"], "a" * 32)
        self.assertEqual(parsed["headers"]["X-Original-Filename"], NON_ASCII)

    def test_message_with_no_attachments_still_multipart(self):
        parts = self.parts(self.build([]))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].get_content_type(), "text/plain")


if __name__ == "__main__":
    unittest.main()


class TestHeaderFolding(unittest.TestCase):
    def test_folded_hash_header_is_unfolded(self):
        # regression: Python 3.11 folds "X-File-SHA256: <64 hex>" past 78 chars
        digest = "a" * 64
        raw = ("From: a@localmail\r\nX-File-SHA256:\r\n " + digest + "\r\n\r\nbody\r\n").encode()
        parsed = parse_message(raw)
        self.assertEqual(parsed["headers"]["X-File-SHA256"], digest)
