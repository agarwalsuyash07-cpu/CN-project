import io
import unittest
from unittest import mock

from localmail.common.lineio import setup_logging


class TestConsoleEncoding(unittest.TestCase):
    def test_non_ascii_prints_when_output_is_redirected_on_windows(self):
        # a redirected stdout on Windows is a cp1252 TextIOWrapper, which cannot hold Devanagari
        out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
        err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err), \
                mock.patch("logging.basicConfig"):
            setup_logging()
            print("saved: रिपोर्ट_é.txt", file=out)
        out.flush()
        self.assertEqual(out.buffer.getvalue().decode("utf-8"), "saved: रिपोर्ट_é.txt\n")
        self.assertEqual(err.encoding, "utf-8")

    def test_missing_streams_are_left_alone(self):
        # pythonw (GUI without a console) has sys.stdout = None
        with mock.patch("sys.stdout", None), mock.patch("sys.stderr", None), \
                mock.patch("logging.basicConfig"):
            setup_logging()


if __name__ == "__main__":
    unittest.main()
