import os
import threading
import unittest

from .helpers import ServerCase

THREADS = 20


class TestConcurrentDelivery(ServerCase):
    def test_twenty_threads_into_one_mailbox(self):
        errors = []

        def worker(n):
            try:
                body = "Subject: msg-%02d\r\n\r\npayload-%02d %s" % (n, n, "x" * 500)
                reply = self.deliver(body)
                if reply != "250 Message accepted":
                    errors.append("thread %d got %r" % (n, reply))
            except Exception as exc:
                errors.append("thread %d raised %r" % (n, exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)

        self.assertEqual(errors, [])
        self.assertEqual(self.store.index_count("kapish"), THREADS)

        rows = self.store.list_messages("kapish")
        self.assertEqual(len(rows), THREADS)
        subjects = set()
        for _msg_id, filename, size in rows:
            raw = self.store.read_message("kapish", filename)
            self.assertEqual(len(raw), size)
            self.assertIn(b"payload-", raw)
            self.assertEqual(raw.count(b"Subject: "), 1)
            subjects.add(raw.split(b"Subject: ", 1)[1].split(b"\r\n", 1)[0])
        self.assertEqual(len(subjects), THREADS)

        box = os.path.join(self.cfg["data_dir"], "mail", "kapish")
        self.assertEqual(os.listdir(os.path.join(box, "tmp")), [])
        self.assertEqual(len(os.listdir(os.path.join(box, "new"))), THREADS)

    def test_concurrent_delivery_to_different_mailboxes(self):
        errors = []

        def worker(n):
            try:
                rcpt = ("kapish", "yashraj", "suyash")[n % 3] + "@localmail"
                self.deliver("Subject: m-%02d\r\n\r\nbody" % n, rcpt=rcpt)
            except Exception as exc:
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(self.store.index_count("kapish"), 4)
        self.assertEqual(self.store.index_count("yashraj"), 4)
        self.assertEqual(self.store.index_count("suyash"), 4)


if __name__ == "__main__":
    unittest.main()
