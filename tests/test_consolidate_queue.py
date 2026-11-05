import json

import consolidate_queue as cq
import page_status as ps
from test_page_status import fake_execute


def setup(tmp_path, pages=("a", "b", "c"), queue=None):
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    for p in pages:
        (tmp_path / f"content/05_Multi_AI/{p}.md").write_text(f"drafts {p}")
    if queue is not None:
        ps.save(tmp_path / cq.QUEUE, queue)
    return tmp_path


def test_empty_queue_means_every_page_and_finished_pages_are_skipped(tmp_path, monkeypatch):
    root, log = setup(tmp_path, queue={}), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    done, _ = cq.run_queue(None, "M", root)
    assert [p for p, _ in done] == ["a", "b", "c"] and len(log) == 15
    assert cq.run_queue(None, "M", root)[0] == []  # nothing left to do, nothing runs


def test_only_listed_pages_run_and_unknown_names_are_ignored(tmp_path, monkeypatch):
    root, log = setup(tmp_path, queue={"pages": ["b", "ghost"]}), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert [p for p, _ in cq.run_queue(None, "M", root)[0]] == ["b"]


def test_a_crash_in_one_page_does_not_stop_the_others_and_is_quarantined(tmp_path, monkeypatch):
    root, log = setup(tmp_path, queue={}), []
    ok = fake_execute(log)

    def execute(step, page_md, record, call, model, repair=False):
        if page_md == "drafts a":
            raise ValueError("boom")
        return ok(step, page_md, record, call, model)
    monkeypatch.setattr(ps, "execute", execute)
    for _ in range(cq.CRASH_LIMIT + 1):
        done, issues = cq.run_queue(None, "M", root)
    assert issues["a|run|crash"]["count"] == cq.CRASH_LIMIT  # not tried a fourth time
    assert (root / ps.STATUS / "b.json").exists() and "boom" in issues["a|run|crash"]["detail"]
    cq_args = ["--clear", "a"]
    import os
    cwd = os.getcwd()
    os.chdir(root)
    try:
        cq.main(cq_args)
    finally:
        os.chdir(cwd)
    assert "a|run|crash" not in json.loads((root / cq.ISSUES).read_text())


def test_overloaded_gateway_stops_the_run_after_two_waiting_pages(tmp_path, monkeypatch):
    root = setup(tmp_path, pages=("a", "b", "c", "d"), queue={})

    def execute(step, page_md, record, call, model, repair=False):
        raise cq.cp.WriterUnavailable("busy")
    monkeypatch.setattr(ps, "execute", execute)
    done, issues = cq.run_queue(None, "M", root)
    assert [p for p, _ in done] == ["a", "b"]
    assert issues["*|run|gateway"]["open"] and cq.summary(issues)["waiting"] == 2


def test_waiting_page_is_tried_again_and_its_issue_closes(tmp_path, monkeypatch):
    root, log = setup(tmp_path, pages=("a",), queue={}), []
    monkeypatch.setattr(ps, "execute", lambda *a, **kw: (_ for _ in ()).throw(cq.cp.WriterUnavailable("busy")))
    assert cq.summary(cq.run_queue(None, "M", root)[1])["waiting"] == 1
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert cq.summary(cq.run_queue(None, "M", root)[1])["waiting"] == 0


def test_gaps_are_healed_once_then_left_as_an_issue(tmp_path, monkeypatch):
    root, log = setup(tmp_path, pages=("a",), queue={}), []
    monkeypatch.setattr(ps, "execute", fake_execute(log, partial=("translate",)))
    _, issues = cq.run_queue(None, "M", root)
    assert issues["a|translate|gaps"]["open"] and log.count("translate") == ps.MAX_ATTEMPTS
    cq.run_queue(None, "M", root)  # heal: the step is forgotten and tried again (2 attempts)
    assert log.count("translate") == 2 * ps.MAX_ATTEMPTS
    cq.run_queue(None, "M", root)  # no second heal
    assert log.count("translate") == 2 * ps.MAX_ATTEMPTS


def test_time_budget_stops_before_the_next_page(tmp_path, monkeypatch):
    root, log = setup(tmp_path, queue={}), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    ticks = iter([0, 0, 99999, 99999, 99999, 99999])
    done, _ = cq.run_queue(None, "M", root, minutes=1, clock=lambda: next(ticks))
    assert [p for p, _ in done] == ["a"]


def test_defects_the_gate_could_not_repair_become_quality_issues_and_close_when_gone(tmp_path, monkeypatch):
    root, log = setup(tmp_path, pages=("a",), queue={}), []
    base = fake_execute(log)
    bad = {"on": True}

    def execute(step, page_md, record, call, model, repair=False):
        record, report = base(step, page_md, record, call, model)
        if step == "translate" and bad["on"]:
            record["sections"][0]["units"][0]["zh"] = "佢係首相。"
        return record, report
    monkeypatch.setattr(ps, "execute", execute)
    _, issues = cq.run_queue(None, "M", root)
    assert issues["a|cantonese|quality"]["open"] and cq.summary(issues)["quality"] == 1
    bad["on"] = False
    ps.retry("a", ["translate"], root)
    _, issues = cq.run_queue(None, "M", root)
    assert not issues["a|cantonese|quality"]["open"]
