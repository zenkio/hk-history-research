import json

import page_status as ps


def setup(tmp_path):
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    (tmp_path / "content/05_Multi_AI/p.md").write_text("drafts v1")
    return tmp_path


def fake_execute(log, partial=()):
    def execute(step, page_md, record, call, model):
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
