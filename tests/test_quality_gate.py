import json

import page_status as ps
import quality_gate as qg
from test_page_status import fake_execute, setup


def rec(units, title="Peking", title_zh="北京", qs=()):
    return {"title": title, "title_zh": title_zh, "questions": list(qs),
            "sections": [{"title": "S", "title_zh": "段", "units": units}]}


def unit(text, zh="中文。"):
    return {"text": text, "zh": zh, "by": ["A"]}


def checks(r):
    return {f["check"] for f in qg.check(r)}


def test_a_clean_record_has_no_findings():
    assert qg.check(rec([unit("Lin arrived in Canton."), unit("France signed a convention.")])) == []


def test_each_defect_the_owner_found_by_reading_has_a_detector():
    a = "Prince Gong established the Zongli Yamen in 1861, beginning the Tongzhi Restoration."
    assert "repeat" in checks(rec([unit(a), unit("Prince Gong set up the Zongli Yamen in 1861.")]))
    assert "fragment" in checks(rec([unit("The Qing Dynasty under the Xianfeng Emperor (r.")]))
    assert "cantonese" in checks(rec([unit("He was premier.", "佢係首相。")]))
    assert "english_in_zh" in checks(rec([unit("Signed in July 1997.", "於1 July 1997簽署。")]))
    assert "missing_zh" in checks(rec([{"text": "No Chinese yet.", "by": ["A"]}]))
    assert "title_zh" in checks(rec([unit("Fine.")], title_zh=None))
    assert "leaked" in checks(rec([unit("Another AI says the treaty was signed.")]))
    assert "too_long" in checks(rec([unit(" ".join(["word"] * 70) + ".")]))
    q = {"id": "kid-1", "lang": "zh", "term": "九龍", "section": "S", "sentence": "Fine.", "question": "九龍究係誰的？"}
    assert "stale_question" in checks(rec([unit("Fine.")], qs=[q]))
    gone = dict(q, question="九龍是誰的？", sentence="A sentence that no longer exists.")
    assert "stale_question" in checks(rec([unit("Fine.")], qs=[gone]))


def test_the_gate_starts_a_repair_round_for_the_step_that_can_fix_it_and_stops_after_two(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    base = fake_execute(log)
    state = {"bad": 1}

    def execute(step, page_md, record, call, model, repair=False):
        record, report = base(step, page_md, record, call, model)
        if step == "translate" and state["bad"]:
            record["sections"][0]["units"][0]["zh"] = "佢係首相。"  # a Cantonese translation the first time only
            state["bad"] = 0
        return record, report
    monkeypatch.setattr(ps, "execute", execute)
    ps.run_page("p", None, "M", root=root)
    st = json.loads((root / ps.STATUS / "p.json").read_text())
    assert log.count("translate") == 2 and log.count("tidy") == 1 and st["gate"]["findings"] == []  # only translate redone


def test_a_defect_the_repair_cannot_fix_stays_in_the_status_after_the_rounds(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    base = fake_execute(log)

    def execute(step, page_md, record, call, model, repair=False):
        record, report = base(step, page_md, record, call, model)
        if step == "translate":
            record["sections"][0]["units"][0]["zh"] = "佢係首相。"
        return record, report
    monkeypatch.setattr(ps, "execute", execute)
    ps.run_page("p", None, "M", root=root)
    st = json.loads((root / ps.STATUS / "p.json").read_text())
    assert log.count("translate") == 1 + ps.GATE_ROUNDS and st["gate"]["counts"] == {"cantonese": 1}
