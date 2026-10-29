import os
import unittest

from localmail.client import tiering
from localmail.client.mime_builder import parse_message
from localmail.client.reassembly import fetch_inbox
from localmail.config import CONFIG, MB
from localmail.server.ref_store import ref_dir

from .helpers import HOST, ServerCase, write_file

# scaled limits keep the end-to-end tests fast; the real constants are asserted separately
SCALED = {"inline_max": 1024, "reference_max": 10240, "hard_max": 25600, "chunk_size": 2048}
NON_ASCII = "रिपोर्ट_é.txt"


class TestTierBoundaries(unittest.TestCase):
    def test_report_boundaries_with_real_constants(self):
        cases = [(1 * MB, "inline"), (1 * MB + 1, "reference"),
                 (10 * MB, "reference"), (10 * MB + 1, "fragment"),
                 (25 * MB, "fragment"), (25 * MB + 1, "reject")]
        for size, expected in cases:
            with self.subTest(size=size):
                self.assertEqual(tiering.choose_tier(size, CONFIG), expected)

    def test_small_sizes_are_inline(self):
        self.assertEqual(tiering.choose_tier(0, CONFIG), "inline")
        self.assertEqual(tiering.choose_tier(1, CONFIG), "inline")

    def test_config_matches_the_report(self):
        self.assertEqual(CONFIG["inline_max"], 1 * MB)
        self.assertEqual(CONFIG["reference_max"], 10 * MB)
        self.assertEqual(CONFIG["hard_max"], 25 * MB)
        self.assertEqual(CONFIG["chunk_size"], 2 * MB)

    def test_split_makes_2mb_chunks(self):
        data = b"x" * (15 * MB)
        chunks = tiering.split(data, 2 * MB)
        self.assertEqual(len(chunks), 8)
        self.assertEqual([len(c) for c in chunks[:7]], [2 * MB] * 7)
        self.assertEqual(len(chunks[7]), 1 * MB)
        self.assertEqual(b"".join(chunks), data)

    def test_split_exact_multiple(self):
        chunks = tiering.split(b"y" * 4096, 2048)
        self.assertEqual([len(c) for c in chunks], [2048, 2048])

    def test_reject_raises(self):
        with self.assertRaises(ValueError) as ctx:
            tiering.reject("exceeds 25 MB limit")
        self.assertEqual(str(ctx.exception), "exceeds 25 MB limit")


class TransferCase(ServerCase):
    overrides = dict(SCALED)

    def send(self, paths, subject="tiers", body="body text"):
        return tiering.send(self.cfg, "suyash", "kapish@localmail", subject, body, paths,
                            host=HOST, smtp_port=self.smtp_port, ref_port=self.ref_port)

    def fetch(self, delete=False):
        return fetch_inbox(self.cfg, "kapish", "kapish123", host=HOST,
                           pop3_port=self.pop3_port, ref_port=self.ref_port,
                           delete=delete, out_dir=self.downloads)

    def assertSameBytes(self, saved, source):
        with open(saved, "rb") as a, open(source, "rb") as b:
            self.assertEqual(a.read(), b.read())


class TestTierTransfers(TransferCase):
    def test_inline_non_ascii_round_trip(self):
        path = write_file(self.work, NON_ASCII, 500)
        self.assertEqual(self.send([path])[0]["tier"], "inline")
        rows = self.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tier"], "inline")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(os.path.basename(rows[0]["saved"][0]), NON_ASCII)
        self.assertSameBytes(rows[0]["saved"][0], path)

    def test_inline_mail_carries_the_bytes(self):
        path = write_file(self.work, "small.bin", 500)
        self.send([path])
        rows = self.store.list_messages("kapish")
        parsed = parse_message(self.store.read_message("kapish", rows[0][1]))
        self.assertEqual(len(parsed["attachments"]), 1)
        self.assertEqual(parsed["headers"]["X-Transfer-Mode"], "inline")

    def test_reference_downloaded_and_hash_verified(self):
        path = write_file(self.work, "mid.bin", 5000)
        result = self.send([path])
        self.assertEqual(result[0]["tier"], "reference")
        rows = self.fetch()
        self.assertEqual(rows[0]["tier"], "reference")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertSameBytes(rows[0]["saved"][0], path)

    def test_reference_mail_has_headers_and_no_attachment_bytes(self):
        path = write_file(self.work, "mid.bin", 5000)
        self.send([path])
        rows = self.store.list_messages("kapish")
        parsed = parse_message(self.store.read_message("kapish", rows[0][1]))
        self.assertEqual(parsed["attachments"], [])
        self.assertEqual(parsed["headers"]["X-Transfer-Mode"], "reference")
        self.assertEqual(len(parsed["headers"]["X-Ref-ID"]), 32)
        self.assertEqual(parsed["headers"]["X-Ref-Filename"], "mid.bin")
        self.assertEqual(parsed["headers"]["X-File-Size"], "5000")
        self.assertEqual(len(parsed["headers"]["X-File-SHA256"]), 64)
        self.assertIn("mid.bin", parsed["body"])
        self.assertLess(rows[0][2], 2000)

    def test_reference_hash_mismatch_is_not_saved(self):
        path = write_file(self.work, "mid.bin", 5000)
        ref_id = self.send([path])[0]["ref_id"]
        with open(os.path.join(ref_dir(self.cfg), ref_id), "wb") as fh:
            fh.write(b"tampered payload")
        rows = self.fetch()
        self.assertEqual(rows[0]["status"], "incomplete: SHA-256 mismatch")
        self.assertEqual(rows[0]["saved"], [])
        self.assertFalse(os.path.exists(os.path.join(self.downloads, "mid.bin")))

    def test_fragments_reassemble_into_one_logical_message(self):
        path = write_file(self.work, "big.bin", 15000)
        result = self.send([path])
        self.assertEqual(result[0]["tier"], "fragment")
        self.assertEqual(result[0]["fragments"], 8)
        self.assertEqual(self.store.index_count("kapish"), 8)
        rows = self.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fragments"], "8/8")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["subject"], "tiers")
        self.assertSameBytes(rows[0]["saved"][0], path)

    def test_fragment_mails_carry_the_required_headers(self):
        path = write_file(self.work, "big.bin", 15000)
        self.send([path])
        headers = []
        for _msg_id, filename, _size in self.store.list_messages("kapish"):
            headers.append(parse_message(self.store.read_message("kapish", filename))["headers"])
        self.assertEqual(len({h["X-Fragment-ID"] for h in headers}), 1)
        self.assertEqual({h["X-Fragment-Total"] for h in headers}, {"8"})
        self.assertEqual({int(h["X-Fragment-Index"]) for h in headers}, set(range(1, 9)))
        for header in headers:
            self.assertEqual(header["X-Transfer-Mode"], "fragment")
            self.assertEqual(header["X-Original-Filename"], "big.bin")
            self.assertEqual(len(header["X-File-SHA256"]), 64)

    def test_mixed_tiers_in_one_send(self):
        small = write_file(self.work, "small.bin", 500)
        mid = write_file(self.work, "mid.bin", 5000)
        big = write_file(self.work, "big.bin", 15000)
        result = self.send([small, mid, big])
        self.assertEqual([r["tier"] for r in result], ["inline", "reference", "fragment"])
        rows = self.fetch()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["status"] for r in rows}, {"ok"})
        for source in (small, mid, big):
            saved = os.path.join(self.downloads, os.path.basename(source))
            self.assertSameBytes(saved, source)

    def test_oversize_rejected_client_side(self):
        path = write_file(self.work, "huge.bin", self.cfg["hard_max"] + 1)
        with self.assertRaises(ValueError) as ctx:
            self.send([path])
        self.assertEqual(str(ctx.exception), "exceeds 25 MB limit")
        self.assertEqual(self.store.index_count("kapish"), 0)

    def test_exact_hard_max_is_fragmented_not_rejected(self):
        path = write_file(self.work, "edge.bin", self.cfg["hard_max"])
        self.assertEqual(self.send([path])[0]["tier"], "fragment")


class TestFragmentEdgeCases(TransferCase):
    FRAG_ID = "deadbeef" * 4

    def _inject(self, name, data, total, indices, corrupt=None, digest=None):
        chunks = tiering.split(data, self.cfg["chunk_size"])
        digest = digest or tiering.sha256_bytes(data)
        for index in indices:
            chunk = chunks[index - 1]
            if corrupt == index:
                chunk = bytes([(chunk[0] + 1) % 256]) + chunk[1:]
            tiering.send_fragment(HOST, self.smtp_port, "suyash@localmail",
                                  "kapish@localmail", "big subject", "body text",
                                  name, chunk, index, total, self.FRAG_ID, digest)

    def test_out_of_order_fragments_reassemble(self):
        data = os.urandom(4 * self.cfg["chunk_size"])
        self._inject("ooo.bin", data, 4, [3, 1, 4, 2])
        rows = self.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["fragments"], "4/4")
        with open(rows[0]["saved"][0], "rb") as fh:
            self.assertEqual(fh.read(), data)

    def test_missing_fragment_reports_incomplete_and_saves_nothing(self):
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject("part.bin", data, 3, [1, 2])
        rows = self.fetch()
        self.assertEqual(rows[0]["status"], "incomplete: waiting for 1 of 3 fragments")
        self.assertEqual(rows[0]["saved"], [])
        self.assertFalse(os.path.exists(os.path.join(self.downloads, "part.bin")))

    def test_two_missing_fragments_counted(self):
        data = os.urandom(4 * self.cfg["chunk_size"])
        self._inject("part.bin", data, 4, [2, 3])
        rows = self.fetch()
        self.assertEqual(rows[0]["status"], "incomplete: waiting for 2 of 4 fragments")

    def test_corrupted_fragment_fails_sha256_and_is_not_saved(self):
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject("bad.bin", data, 3, [1, 2, 3], corrupt=2)
        rows = self.fetch()
        self.assertEqual(rows[0]["status"], "incomplete: SHA-256 mismatch")
        self.assertEqual(rows[0]["saved"], [])
        self.assertFalse(os.path.exists(os.path.join(self.downloads, "bad.bin")))

    def test_subject_prefix_is_stripped_for_the_inbox_row(self):
        data = os.urandom(2 * self.cfg["chunk_size"])
        self._inject("s.bin", data, 2, [1, 2])
        self.assertEqual(self.fetch()[0]["subject"], "big subject")


class TestDeletePolicy(TransferCase):
    FRAG_ID = "cafebabe" * 4

    def _inject(self, data, total, indices):
        chunks = tiering.split(data, self.cfg["chunk_size"])
        digest = tiering.sha256_bytes(data)
        for index in indices:
            tiering.send_fragment(HOST, self.smtp_port, "suyash@localmail",
                                  "kapish@localmail", "held", "body", "held.bin",
                                  chunks[index - 1], index, total, self.FRAG_ID, digest)

    def test_delete_removes_a_complete_group(self):
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject(data, 3, [1, 2, 3])
        rows = self.fetch(delete=True)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(self.store.index_count("kapish"), 0)

    def test_delete_keeps_an_incomplete_group(self):
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject(data, 3, [1, 2])
        rows = self.fetch(delete=True)
        self.assertTrue(rows[0]["status"].startswith("incomplete: waiting for 1 of 3"))
        self.assertEqual(self.store.index_count("kapish"), 2)

    def test_held_group_completes_on_a_later_fetch(self):
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject(data, 3, [1, 2])
        self.assertNotEqual(self.fetch(delete=True)[0]["status"], "ok")
        self._inject(data, 3, [3])
        rows = self.fetch(delete=True)
        self.assertEqual(rows[0]["status"], "ok")
        with open(rows[0]["saved"][0], "rb") as fh:
            self.assertEqual(fh.read(), data)
        self.assertEqual(self.store.index_count("kapish"), 0)

    def test_delete_removes_inline_but_keeps_partial_fragments(self):
        inline_path = write_file(self.work, "small.bin", 500)
        self.send([inline_path])
        data = os.urandom(3 * self.cfg["chunk_size"])
        self._inject(data, 3, [1])
        self.assertEqual(self.store.index_count("kapish"), 2)
        self.fetch(delete=True)
        self.assertEqual(self.store.index_count("kapish"), 1)

    def test_fetch_without_delete_leaves_everything(self):
        path = write_file(self.work, "small.bin", 500)
        self.send([path])
        self.fetch(delete=False)
        self.assertEqual(self.store.index_count("kapish"), 1)


if __name__ == "__main__":
    unittest.main()
