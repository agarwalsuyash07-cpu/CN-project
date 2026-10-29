import poplib
import smtplib
import unittest
from email.mime.text import MIMEText

from .helpers import HOST, ServerCase


class TestReferenceClients(ServerCase):
    # stdlib smtplib/poplib are used here only, to prove the servers are RFC-compliant
    def test_smtplib_delivers(self):
        msg = MIMEText("sent by the stdlib reference client")
        msg["Subject"] = "smtplib probe"
        msg["From"] = "suyash@localmail"
        msg["To"] = "kapish@localmail"
        with smtplib.SMTP(HOST, self.smtp_port, timeout=20) as client:
            code, _reply = client.ehlo("reference-client")
            self.assertEqual(code, 250)
            self.assertIn("size", client.esmtp_features)
            refused = client.sendmail("suyash@localmail", ["kapish@localmail"],
                                      msg.as_string())
            self.assertEqual(refused, {})
        self.assertEqual(self.store.index_count("kapish"), 1)
        rows = self.store.list_messages("kapish")
        raw = self.store.read_message("kapish", rows[0][1])
        self.assertIn(b"sent by the stdlib reference client", raw)

    def test_smtplib_helo_path(self):
        with smtplib.SMTP(HOST, self.smtp_port, timeout=20) as client:
            code, _reply = client.helo("reference-client")
            self.assertEqual(code, 250)

    def test_smtplib_unknown_recipient_is_refused(self):
        with smtplib.SMTP(HOST, self.smtp_port, timeout=20) as client:
            client.ehlo("reference-client")
            with self.assertRaises(smtplib.SMTPRecipientsRefused) as ctx:
                client.sendmail("suyash@localmail", ["nobody@localmail"],
                                "Subject: x\r\n\r\nbody")
            self.assertEqual(ctx.exception.recipients["nobody@localmail"][0], 550)

    def test_smtplib_multiple_recipients(self):
        with smtplib.SMTP(HOST, self.smtp_port, timeout=20) as client:
            client.ehlo("reference-client")
            client.sendmail("suyash@localmail",
                            ["kapish@localmail", "yashraj@localmail"],
                            "Subject: broadcast\r\n\r\nbody")
        self.assertEqual(self.store.index_count("kapish"), 1)
        self.assertEqual(self.store.index_count("yashraj"), 1)

    def test_poplib_retrieves_and_deletes(self):
        self.deliver("Subject: for poplib\r\n\r\nhello poplib")
        client = poplib.POP3(HOST, self.pop3_port, timeout=20)
        self.assertTrue(client.getwelcome().startswith(b"+OK POP3 ready"))
        client.user("kapish")
        client.pass_("kapish123")
        count, octets = client.stat()
        self.assertEqual(count, 1)
        self.assertGreater(octets, 0)
        self.assertEqual(len(client.list()[1]), 1)
        self.assertEqual(len(client.uidl()[1]), 1)
        _resp, lines, _octets = client.retr(1)
        self.assertIn(b"hello poplib", b"\r\n".join(lines))
        client.dele(1)
        client.quit()
        self.assertEqual(self.store.index_count("kapish"), 0)

    def test_poplib_undoes_our_dot_stuffing(self):
        self.deliver("Subject: dots\r\n\r\n..stuffed line\r\ntail")
        client = poplib.POP3(HOST, self.pop3_port, timeout=20)
        client.user("kapish")
        client.pass_("kapish123")
        _resp, lines, _octets = client.retr(1)
        client.quit()
        self.assertIn(b".stuffed line", lines)
        self.assertNotIn(b"..stuffed line", lines)

    def test_poplib_bad_password(self):
        client = poplib.POP3(HOST, self.pop3_port, timeout=20)
        client.user("kapish")
        with self.assertRaises(poplib.error_proto):
            client.pass_("wrong")
        client.close()


if __name__ == "__main__":
    unittest.main()
