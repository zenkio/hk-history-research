import json

import page_status as ps


def setup(tmp_path):
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    (tmp_path / "content/05_Multi_AI/p.md").write_text("drafts v1")
    return tmp_path


def fake_execute(log, partial=()):
    def execute(step, page_md, record, call, model, repair=False):
        log.append(step)
        if step == "fold":
            record["sections"] = [{"title": "S", "units": [{"text": f"Sentence of {page_md}.", "by": ["A"]}]}]
            return record, {"folds": [], "whole_text_problems": []}
        if step == "tidy":
            return record, {"sections": [{"section": "S", "fallback": step in partial}]}
        if step == "translate":
            if step not in partial:
                for s in record["sections"]:
                    for u in s["units"]:
                        u["zh"] = "中"
            return record, {}
        if step == "review":
            return record, {"reviewed": True}
        return record, {"unread": 0}
    return execute


def test_each_step_runs_once_and_a_second_run_does_nothing(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert ps.run_page("p", None, "M", root=root) == ps.STEPS
    assert ps.run_page("p", None, "M", root=root) == [] and log == ps.STEPS
    assert ps.show("p", root)["next"] is None


def test_a_new_draft_makes_every_later_step_stale_but_not_an_unchanged_page(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    ps.run_page("p", None, "M", root=root)
    (root / "content/05_Multi_AI/p.md").write_text("drafts v2")
    assert ps.show("p", root)["next"] == "fold"
    assert ps.run_page("p", None, "M", root=root) == ps.STEPS


def test_a_step_that_left_gaps_is_repeated_then_accepted_and_the_page_moves_on(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log, partial=("translate",)))
    ran = ps.run_page("p", None, "M", root=root)
    assert ran.count("translate") == ps.MAX_ATTEMPTS and ran[-2:] == ["review", "kidread"]
    st = json.loads((root / ps.STATUS / "p.json").read_text())
    assert st["translate"]["state"] == "accepted" and st["translate"]["gaps"] == ["S"]
    assert ps.run_page("p", None, "M", root=root) == []


def test_max_steps_limits_one_call_and_the_next_call_continues(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert ps.run_page("p", None, "M", max_steps=2, root=root) == ["fold", "tidy"]
    assert ps.run_page("p", None, "M", root=root) == ["translate", "review", "kidread"]


def test_steps_done_before_status_files_can_be_adopted_so_they_are_not_run_again(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    (root / "data/consolidated_facts").mkdir(parents=True)
    (root / "data/consolidated_facts/p.json").write_text(json.dumps(
        {"facts": [], "sections": [{"title": "S", "units": [{"text": "x", "by": ["A"], "zh": "中"}]}]}))
    ps.adopt("p", ["fold", "tidy", "translate"], root)
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert ps.run_page("p", None, "M", root=root) == ["review", "kidread"]


def test_an_overloaded_model_pauses_the_page_without_using_up_an_attempt(tmp_path, monkeypatch):
    # run 41375955401: translate crashed on "all models overloaded" and the run lost the step
    root, log = setup(tmp_path), []
    good = fake_execute(log)

    def execute(step, *a, **kw):
        if step == "translate" and "down" not in log:
            log.append("down")
            raise ps.cp.WriterUnavailable("503 overloaded")
        return good(step, *a)

    monkeypatch.setattr(ps, "execute", execute)
    assert ps.run_page("p", None, "M", root=root) == ["fold", "tidy"]
    st = json.loads((root / ps.STATUS / "p.json").read_text())
    assert st["translate"]["state"] == "waiting" and st["translate"]["attempts"] == 0
    assert ps.run_page("p", None, "M", root=root) == ["translate", "review", "kidread"]


def test_retry_forgets_an_accepted_step_so_only_that_step_runs_again(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log, partial=("translate",)))
    ps.run_page("p", None, "M", root=root)
    log.clear()
    ps.retry("p", ["translate"], root)
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    assert ps.run_page("p", None, "M", root=root) == ["translate"]


def test_a_forgotten_step_runs_as_a_repair_but_a_first_run_does_not(tmp_path, monkeypatch):
    root, seen = setup(tmp_path), []
    base = fake_execute([])

    def execute(step, page_md, record, call, model, repair=False):
        seen.append((step, repair))
        return base(step, page_md, record, call, model)
    monkeypatch.setattr(ps, "execute", execute)
    ps.run_page("p", None, "M", root=root)
    assert all(not r for _, r in seen)
    seen.clear()
    ps.retry("p", ["tidy"], root)
    ps.run_page("p", None, "M", root=root)
    assert seen[0] == ("tidy", True)
