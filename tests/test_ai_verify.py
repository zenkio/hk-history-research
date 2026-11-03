import json

import ai_verify as av
import page_status as ps
import tidy_consolidated as td
from test_page_status import fake_execute, setup


def rec():
    return {"facts": [], "sections": [{"title": "S", "units": [
        {"text": "Lin arrived in Canton.", "zh": "林到達廣州。", "by": ["A"]},
        {"text": "Lin came to Canton.", "zh": "林來到廣州。", "by": ["B"]},
        {"text": "Elliot promised compensation.", "zh": "義律拒絕賠償。", "by": ["A"]}]}]}


def test_only_valid_lines_in_the_fixed_form_are_accepted():
    raw = ("F [1,2] | same_point | both say Lin reached Canton\nF [3] | unfaithful | promised vs refused\n"
           "F [9] | confusing | outside the section\nF [1] | same_point | needs two numbers\nF [2] | style | not a category\n"
           "chatter\nF [2,2] | same_point | same sentence")
    assert av.parse(raw, 3) == [([0, 1], "same_point", "both say Lin reached Canton"), ([2], "unfaithful", "promised vs refused")]


def test_findings_name_the_step_that_repairs_them_and_clean_sections_are_not_read_again():
    r, calls = rec(), []

    def call(system, prompt):
        calls.append(prompt)
        return "F [1,2] | same_point | repeat\nF [3] | unfaithful | opposite meaning"
    findings, stats = av.verify(r, call, "M")
    assert {(f["check"], f["step"]) for f in findings} == {("ai:same_point", "tidy"), ("ai:unfaithful", "translate")}
    assert "|| 林到達廣州。" in calls[0] and stats["flagged"] == 2
    av.verify(r, lambda s, p: "NONE", "M")  # a clean reading is remembered
    again, _ = av.verify(r, lambda s, p: 1 / 0, "M")
    assert again == []


def test_apply_drops_a_flagged_translation_and_hands_a_repeat_to_tidy_with_a_hint():
    r = rec()
    findings, _ = av.verify(r, lambda s, p: "F [1,2] | same_point | repeat\nF [3] | unfaithful | opposite", "M")
    av.apply(r, findings)
    units = r["sections"][0]["units"]
    assert "zh" not in units[2] and units[0].get("zh") and r["review_flags"] == {"S": [[0, 1]]}
    prompts = []

    def call(system, prompt):
        prompts.append(prompt)
        return "[C1,C2] Lin arrived in Canton.\n[C3] Elliot promised compensation."
    out, rep = td.run(r, call, only_problems=True)
    assert len(out["sections"][0]["units"]) == 2 and rep["redone"] == 1 and "tell the same point in different words" in prompts[0]
    assert "review_flags" not in out


def test_the_status_runner_lets_the_ai_proofreader_start_a_repair_round(tmp_path, monkeypatch):
    root, log = setup(tmp_path), []
    monkeypatch.setattr(ps, "execute", fake_execute(log))
    answers = iter(["F [1] | unfaithful | wrong meaning", "NONE"])
    seen = []

    def call(system, prompt):
        seen.append(prompt)
        return next(answers)
    ps.run_page("p", call, "M", root=root)
    st = json.loads((root / ps.STATUS / "p.json").read_text())
    assert log.count("translate") == 2 and log.count("tidy") == 1 and st["gate"]["findings"] == []
    assert len(seen) == 2  # the second reading found nothing, so the page is done
