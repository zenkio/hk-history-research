import review_consolidated as rv
import render_consolidated_facts as rc


def record():
    texts = ["Britain imported Chinese tea.", "China imported British tea.", "Opium paid for tea."]
    return {"facts": [], "sections": [{"title": "Background", "units": [{"text": t, "by": ["A"], "facts": []} for t in texts]}]}


def test_conflict_is_flagged_checked_and_shown_disputed():
    rec, rep = rv.run(record(), lambda s, p: "[2] conflicts with [1]: direction of the tea trade is reversed", "M")
    units = rec["sections"][0]["units"]
    assert rep["conflicts"] == 1 and "conflict" not in units[0] and units[1]["conflict"]["judged_by"] == "M"
    html = rc.paragraph_from_units("**1. x** ", units, {})
    assert "Disputed: an AI reviewer" in html and "fact-disputed" in html


def test_none_means_nothing_flagged_and_bad_numbers_are_retried_then_not_applied():
    assert rv.run(record(), lambda s, p: "NONE")[1]["conflicts"] == 0
    answers = []
    rec, rep = rv.run(record(), lambda s, p: answers.append(p) or "[9] conflicts with [1]: x")
    assert not rep["reviewed"] and len(answers) == rv.cp.MAX_TRIES and "bad numbers" in answers[1]
    assert all("conflict" not in u for u in rec["sections"][0]["units"])
