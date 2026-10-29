import json
import os

MB = 1024 * 1024
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    "host": "127.0.0.1",
    "smtp_port": 2525,
    "pop3_port": 1110,
    "ref_port": 8000,
    "domain": "localmail",
    "data_dir": "data",
    "users": {"suyash": "suyash123", "kapish": "kapish123", "yashraj": "yashraj123"},
    "inline_max": 1 * MB,
    "reference_max": 10 * MB,
    "hard_max": 25 * MB,
    "chunk_size": 2 * MB,
}


def load(path=CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


CONFIG = load()


def data_dir(cfg=None):
    cfg = cfg or CONFIG
    path = cfg["data_dir"]
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def human(size):
    return "%.1f MB" % (size / float(MB)) if size >= MB else "%.1f KB" % (size / 1024.0)
