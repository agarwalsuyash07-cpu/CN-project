import argparse
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from email.utils import parsedate_to_datetime
from tkinter import filedialog, messagebox, ttk

from ..common.lineio import setup_logging
from ..config import CONFIG, human
from . import tiering
from .reassembly import fetch_inbox


def short_date(value):
    # inbox column only; the message view keeps the full RFC 2822 Date header
    try:
        return parsedate_to_datetime(value).strftime("%d %b %Y %H:%M")
    except (TypeError, ValueError):
        return value


def open_with_os(path):
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class LocalMailApp:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.rows = []
        self.user = ""
        self.password = ""
        self.host = cfg["host"]
        self._pending = []
        self._lock = threading.Lock()
        root.title("LocalMail")
        root.geometry("980x640")
        self.body = tk.Frame(root)
        self.body.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="ready")
        tk.Label(root, textvariable=self.status_var, anchor="w", relief="sunken",
                 padx=6).pack(fill="x", side="bottom")
        self.build_login()
        root.after(150, self._drain)

    def status(self, text):
        self.status_var.set(text)

    def run_async(self, work, done):
        def runner():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            with self._lock:
                self._pending.append((done, result, error))
        threading.Thread(target=runner, daemon=True).start()

    def _drain(self):
        with self._lock:
            items, self._pending = self._pending, []
        for done, result, error in items:
            if error is not None:
                self.status("error: %s" % error)
                messagebox.showerror("LocalMail", str(error))
            else:
                done(result)
        self.root.after(150, self._drain)

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def build_login(self):
        self._clear()
        frame = tk.Frame(self.body, padx=40, pady=60)
        frame.pack(expand=True)
        tk.Label(frame, text="LocalMail", font=("TkDefaultFont", 20)).grid(
            row=0, column=0, columnspan=2, pady=(0, 20))
        self.host_var = tk.StringVar(value=self.cfg["host"])
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        for row, (label, var, hide) in enumerate(
                [("Server host", self.host_var, False),
                 ("Username", self.user_var, False),
                 ("Password", self.pass_var, True)], start=1):
            tk.Label(frame, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
            tk.Entry(frame, textvariable=var, width=28,
                     show="*" if hide else "").grid(row=row, column=1, padx=6, pady=4)
        tk.Button(frame, text="Login", width=14, command=self.do_login).grid(
            row=4, column=0, columnspan=2, pady=16)
        frame.bind_all("<Return>", lambda _event: self.do_login())

    def do_login(self):
        self.host = self.host_var.get().strip() or self.cfg["host"]
        self.user = self.user_var.get().strip()
        self.password = self.pass_var.get()
        if not self.user or not self.password:
            messagebox.showwarning("LocalMail", "username and password are required")
            return
        self.status("connecting to %s ..." % self.host)
        self.run_async(self._fetch, self._logged_in)

    def _fetch(self, delete=False):
        return fetch_inbox(self.cfg, self.user, self.password, host=self.host,
                           delete=delete)

    def _logged_in(self, rows):
        self.root.unbind_all("<Return>")
        self.build_main()
        self._show_rows(rows)

    def build_main(self):
        self._clear()
        bar = tk.Frame(self.body, pady=6, padx=6)
        bar.pack(fill="x")
        tk.Label(bar, text="%s@%s" % (self.user, self.cfg["domain"]),
                 font=("TkDefaultFont", 12, "bold")).pack(side="left")
        tk.Button(bar, text="Refresh", command=self.do_refresh).pack(side="right", padx=4)
        tk.Button(bar, text="Compose", command=self.do_compose).pack(side="right", padx=4)
        self.delete_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="delete complete transfers on fetch",
                       variable=self.delete_var).pack(side="right", padx=10)

        columns = ("from", "subject", "date", "tier", "frag", "att", "status")
        widths = (170, 300, 150, 80, 55, 45, 170)
        self.tree = ttk.Treeview(self.body, columns=columns, show="headings", height=11)
        for name, width in zip(columns, widths):
            self.tree.heading(name, text=name.upper())
            self.tree.column(name, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=6)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        lower = tk.Frame(self.body, padx=6, pady=6)
        lower.pack(fill="both", expand=True)
        left = tk.Frame(lower)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Message", anchor="w").pack(fill="x")
        self.message_text = tk.Text(left, height=8, wrap="word")
        self.message_text.pack(fill="both", expand=True)

        right = tk.Frame(lower, padx=8)
        right.pack(side="right", fill="y")
        tk.Label(right, text="Attachments", anchor="w").pack(fill="x")
        self.att_list = tk.Listbox(right, width=38, height=6)
        self.att_list.pack(fill="both", expand=True)
        buttons = tk.Frame(right, pady=6)
        buttons.pack(fill="x")
        tk.Button(buttons, text="Open", width=10, command=self.do_open).pack(side="left")
        tk.Button(buttons, text="Save", width=10, command=self.do_save).pack(side="left", padx=6)

    def _show_rows(self, rows):
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), values=(
                row["from"], row["subject"], short_date(row["date"]), row["tier"],
                row["fragments"] or "-", len(row["attachments"]), row["status"]))
        tiers = ", ".join(sorted({r["tier"] for r in rows})) or "none"
        held = sum(1 for r in rows if r["status"] != "ok")
        self.status("%d message(s); tiers: %s%s" % (
            len(rows), tiers, "; %d incomplete held on server" % held if held else ""))

    def do_refresh(self):
        self.status("fetching over POP3 ...")
        delete = self.delete_var.get()
        self.run_async(lambda: self._fetch(delete), self._show_rows)

    def current_row(self):
        selection = self.tree.selection()
        return self.rows[int(selection[0])] if selection else None

    def on_select(self, _event=None):
        row = self.current_row()
        if row is None:
            return
        self.message_text.delete("1.0", "end")
        self.message_text.insert("end", "From: %s\nSubject: %s\nDate: %s\nTier: %s %s\n"
                                        "Status: %s\n\n%s"
                                 % (row["from"], row["subject"], row["date"], row["tier"],
                                    row["fragments"], row["status"], row.get("body", "")))
        self.att_list.delete(0, "end")
        for name in row["attachments"]:
            self.att_list.insert("end", name)
        self.status("%s: %s %s" % (row["tier"], row["status"], row["fragments"]))

    def _selected_path(self):
        row = self.current_row()
        if row is None:
            self.status("select a message first")
            return None
        index = self.att_list.curselection()
        if not index:
            self.status("select an attachment first")
            return None
        if not row["saved"]:
            messagebox.showinfo("LocalMail",
                                "nothing was saved for this message (%s)" % row["status"])
            return None
        return row["saved"][min(index[0], len(row["saved"]) - 1)]

    def do_open(self):
        path = self._selected_path()
        if path:
            open_with_os(path)
            self.status("opened %s" % path)

    def do_save(self):
        path = self._selected_path()
        if not path:
            return
        target = filedialog.asksaveasfilename(initialfile=os.path.basename(path))
        if target:
            shutil.copyfile(path, target)
            self.status("saved to %s" % target)

    def do_compose(self):
        ComposeWindow(self)


class ComposeWindow:
    def __init__(self, app):
        self.app = app
        self.paths = []
        self.window = tk.Toplevel(app.root)
        self.window.title("Compose")
        self.window.geometry("620x520")
        frame = tk.Frame(self.window, padx=10, pady=10)
        frame.pack(fill="both", expand=True)

        self.to_var = tk.StringVar()
        self.subject_var = tk.StringVar()
        for row, (label, var) in enumerate([("To", self.to_var),
                                            ("Subject", self.subject_var)]):
            tk.Label(frame, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=4)
            tk.Entry(frame, textvariable=var, width=56).grid(row=row, column=1, pady=4)

        tk.Label(frame, text="Body").grid(row=2, column=0, sticky="ne", padx=4, pady=4)
        self.body_text = tk.Text(frame, width=56, height=9, wrap="word")
        self.body_text.grid(row=2, column=1, pady=4)

        tk.Button(frame, text="Attach files...", command=self.pick_files).grid(
            row=3, column=1, sticky="w", pady=6)
        tk.Label(frame, text="Tier preview").grid(row=4, column=0, sticky="ne", padx=4)
        self.preview = tk.Listbox(frame, width=56, height=6)
        self.preview.grid(row=4, column=1, pady=4)
        tk.Button(frame, text="Send", width=14, command=self.do_send).grid(
            row=5, column=1, sticky="e", pady=10)

    def pick_files(self):
        chosen = filedialog.askopenfilenames()
        if not chosen:
            return
        self.paths = list(chosen)
        self.preview.delete(0, "end")
        for path in self.paths:
            name, size, tier = tiering.preview(path, self.app.cfg)
            note = tier
            if tier == "reject":
                note = "REJECTED (over %s)" % human(self.app.cfg["hard_max"])
            elif tier == "fragment":
                chunks = -(-size // self.app.cfg["chunk_size"])
                note = "fragment (%d x %s)" % (chunks, human(self.app.cfg["chunk_size"]))
            self.preview.insert("end", "%s   %s   -> %s" % (name, human(size), note))

    def do_send(self):
        recipient = self.to_var.get().strip()
        if not recipient:
            messagebox.showwarning("Compose", "a recipient is required")
            return
        subject = self.subject_var.get()
        body = self.body_text.get("1.0", "end").rstrip("\n")
        paths = list(self.paths)
        app = self.app
        app.status("sending ...")

        def work():
            return tiering.send(app.cfg, app.user, recipient, subject, body, paths,
                                host=app.host)

        def done(results):
            tiers = ", ".join("%s: %s" % (r["file"], r["tier"]) for r in results) \
                or "no attachments"
            app.status("sent to %s (%s)" % (recipient, tiers))
            self.window.destroy()

        app.run_async(work, done)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m localmail.client.gui")
    parser.add_argument("--host", help="server address (default: config host)")
    parser.add_argument("--user", help="with --password, log in on launch")
    parser.add_argument("--password")
    args = parser.parse_args(argv)
    setup_logging()
    root = tk.Tk()
    app = LocalMailApp(root, CONFIG)
    if args.host:
        app.host_var.set(args.host)
    if args.user and args.password:
        app.user_var.set(args.user)
        app.pass_var.set(args.password)
        root.after(0, app.do_login)
    root.mainloop()


if __name__ == "__main__":
    main()
