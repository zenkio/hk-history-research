import json

import pytest

import consolidate_queue as cq
import page_status as ps
import run_control as rc
import usage_report as ur
from test_page_status import setup, fake_execute


def ctl(tmp_path, **settings):
    (tmp_path / "data").mkdir(exist_ok=True)
    if settings:
        (tmp_path / rc.CONTROL).write_text(json.dumps(settings))
    return rc.Control(tmp_path, signals=False)


def test_calls_are_counted_per_page_and_step_with_estimated_tokens(tmp_path):
    c = ctl(tmp_path)
    call = c.wrap(lambda s, p: "x" * 40, "p", "tidy")
    call("a" * 8, "b" * 8)
    u = json.loads((tmp_path / rc.USAGE).read_text())
    assert u["pages"]["p"]["tidy"] == {"calls": 1, "failed": 0, "in": 4, "out": 10}
    assert u["days"][rc.today()]["calls"] == 1


def test_a_failed_call_is_counted_as_used_quota(tmp_path):
    c = ctl(tmp_path)

    def boom(s, p):
        raise OSError("503")
    with pytest.raises(OSError):
        c.wrap(boom, "p", "tidy")("s", "p")
    assert json.loads((tmp_path / rc.USAGE).read_text())["pages"]["p"]["tidy"]["failed"] == 1


def test_paused_pipeline_starts_no_call_and_resumes_when_unpaused(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    (root / "data").mkdir(exist_ok=True)
    (root / rc.CONTROL).write_text(json.dumps({"paused": True, "reason": "gateway needed elsewhere"}))
    c = rc.Control(root, signals=False)
    assert ps.run_page("p", lambda s, p: "x", "M", root=root, ctl=c) == []
    (root / "data").mkdir(exist_ok=True)
    (root / rc.CONTROL).write_text(json.dumps({"paused": False}))
    assert ps.run_page("p", lambda s, p: "x", "M", root=root, ctl=c)[0] == "fold"


def test_daily_budget_stops_the_run_in_the_middle_of_a_step_and_the_step_stays_open(tmp_path, monkeypatch):
    root = setup(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    (root / rc.CONTROL).write_text(json.dumps({"daily_calls": 2}))
    c = rc.Control(root, signals=False)

    def execute(step, page_md, record, call, model, repair=False):
        for _ in range(5):
            call("s", "p")
        return record, {}
    monkeypatch.setattr(ps, "execute", execute)
    assert ps.run_page("p", lambda s, p: "ok", "M", root=root, ctl=c) == []
    assert c.calls_today() == 2
    st = json.loads((root / ps.STATUS / "p.json").read_text()) if (root / ps.STATUS / "p.json").exists() else {}
    assert not st.get("fold", {}).get("state") in ("done", "accepted", "partial")


def test_a_signal_stops_before_the_next_call(tmp_path):
    c = ctl(tmp_path)
    c.signalled = "SIGTERM"
    with pytest.raises(rc.Stopped):
        c.wrap(lambda s, p: "x", "p", "tidy")("s", "p")


def test_queue_stops_when_paused_and_saves_nothing_lost(tmp_path, monkeypatch):
    root = setup(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    (root / rc.CONTROL).write_text(json.dumps({"paused": True}))
    c = rc.Control(root, signals=False)
    done, _ = cq.run_queue(lambda s, p: "x", "M", root, ctl=c)
    assert done == []


def test_report_gives_the_average_cost_of_a_complete_page_and_pages_per_day():
    usage = {"pages": {"a": {"fold": {"calls": 20, "failed": 2, "in": 40000, "out": 10000},
                              "kidread": {"calls": 10, "failed": 0, "in": 10000, "out": 2000}},
                       "b": {"fold": {"calls": 5, "failed": 0, "in": 1000, "out": 500}}}}
    r = ur.report(usage, price_in=1, price_out=2, daily_calls=300)
    assert r["pages_complete"] == 1 and r["average_per_page"]["calls"] == 30
    assert r["pages_per_day_at_budget"] == 10.0 and r["days_for_120_pages_at_budget"] == 12.0
    assert r["paid_cost_per_page_usd"] == round((50000 * 1 + 12000 * 2) / 1e6, 4)


def test_many_threads_counting_calls_at_once_do_not_crash_or_lose_counts(tmp_path):
    # run 41929679016: the review step calls the writer from a thread pool; the unlocked ledger write failed with
    # FileNotFoundError and stopped the page
    from concurrent.futures import ThreadPoolExecutor
    c = ctl(tmp_path)
    call = c.wrap(lambda s, p: "ok", "p", "review")
    with ThreadPoolExecutor(12) as pool:
        list(pool.map(lambda _: call("s", "p"), range(200)))
    assert json.loads((tmp_path / rc.USAGE).read_text())["pages"]["p"]["review"]["calls"] == 200
    assert c.calls_today() == 200


def test_a_ledger_that_cannot_be_written_does_not_stop_the_call(tmp_path, monkeypatch):
    c = ctl(tmp_path)

    def broken(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(rc, "_save", broken)
    assert c.wrap(lambda s, p: "ok", "p", "tidy")("s", "p") == "ok"


def test_the_model_the_gateway_reports_is_counted_and_a_different_one_is_a_mismatch(tmp_path):
    import consolidate_pipeline as cp
    c = rc.Control(tmp_path, signals=False, expected="nvidia/nemotron-3-ultra-550b-a55b:free")

    def call(model):
        def f(s, p):
            cp.SERVED.model = model
            return "ok"
        return f
    c.wrap(call("nvidia/nemotron-3-ultra-550b-a55b:free"), "p", "tidy")("s", "p")
    c.wrap(call("nvidia/nemotron-3-ultra-550b-a55b"), "p", "tidy")("s", "p")  # same model, no ':free' tag
    assert c.mismatches() == 0
    c.wrap(call("google/gemma-4-26b:free"), "p", "tidy")("s", "p")
    u = json.loads((tmp_path / rc.USAGE).read_text())["pages"]["p"]["tidy"]
    assert c.mismatches() == 1 and u["models"]["google/gemma-4-26b:free"] == 1 and u["calls"] == 3
