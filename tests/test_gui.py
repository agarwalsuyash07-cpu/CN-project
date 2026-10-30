import os
import tempfile
import types
import unittest
from unittest import mock

from localmail.client import gui
from localmail.client.gui import LocalMailApp, short_date


class TestInboxDateColumn(unittest.TestCase):
    def test_rfc2822_date_is_shortened_to_fit_the_column(self):
        self.assertEqual(short_date("Wed, 30 Sep 2026 17:29:29 +0530"), "30 Sep 2026 17:29")

    def test_unparseable_date_is_shown_as_is(self):
        self.assertEqual(short_date("not a date"), "not a date")
        self.assertEqual(short_date(""), "")


def fake_app(saved, selected=(0,)):
    # stands in for LocalMailApp so Open/Save run without a Tk window
    app = types.SimpleNamespace(statuses=[])
    app.current_row = lambda: {"saved": saved, "status": "incomplete: waiting for 1 of 8 fragments"}
    app.att_list = types.SimpleNamespace(curselection=lambda: selected)
    app.status = app.statuses.append
    app._selected_path = lambda: LocalMailApp._selected_path(app)
    return app


class TestOpenAndSave(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.src = os.path.join(self.dir, "संदेश_é.txt")
        with open(self.src, "wb") as fh:
            fh.write(b"attachment bytes")

    def test_open_passes_the_saved_file_to_the_os(self):
        app = fake_app([self.src])
        with mock.patch.object(gui, "open_with_os") as opener:
            LocalMailApp.do_open(app)
        opener.assert_called_once_with(self.src)
        self.assertEqual(app.statuses, ["opened %s" % self.src])

    def test_save_copies_the_file_to_the_chosen_path(self):
        target = os.path.join(self.dir, "copy.txt")
        app = fake_app([self.src])
        with mock.patch.object(gui.filedialog, "asksaveasfilename", return_value=target) as ask:
            LocalMailApp.do_save(app)
        self.assertEqual(ask.call_args.kwargs["initialfile"], "संदेश_é.txt")
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"attachment bytes")
        self.assertEqual(app.statuses, ["saved to %s" % target])

    def test_cancelled_save_dialog_writes_nothing(self):
        app = fake_app([self.src])
        with mock.patch.object(gui.filedialog, "asksaveasfilename", return_value=""):
            LocalMailApp.do_save(app)
        self.assertEqual(os.listdir(self.dir), ["संदेश_é.txt"])
        self.assertEqual(app.statuses, [])

    def test_nothing_to_open_when_the_message_saved_no_file(self):
        app = fake_app([])
        with mock.patch.object(gui, "open_with_os") as opener, \
                mock.patch.object(gui.messagebox, "showinfo") as info:
            LocalMailApp.do_open(app)
        opener.assert_not_called()
        self.assertIn("waiting for 1 of 8 fragments", info.call_args.args[1])

    def test_open_without_an_attachment_selected_asks_for_one(self):
        app = fake_app([self.src], selected=())
        with mock.patch.object(gui, "open_with_os") as opener:
            LocalMailApp.do_open(app)
        opener.assert_not_called()
        self.assertEqual(app.statuses, ["select an attachment first"])


class TestOpenWithOS(unittest.TestCase):
    def test_windows_uses_startfile(self):
        with mock.patch.object(gui.os, "name", "nt"), \
                mock.patch.object(gui.os, "startfile", create=True) as start:
            gui.open_with_os("f.txt")
        start.assert_called_once_with("f.txt")

    def test_macos_uses_open_and_linux_uses_xdg_open(self):
        for platform, command in (("darwin", "open"), ("linux", "xdg-open")):
            with mock.patch.object(gui.os, "name", "posix"), \
                    mock.patch.object(gui.sys, "platform", platform), \
                    mock.patch.object(gui.subprocess, "Popen") as popen:
                gui.open_with_os("f.txt")
            popen.assert_called_once_with([command, "f.txt"])


if __name__ == "__main__":
    unittest.main()
