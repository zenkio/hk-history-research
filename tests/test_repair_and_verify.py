"""Repair step and the Wikipedia cross-check page writer."""
import time

import repair_content as rc
import seed_history as sh
import wikipedia
from conftest import event_page


def test_tick_boxes_become_plain_markers_once(tmp_path):
    # PR #12: Quartz drew "- [ ]" as boxes readers could tick.
    p = tmp_path / "p.md"
    p.write_text(event_page("P").replace("- ❔ ", "- [ ] "), encoding="utf-8")
    pages = lambda: [(str(p), *rc.split_page(p.read_text()))]
    assert rc.plain_claim_markers(pages()) == 1
    assert rc.plain_claim_markers(pages()) == 0
    assert "- ❔ A claim" in p.read_text() and "- [ ]" not in p.read_text()


class VerifyPool:
    def total_remaining(self, role):
        return 5

    def generate_json(self, role, prompt, **k):
        return {"on_topic": True, "verdicts": [
            {"claim": "Founded in 1844.", "status": "supported", "note": "Wikipedia says 1844."},
            {"claim": "The exact date?", "status": "unclear", "note": "Not covered."}]}, "gemma", []


def test_verify_writes_cross_check_and_keeps_grade(write_page, monkeypatch, timeline):
    path = write_page("p.md", "Establishment of the Hong Kong Police Force", 1844, grade="none",
                      claims=["Founded in 1844.", "The exact date?"])
    monkeypatch.setattr(sh, "save_plan", lambda plan: None)
    monkeypatch.setattr(wikipedia, "reference_text", lambda *a: ("text", [{"title": "Wikipedia: HKPF", "uri": "u"}], ["HKPF"]))
    monkeypatch.setattr(wikipedia, "cited_sources", lambda *a: [])
    plan = {"events": [{"file": "p.md", "title": "Establishment of the Hong Kong Police Force", "year": 1844,
                        "status": "done", "era": "06-early-colony"}]}
    assert sh.verify_pages(VerifyPool(), plan, time.time() + 60) == 1
    text = path.read_text()
    assert "## Wikipedia cross-check" in text and "## Claims to verify" not in text
    assert "Founded in 1844. Wikipedia" in text and ".." not in text
    assert "evidence_grade: none" in text, "Wikipedia must never change the evidence grade"
    assert '"wikipedia-checked"' in text


def test_off_topic_reference_writes_nothing(write_page, monkeypatch):
    path = write_page("p.md", "Hong Kong Club", 1846)
    monkeypatch.setattr(sh, "save_plan", lambda plan: None)
    monkeypatch.setattr(wikipedia, "reference_text", lambda *a: ("text", [], ["SSV Ulm 1846"]))

    class OffTopic(VerifyPool):
        def generate_json(self, role, prompt, **k):
            return {"on_topic": False, "verdicts": []}, "gemma", []
    ev = {"file": "p.md", "title": "Hong Kong Club", "year": 1846, "status": "done", "era": "06-early-colony"}
    assert sh.verify_pages(OffTopic(), {"events": [ev]}, time.time() + 60) == 0
    assert "## Claims to verify" in path.read_text() and ev["verified"] == "no-reference"


def test_cross_check_keeps_the_sections_after_the_claims(write_page, timeline):
    # hk-history-data PR #25: replacing up to "Part of:" deleted 98 Evidence, 26 Research notes and
    # 58 photo sections. Only the claims section may be replaced.
    later = ("\n## Evidence\n\n> [!abstract] Evidence grade: **B**\n\n- [Paper](https://doi.org/10.1/x) (supports claim 1): y\n"
             "\n## Research notes\n\nnotes\n\n## Photos from this period\n\nphotos\n")
    p = write_page("p.md", "Founding of the Police", 1844, grade="B", extra=later)
    sh.apply_verification(str(p), [{"claim": "Founded in 1844", "status": "supported", "note": "ok"}], [], "m")
    text = p.read_text(encoding="utf-8")
    assert "## Wikipedia cross-check" in text and "## Claims to verify" not in text
    for kept in ("## Evidence", "Evidence grade: **B**", "## Research notes", "## Photos from this period", "Part of: "):
        assert kept in text, kept
