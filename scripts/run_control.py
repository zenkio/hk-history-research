"""Pause, stop, resume and AI-usage accounting for the consolidation pipeline (owner 2026-11-04).

The project runs on free AI resources at the lowest priority, so it must be able to stop at any moment and go on later
without losing work, and it must know what a page costs.
 - `data/consolidated_control.json`: {"paused": true/false, "reason": "...", "daily_calls": 300}. Paused, or the day's
   call budget spent, means: no new AI call is started. The step that was running is left open (its status file says
   so) and the next run resumes it; finished steps are never redone.
 - SIGTERM / SIGINT (a cancelled workflow, a closed terminal) stop the same way, before the next AI call.
 - `data/consolidated_usage.json`: calls, failed calls and estimated tokens per day and per page and step, so the cost
   of a page is known (`usage_report.py`). Tokens are estimated from characters (about 4 per token): the gateway does
   not report them for every model.
"""
import json
import signal
from datetime import datetime, timezone
from pathlib import Path

CONTROL = "data/consolidated_control.json"
USAGE = "data/consolidated_usage.json"
DEFAULT_DAILY_CALLS = 300  # a share of the gateway's ~1,000 a day: this project is low priority


class Stopped(Exception):
    """Raised before an AI call that must not start (paused, budget spent, signal)."""


def tokens(text):
    return (len(text or "") + 3) // 4


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Control:
    def __init__(self, root=Path("."), signals=True):
        self.root = Path(root)
        self.signalled = None
        self.usage = _load(self.root / USAGE, {"days": {}, "pages": {}})
        if signals:
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    signal.signal(sig, self._on_signal)
                except ValueError:  # not the main thread
                    pass

    def _on_signal(self, signum, frame):
        self.signalled = signal.Signals(signum).name

    def settings(self):
        return _load(self.root / CONTROL, {})

    def calls_today(self):
        return self.usage["days"].get(today(), {}).get("calls", 0)

    def reason_to_stop(self):
        """Why no new AI call may start now, or None."""
        if self.signalled:
            return f"stopped by {self.signalled}"
        s = self.settings()
        if s.get("paused"):
            return "paused" + (f": {s['reason']}" if s.get("reason") else "")
        budget = s.get("daily_calls", DEFAULT_DAILY_CALLS)
        if budget is not None and self.calls_today() >= budget:
            return f"daily budget of {budget} calls spent"
        return None

    def record(self, page, step, calls=0, failed=0, tin=0, tout=0):
        for bucket in (self.usage["days"].setdefault(today(), {}),
                       self.usage["pages"].setdefault(page, {}).setdefault(step, {})):
            for k, v in (("calls", calls), ("failed", failed), ("in", tin), ("out", tout)):
                bucket[k] = bucket.get(k, 0) + v
        _save(self.root / USAGE, self.usage)

    def wrap(self, call, page, step):
        """The writer call, counted, and refused once the pipeline must stop."""
        if call is None:
            return None

        def counted(system, prompt):
            reason = self.reason_to_stop()
            if reason:
                raise Stopped(reason)
            try:
                text = call(system, prompt)
            except Exception:
                self.record(page, step, calls=1, failed=1, tin=tokens(system) + tokens(prompt))
                raise
            self.record(page, step, calls=1, tin=tokens(system) + tokens(prompt), tout=tokens(text))
            return text
        return counted
