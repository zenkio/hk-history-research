"""Small shared helpers for work that runs in parallel threads (seed_history.py).

Each worker keeps its progress in its own JSON file under scripts/state/, so no two
threads ever write the same file, and every write is atomic (temp file + rename), so a
git commit taken mid-run never captures half a file. PAGE_LOCK serialises
read-modify-write edits of content pages, since the evidence, photo and fact-check
workers can touch the same event page.
"""
import os
import json
import threading

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
PAGE_LOCK = threading.RLock()
_locks = {}
_locks_guard = threading.Lock()


def _lock(name):
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def path(name):
    return os.path.join(STATE_DIR, f"{name}.json")


def load(name, default=None):
    with _lock(name):
        try:
            with open(path(name), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {} if default is None else default


def save(name, data):
    with _lock(name):
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path(name))


def atomic_write(file_path, text):
    tmp = file_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, file_path)
