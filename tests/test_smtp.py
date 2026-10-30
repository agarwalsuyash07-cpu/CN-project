import os
import unittest

from .helpers import RawSession, ServerCase


class TestSMTPSession(ServerCase):
    def test_greeting(self):
        session = RawSession(self.smtp_port)
        self.assertEqual(session.line(), "220 localmail SMTP ready")
        session.close()

    def test_ehlo_is_multiline_and_ends_250_ok(self):
        session = RawSession(self.smtp_port)
        session.line()
        first = session.cmd("EHLO client.local")
        rest = session.lines(2)
        self.assertEqual(first, "250-localmail Hello client.local")
        self.assertEqual(rest[0], "250-SIZE %d" % self.cfg["hard_max"])
        self.assertEqual(rest[1], "250 OK")
        session.close()

    def test_helo_single_line(self):
        session = RawSession(self.smtp_port)
        session.line()
        self.assertEqual(session.cmd("HELO client.local"), "250 OK")
        session.close()

    def test_full_exchange_exact_strings(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO client.local")
        session.lines(2)
        self.assertEqual(session.cmd("MAIL FROM:<suyash@localmail>"), "250 OK")
        self.assertEqual(session.cmd("RCPT TO:<kapish@localmail>"), "250 OK")
        self.assertEqual(session.cmd("DATA"), "354 End data with <CRLF>.<CRLF>")
        session.send_raw(b"Subject: hi\r\n\r\nbody\r\n.\r\n")
        self.assertEqual(session.line(), "250 Message accepted")
        self.assertEqual(session.cmd("QUIT"), "221 Bye")
        session.close()

    def test_bad_sequence_503(self):
        session = RawSession(self.smtp_port)
        session.line()
        self.assertEqual(session.cmd("RCPT TO:<kapish@localmail>"), "503 Bad sequence of commands")
        self.assertEqual(session.cmd("MAIL FROM:<suyash@localmail>"),
                         "503 Bad sequence of commands")
        session.cmd("EHLO x")
        session.lines(2)
        self.assertEqual(session.cmd("DATA"), "503 Bad sequence of commands")
        session.close()

    def test_unknown_user_550(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        session.lines(2)
        session.cmd("MAIL FROM:<suyash@localmail>")
        self.assertEqual(session.cmd("RCPT TO:<nobody@localmail>"), "550 No such user")
        self.assertEqual(session.cmd("RCPT TO:<suyash@elsewhere>"), "550 No such user")
        session.close()

    def test_unknown_command_500_and_syntax_501(self):
        session = RawSession(self.smtp_port)
        session.line()
        self.assertEqual(session.cmd("FROBNICATE now"), "500 Command not recognized")
        session.cmd("EHLO x")
        session.lines(2)
        self.assertEqual(session.cmd("MAIL FROM:<>"), "501 Syntax error")
        session.close()

    def test_rset_and_noop(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        session.lines(2)
        session.cmd("MAIL FROM:<suyash@localmail>")
        session.cmd("RCPT TO:<kapish@localmail>")
        self.assertEqual(session.cmd("RSET"), "250 OK")
        self.assertEqual(session.cmd("NOOP"), "250 OK")
        self.assertEqual(session.cmd("DATA"), "503 Bad sequence of commands")
        session.close()

    def test_rcpts_reset_after_data(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        session.lines(2)
        session.cmd("MAIL FROM:<suyash@localmail>")
        session.cmd("RCPT TO:<kapish@localmail>")
        session.cmd("DATA")
        session.send_raw(b"Subject: one\r\n\r\nbody\r\n.\r\n")
        session.line()
        self.assertEqual(session.cmd("DATA"), "503 Bad sequence of commands")
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 1)

    def test_dot_stuffing_round_trip(self):
        body = "Subject: dots\r\n\r\nnormal line\r\n..dotted line\r\n...three\r\nend"
        self.assertEqual(self.deliver(body), "250 Message accepted")
        rows = self.store.list_messages("kapish")
        stored = self.store.read_message("kapish", rows[0][1]).decode("utf-8")
        self.assertIn("\r\n.dotted line\r\n", stored)
        self.assertIn("\r\n..three\r\n", stored)
        self.assertNotIn("\r\n..dotted line\r\n", stored)


class TestSMTPOversize(ServerCase):
    overrides = {"hard_max": 4096}

    def test_oversize_552(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        session.lines(2)
        session.cmd("MAIL FROM:<suyash@localmail>")
        session.cmd("RCPT TO:<kapish@localmail>")
        session.cmd("DATA")
        session.send_raw(b"Subject: big\r\n\r\n" + b"x" * 8192 + b"\r\n.\r\n")
        self.assertEqual(session.line(), "552 Message size exceeds limit")
        # the stream is still usable: the body was drained, not misparsed as commands
        self.assertEqual(session.cmd("QUIT"), "221 Bye")
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 0)

    def test_ehlo_advertises_the_limit(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        self.assertEqual(session.lines(2)[0], "250-SIZE 4096")
        session.close()


class TestStorage(ServerCase):
    def test_maildir_layout_and_index_row(self):
        self.deliver("From: suyash@localmail\r\nSubject: indexed\r\n\r\nhello")
        box = os.path.join(self.cfg["data_dir"], "mail", "kapish")
        for sub in ("tmp", "new", "cur"):
            self.assertTrue(os.path.isdir(os.path.join(box, sub)), sub)
        self.assertEqual(len(os.listdir(os.path.join(box, "new"))), 1)
        self.assertEqual(os.listdir(os.path.join(box, "tmp")), [])

        rows = self.store.list_messages("kapish")
        self.assertEqual(len(rows), 1)
        row = self.store._query("SELECT user, sender, subject, size, deleted FROM messages"
                                " WHERE filename=?", (rows[0][1],))[0]
        self.assertEqual(row[0], "kapish")
        self.assertEqual(row[1], "suyash@localmail")
        self.assertEqual(row[2], "indexed")
        self.assertGreater(row[3], 0)
        self.assertEqual(row[4], 0)

    def test_received_header_is_prepended(self):
        self.deliver("Subject: hdr\r\n\r\nbody")
        rows = self.store.list_messages("kapish")
        stored = self.store.read_message("kapish", rows[0][1]).decode("utf-8")
        self.assertTrue(stored.startswith("Received: from 127.0.0.1 by localmail"))

    def test_one_store_call_per_recipient(self):
        session = RawSession(self.smtp_port)
        session.line()
        session.cmd("EHLO x")
        session.lines(2)
        session.cmd("MAIL FROM:<suyash@localmail>")
        session.cmd("RCPT TO:<kapish@localmail>")
        session.cmd("RCPT TO:<yashraj@localmail>")
        session.cmd("DATA")
        session.send_raw(b"Subject: both\r\n\r\nbody\r\n.\r\n")
        self.assertEqual(session.line(), "250 Message accepted")
        session.cmd("QUIT")
        session.close()
        self.assertEqual(self.store.index_count("kapish"), 1)
        self.assertEqual(self.store.index_count("yashraj"), 1)


class TestPortConflict(ServerCase):
    # on Windows SO_REUSEADDR lets a second listener steal a busy port without an error
    def test_second_server_on_a_busy_port_fails_to_start(self):
        from localmail.server.pop3_server import POP3Server
        from localmail.server.ref_store import RefStoreServer
        from localmail.server.smtp_server import SMTPServer
        busy = dict(self.cfg, smtp_port=self.smtp_port, pop3_port=self.pop3_port,
                    ref_port=self.ref_port)
        for server in (SMTPServer(busy, self.store), POP3Server(busy, self.store),
                       RefStoreServer(busy)):
            self.addCleanup(server.stop)   # also closes the socket a failed bind leaves open
            with self.subTest(server=type(server).__name__):
                with self.assertRaises(OSError):
                    server.start()


if __name__ == "__main__":
    unittest.main()
