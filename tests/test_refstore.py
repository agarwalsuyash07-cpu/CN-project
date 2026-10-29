import os
import unittest

from localmail.client.reassembly import http_get
from localmail.client.tiering import upload_to_store
from localmail.server.ref_store import ref_dir

from .helpers import HOST, ServerCase


class TestRefStore(ServerCase):
    def test_put_get_round_trip(self):
        data = os.urandom(5000)
        ref_id = upload_to_store(HOST, self.ref_port, "file.bin", data)
        self.assertEqual(len(ref_id), 32)
        self.assertTrue(os.path.exists(os.path.join(ref_dir(self.cfg), ref_id)))
        self.assertEqual(http_get(HOST, self.ref_port, ref_id), data)

    def test_each_put_gets_its_own_id(self):
        first = upload_to_store(HOST, self.ref_port, "a.bin", b"aaa")
        second = upload_to_store(HOST, self.ref_port, "a.bin", b"bbb")
        self.assertNotEqual(first, second)
        self.assertEqual(http_get(HOST, self.ref_port, first), b"aaa")
        self.assertEqual(http_get(HOST, self.ref_port, second), b"bbb")

    def test_missing_id_is_404(self):
        with self.assertRaises(RuntimeError) as ctx:
            http_get(HOST, self.ref_port, "0" * 32)
        self.assertIn("404", str(ctx.exception))

    def test_malformed_id_is_404(self):
        for bad in ("", "abc", "../index.db", "Z" * 32):
            with self.subTest(ref_id=bad):
                with self.assertRaises(RuntimeError):
                    http_get(HOST, self.ref_port, bad)

    def test_non_ascii_filename_header_is_accepted(self):
        ref_id = upload_to_store(HOST, self.ref_port, "रिपोर्ट_é.txt", b"payload")
        self.assertEqual(http_get(HOST, self.ref_port, ref_id), b"payload")

    def test_large_body(self):
        data = os.urandom(3 * 1024 * 1024)
        ref_id = upload_to_store(HOST, self.ref_port, "big.bin", data)
        self.assertEqual(http_get(HOST, self.ref_port, ref_id), data)


if __name__ == "__main__":
    unittest.main()
