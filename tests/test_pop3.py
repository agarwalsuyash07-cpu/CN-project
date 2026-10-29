import os
import time
import unittest

from .helpers import RawSession, ServerCase


def login(port, user="kapish", password="kapish123"):
    session = RawSession(port)
    session.line()
    session.cmd("USER %s" % user)
    session.cmd("PASS %s" % password)
    return session


class TestPOP3Auth(ServerCase):
    def test_greeting(self):
        session = RawSession(self.pop3_port)
        self.assertEqual(session.line(), "+OK POP3 ready")
        session.close()

    def test_pass_exact_string(self):
        session = RawSession(self.pop3_port)
        session.line()
        self.assertTrue(session.cmd("USER kapish").startswith("+OK"))
        self.assertEqual(session.cmd("PASS kapish123"), "+OK logged in")
        session.close()

    def test_bad_password_is_err(self):
        session = RawSession(self.pop3_port)
        session.line()
        session.cmd("USER kapish")
        reply = session.cmd("PASS wrong")
        self.assertTrue(reply.startswith("-ERR "), reply)
        session.close()

    def test_transaction_command_rejected_before_auth(self):
        session = RawSession(self.pop3_port)
        session.line()
        reply = session.cmd("STAT")
        self.assertTrue(reply.startswith("-ERR "), reply)
        session.close()

    def test_quit_from_authorization(self):
        session = RawSession(self.pop3_port)
        session.line()
        self.assertTrue(session.cmd("QUIT").startswith("+OK"))
        session.close()


class TestPOP3Transaction(ServerCase):
    def setUp(self):
        super().setUp()
        self.deliver("Subject: first\r\n\r\nalpha")
        # sent dot-stuffed, so the stored body holds a real leading-dot line
        self.deliver("Subject: second\r\n\r\n..dotted line\r\nbravo")
        self.sizes = [row[2] for row in self.store.list_messages("kapish")]

    def test_stat_format(self):
        session = login(self.pop3_port)
        self.assertEqual(session.cmd("STAT"), "+OK 2 %d" % sum(self.sizes))
        session.close()

    def test_list_multiline_ends_with_dot(self):
        session = login(self.pop3_port)
        self.assertTrue(session.cmd("LIST").startswith("+OK 2 messages"))
        body = session.until_dot()
        self.assertEqual(body, ["1 %d" % self.sizes[0], "2 %d" % self.sizes[1]])
        session.close()

    def test_list_single(self):
        session = login(self.pop3_port)
        self.assertEqual(session.cmd("LIST 1"), "+OK 1 %d" % self.sizes[0])
        self.assertTrue(session.cmd("LIST 9").startswith("-ERR "))
        session.close()

    def test_retr_is_dot_stuffed_and_dot_terminated(self):
        session = login(self.pop3_port)
        self.assertEqual(session.cmd("RETR 2"), "+OK %d octets" % self.sizes[1])
        lines = session.until_dot()
        # stored as ".dotted line", re-stuffed to "..dotted line" on the wire
        self.assertIn("..dotted line", lines)
        self.assertNotIn(".dotted line", lines)
        self.assertIn("bravo", lines)
        session.close()
        stored = self.store.read_message("kapish", self.store.list_messages("kapish")[1][1])
        self.assertIn(b"\r\n.dotted line\r\n", stored)

    def test_retr_bad_number(self):
        session = login(self.pop3_port)
        self.assertTrue(session.cmd("RETR 99").startswith("-ERR "))
        self.assertTrue(session.cmd("RETR abc").startswith("-ERR "))
        session.close()

    def test_uidl_and_noop(self):
        session = login(self.pop3_port)
        self.assertTrue(session.cmd("UIDL").startswith("+OK"))
        uids = session.until_dot()
        self.assertEqual(len(uids), 2)
        self.assertEqual(session.cmd("NOOP"), "+OK")
        session.close()

    def test_unknown_command(self):
        session = login(self.pop3_port)
        self.assertTrue(session.cmd("FROBNICATE").startswith("-ERR "))
        session.close()

    def test_retrieved_message_moves_to_cur(self):
        session = login(self.pop3_port)
        session.cmd("RETR 1")
        session.until_dot()
        session.cmd("QUIT")
        session.close()
        box = os.path.join(self.cfg["data_dir"], "mail", "kapish")
        self.assertEqual(len(os.listdir(os.path.join(box, "cur"))), 1)
        self.assertEqual(len(os.listdir(os.path.join(box, "new"))), 1)


class TestPOP3Deletes(ServerCase):
    def setUp(self):
        super().setUp()
        self.deliver("Subject: one\r\n\r\nalpha")
        self.deliver("Subject: two\r\n\r\nbravo")

    def _wait_unlocked(self, tries=40):
        for _ in range(tries):
            session = RawSession(self.pop3_port)
            session.line()
            session.cmd("USER kapish")
            if session.cmd("PASS kapish123") == "+OK logged in":
                return session
            session.close()
            time.sleep(0.05)
        self.fail("mailbox never unlocked")

    def test_dele_only_marks_until_quit(self):
        session = login(self.pop3_port)
        self.assertTrue(session.cmd("DELE 1").startswith("+OK"))
        self.assertEqual(session.cmd("STAT").split()[1], "1")
        # still on disk and in the index: nothing is committed before QUIT
        self.assertEqual(self.store.index_count("kapish"), 2)
        self.assertTrue(session.cmd("QUIT").startswith("+OK"))
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 1)

    def test_dropped_connection_after_dele_deletes_nothing(self):
        session = login(self.pop3_port)
        session.cmd("DELE 1")
        session.cmd("DELE 2")
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 2)
        again = self._wait_unlocked()
        self.assertEqual(again.cmd("STAT").split()[1], "2")
        again.cmd("QUIT")
        again.close()
        self.assertEqual(self.store.index_count("kapish"), 2)

    def test_rset_clears_marks(self):
        session = login(self.pop3_port)
        session.cmd("DELE 1")
        self.assertTrue(session.cmd("RSET").startswith("+OK"))
        self.assertEqual(session.cmd("STAT").split()[1], "2")
        session.cmd("QUIT")
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 2)

    def test_deleted_message_is_not_listed(self):
        session = login(self.pop3_port)
        session.cmd("DELE 1")
        self.assertTrue(session.cmd("RETR 1").startswith("-ERR "))
        self.assertTrue(session.cmd("LIST 1").startswith("-ERR "))
        session.cmd("QUIT")
        session.close()


class TestPasswordNotLogged(ServerCase):
    def test_log_masks_pass_and_never_contains_a_password(self):
        from localmail.client.reassembly import fetch_inbox
        self.deliver("Subject: one\r\n\r\nalpha")
        with self.assertLogs("localmail", level="INFO") as captured:
            session = login(self.pop3_port)
            session.cmd("QUIT")
            session.close()
            fetch_inbox(self.cfg, "kapish", "kapish123", pop3_port=self.pop3_port,
                        ref_port=self.ref_port, out_dir=self.downloads)
        text = "\n".join(captured.output)
        self.assertIn("[POP3] C: PASS ****", text)
        for password in self.cfg["users"].values():
            self.assertNotIn(password, text)


class TestPOP3Locking(ServerCase):
    def test_one_session_per_mailbox(self):
        first = login(self.pop3_port)
        second = RawSession(self.pop3_port)
        second.line()
        second.cmd("USER kapish")
        reply = second.cmd("PASS kapish123")
        self.assertTrue(reply.startswith("-ERR "), reply)
        second.close()
        first.cmd("QUIT")
        first.close()

    def test_other_mailbox_is_unaffected(self):
        first = login(self.pop3_port)
        other = login(self.pop3_port, "yashraj", "yashraj123")
        self.assertEqual(other.cmd("STAT").split()[0], "+OK")
        other.cmd("QUIT")
        other.close()
        first.cmd("QUIT")
        first.close()


if __name__ == "__main__":
    unittest.main()
