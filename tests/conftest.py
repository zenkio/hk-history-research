"""Shared test setup. Tests never touch the network, real quota or the real content/ tree.

- `no_network` (autouse): any real HTTP call fails the test, so a missing fake is caught
  instead of quietly calling Wikipedia, OpenAlex or an AI API.
- `state_dir`: scripts/state/*.json go to a temp folder.
- `timeline`: a temp content/01_Timeline for the modules that read or write event pages.
- `make_pool`: a ModelPool with no Google client, for testing routing and error handling.
"""
import os
import sys
import threading
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("a test tried to use the network; fake it instead")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.fixture(autouse=True)
def time_limit():
    """Fail a test that runs over 10 s: with sleeps faked, a retry loop that never ends
    (the pre-PR #17 OpenRouter 429 handling) would otherwise hang the whole suite."""
    import signal

    def timeout(*_):
        raise TimeoutError("test ran over 10 s: probably an endless retry loop")
    old = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(10)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    import state
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setattr(state, "STATE_DIR", str(d))
    return d


@pytest.fixture
def timeline(tmp_path, monkeypatch):
    """An empty timeline folder; every module that knows TIMELINE_DIR is pointed at it."""
    d = tmp_path / "01_Timeline"
    d.mkdir()
    import research_import, evidence, seed_history
    for mod in (research_import, evidence, seed_history):
        monkeypatch.setattr(mod, "TIMELINE_DIR", str(d))
    return d


def event_page(title, year=1900, grade=None, claims=("A claim about the event",), extra=""):
    fm = [f'title: "{title}"', f"date: {year}", f"year: {year}", "confidence: ai-draft"]
    if grade:
        fm.append(f"evidence_grade: {grade}")
    fm.append('tags: ["ai-draft"]')
    body = "Body text.\n\n## Claims to verify\n\n" + "".join(f"- ❔ {c}\n" for c in claims)
    return "---\n" + "\n".join(fm) + "\n---\n" + body + extra + "\nPart of: [[era]]\n"


@pytest.fixture
def write_page(timeline):
    def write(rel, *args, **kw):
        path = timeline / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(event_page(*args, **kw), encoding="utf-8")
        return path
    return write


@pytest.fixture
def make_pool():
    import gemini_pool as gp

    def make(models, routing, or_keys=()):
        p = object.__new__(gp.ModelPool)
        p.lock = threading.RLock()
        p.unavailable, p.no_media, p.cooldown, p.token_log = set(), set(), {}, {}
        p.models = {name: {"rpd": 1000, "rpm": 30, "tpm": 10 ** 6, "display": name, "api_id": name, **m}
                    for name, m in models.items()}
        p.routing = routing
        p.config = {"providers": {"openrouter": {"rpd": 50, "reset_timezone": "UTC"}}}
        p.or_keys = list(or_keys)
        p.or_key_name, p.or_key = p.or_keys[0] if p.or_keys else (None, "")
        p.remaining = lambda k, r: 5
        p._pace = lambda *a, **k: None
        p._count = lambda k: None
        p._provider = lambda k: p.models[k].get("provider", "google")
        return p
    return make
