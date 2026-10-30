import os
import subprocess
import sys

from .helpers import HOST, ServerCase

NC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "nc.py")


class TestNetcatScript(ServerCase):
    # scripts/nc.py stands in for `nc -c` on Windows in the Evidence 2 POP3 session
    def run_nc(self, port, typed):
        return subprocess.run([sys.executable, NC, HOST, str(port)], input=typed.encode(),
                              capture_output=True, timeout=30).stdout

    def test_pop3_session_typed_through_nc(self):
        self.deliver("Subject: via nc\r\n\r\nhello")
        out = self.run_nc(self.pop3_port, "USER kapish\nPASS %s\nSTAT\nRETR 1\nQUIT\n"
                          % self.cfg["users"]["kapish"])
        self.assertTrue(out.startswith(b"+OK POP3 ready\r\n"))
        self.assertIn(b"+OK logged in\r\n+OK 1 ", out)
        self.assertIn(b"Subject: via nc\r\n\r\nhello\r\n.\r\n", out)
        self.assertTrue(out.endswith(b"+OK Bye\r\n"))

    def test_input_ending_without_quit_still_returns(self):
        out = self.run_nc(self.smtp_port, "EHLO nc\n")
        self.assertIn(b"250 OK\r\n", out)
