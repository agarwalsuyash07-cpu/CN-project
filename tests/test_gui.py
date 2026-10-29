import unittest

from localmail.client.gui import short_date


class TestInboxDateColumn(unittest.TestCase):
    def test_rfc2822_date_is_shortened_to_fit_the_column(self):
        self.assertEqual(short_date("Wed, 30 Sep 2026 17:29:29 +0530"), "30 Sep 2026 17:29")

    def test_unparseable_date_is_shown_as_is(self):
        self.assertEqual(short_date("not a date"), "not a date")
        self.assertEqual(short_date(""), "")


if __name__ == "__main__":
    unittest.main()
