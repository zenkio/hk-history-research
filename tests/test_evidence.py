"""Evidence engine with fake archive/scholarship sources and a fake AI judge."""
import time

import pytest
import evidence as ev
import state

A_RECORD = {"kind": "archive record", "grade": "A", "year": 1900, "title": "CO 129 Treaty file",
            "url": "https://discovery.nationalarchives.gov.uk/details/r/1", "cite": "CO 129/1", "note": "n"}


class Judge:
    """Keeps the first candidate, like a model that finds it relevant."""
    def __init__(self):
        self.calls = 0

    def generate_json(self, role, prompt, **k):
        self.calls += 1
        return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "about this"}]}, "gemma", []


def fail(q):
    raise Exception("HTTP Error 429: Too Many Requests")


@pytest.fixture(autouse=True)
def fresh_sources(monkeypatch):
    monkeypatch.setattr(ev, "_source_fails", {})
    monkeypatch.setattr(ev, "AUDIT_SHARE", 0)  # the audit test turns it on


def batch(pages, sources, monkeypatch, done=None):
    monkeypatch.setattr(ev, "SOURCES", sources)
    done = {} if done is None else done
    events = [{"file": f, "status": "done"} for f in pages]
    ev.evidence_batch(Judge(), done, events, time.time() + 60, limit=50)
    return done


def test_page_with_no_results_while_a_source_is_down_is_not_recorded(write_page, monkeypatch):
    # PR #18: OpenAlex 429s left 96 of 150 pages marked "none" for good.
    write_page("p.md", "Plague outbreak")
    done = batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [])], monkeypatch)
    assert done == {}


def test_evidence_found_elsewhere_is_kept_while_a_source_is_down(write_page, monkeypatch, timeline):
    write_page("p.md", "Treaty signing")
    done = batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [A_RECORD])], monkeypatch)
    assert done == {"p.md": "A"}
    assert "evidence_grade: A" in (timeline / "p.md").read_text()


def test_all_sources_answering_with_nothing_is_recorded_none(write_page, monkeypatch):
    write_page("p.md", "Plague outbreak")
    assert batch(["p.md"], [("OpenAlex", lambda q: []), ("National Archives", lambda q: [])], monkeypatch) == {"p.md": "none"}


def test_failing_source_is_rested_after_three_failures(write_page, monkeypatch):
    calls = []

    def counting_fail(q):
        calls.append(q)
        fail(q)
    for i in range(5):
        write_page(f"p{i}.md", f"Harbour event {'abcde'[i]}")
    batch([f"p{i}.md" for i in range(5)], [("OpenAlex", counting_fail), ("National Archives", lambda q: [])], monkeypatch)
    assert len(calls) == ev.SOURCE_FAILS_TO_REST


def test_old_none_results_are_searched_again_once():
    done = {"a.md": "none", "b.md": "B", "c.md": "A"}
    assert ev.reopen_unsearched(done) == 1
    assert done == {"b.md": "B", "c.md": "A"}
    done["a.md"] = "none"
    assert ev.reopen_unsearched(done) == 0  # only once per SEARCH_VERSION
    assert state.load("evidence_meta")["search_version"] == ev.SEARCH_VERSION


def test_openalex_sends_the_api_key_when_set(monkeypatch):
    # Since Feb 2026 OpenAlex gives 100 credits a day without a key (10 searches): run 27's 429s.
    seen = []
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: seen.append(url) or {"results": []})
    monkeypatch.setenv("OPENALEX_API_KEY", " key123\n")
    ev.openalex("Tung Wah")
    monkeypatch.delenv("OPENALEX_API_KEY")
    ev.openalex("Tung Wah")
    assert "api_key=key123" in seen[0] and "api_key" not in seen[1]


def test_descriptive_words_are_dropped_from_the_search():
    # Run 31 (after PR #19): "Disastrous Shek Kip Mei Fire" found no evidence for the 1953 fire.
    assert ev.keywords("The Disastrous Shek Kip Mei Fire") == "Shek Kip Mei Fire"
    assert ev.keywords("Establishment of the Hong Kong Housing Authority") == "Housing Authority"
    assert ev.keywords("Japanese Invasion of Hong Kong Begins") == "Japanese Invasion"


def test_log_shows_what_each_source_returned_and_what_the_ai_kept(write_page, monkeypatch, capsys):
    # Run 31 graded 42 of 50 pages "none" and the log could not say whether search or AI found nothing.
    write_page("p.md", "Treaty signing")
    batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [dict(A_RECORD)]),
                     ("Internet Archive", lambda q: [])], monkeypatch)
    out = capsys.readouterr().out
    assert '"Treaty": OpenAlex failed, National Archives 1, Internet Archive 0; AI kept 1' in out


def test_log_line_for_a_search_that_found_nothing(write_page, monkeypatch, capsys):
    write_page("p.md", "Plague outbreak")
    batch(["p.md"], [("OpenAlex", lambda q: []), ("National Archives", lambda q: [])], monkeypatch)
    assert '"Plague": OpenAlex 0, National Archives 0; nothing to judge' in capsys.readouterr().out


# --- stricter judging (2026-09-28 audit: general-topic works were graded as evidence) ---------

B_PAPER = {"kind": "scholarship", "grade": "B", "year": 2009, "title": "Chinese ancestor worship in general",
           "url": "https://doi.org/10.1/x", "cite": "Lakos (2009)", "note": "n"}


class SaysJudge:
    """Answers with the given `relevant` list; a second, different model can answer differently."""
    def __init__(self, relevant, second=None, second_model="nemotron-super"):
        self.relevant, self.second, self.second_model, self.calls = relevant, second, second_model, []
        self.routing = {"evidence": ["nemotron-ultra", "nemotron-super", "gemma"]}

    def generate_json(self, role, prompt, only=None, **k):
        self.calls.append(only)
        if only is not None:
            return {"relevant": self.second or []}, self.second_model, []
        return {"relevant": self.relevant, "missing": ""}, "nemotron-ultra", []


def judge_page(write_page, monkeypatch, timeline, relevant, sources, **kw):
    write_page("p.md", "Consecration of St John's Cathedral", 1849)
    monkeypatch.setattr(ev, "SOURCES", sources)
    pool = SaysJudge(relevant, **kw)
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    return done, (timeline / "p.md").read_text(encoding="utf-8"), pool


def test_background_reading_is_listed_but_earns_no_grade(write_page, monkeypatch, timeline):
    done, text, pool = judge_page(write_page, monkeypatch, timeline,
                                  [{"id": "c1", "relation": "background", "claims": [], "why": "general topic"}],
                                  [("OpenAlex", lambda q: [dict(B_PAPER)])])
    assert done == {"p.md": "none"} and "evidence_grade: none" in text
    assert len(pool.calls) == 1, "one AI call per page"
    assert "### Background reading (does not count towards the grade)" in text and "Lakos (2009)" in text


def test_supports_without_a_claim_counts_as_background(write_page, monkeypatch, timeline):
    done, _, _ = judge_page(write_page, monkeypatch, timeline,
                            [{"id": "c1", "relation": "supports", "claims": [], "why": "vague"}],
                            [("OpenAlex", lambda q: [dict(B_PAPER)])])
    assert done == {"p.md": "none"}


def test_a_contradicting_record_does_not_raise_the_grade_and_is_shown_separately(write_page, monkeypatch, timeline):
    done, text, _ = judge_page(write_page, monkeypatch, timeline,
                               [{"id": "c1", "relation": "contradicts", "claims": [1], "why": "dated 1850"}],
                               [("National Archives", lambda q: [dict(A_RECORD)])])
    assert done == {"p.md": "none"}
    assert "evidence_grade: none" in text
    assert "### Contradictory evidence (does not count as support)" in text
    assert "⚠ contradicts claim 1" in text and '"evidence-contradicts"' in text


def test_supporting_record_still_earns_grade(write_page, monkeypatch, timeline):
    done, text, _ = judge_page(write_page, monkeypatch, timeline,
                               [{"id": "c1", "relation": "supports", "claims": [1], "why": "dated 1849"}],
                               [("National Archives", lambda q: [dict(A_RECORD)])])
    assert done == {"p.md": "A"}
    assert "supports claim 1" in text


def test_new_judgement_can_downgrade_a_stale_grade_and_records_history(write_page, monkeypatch, timeline):
    import state
    write_page("p.md", "Consecration of St John's Cathedral", 1849, grade="A")
    monkeypatch.setattr(ev, "SOURCES", [("OpenAlex", lambda q: [dict(B_PAPER)])])
    pool = SaysJudge([{"id": "c1", "relation": "supports", "claims": [1], "why": "specific study"}])
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert done == {"p.md": "B"}
    assert "evidence_grade: B" in (timeline / "p.md").read_text(encoding="utf-8")
    changes = state.load("evidence_meta")["grade_changes"]
    assert changes[-1]["from"] == "A" and changes[-1]["to"] == "B"
    assert changes[-1]["contradiction_found"] is False


def test_graded_pages_are_judged_again_once_but_research_graded_pages_are_not(write_page, timeline):
    engine = write_page("engine.md", "Treaty signing", extra="\n## Evidence\n\nold judgement\n")
    write_page("research.md", "Police founding", extra="\n## Evidence\n\nx\n\n## Research notes\n\ny\n")
    done = {"engine.md": "B", "research.md": "A", "none.md": "none", "gone.md": "A"}
    assert ev.reopen_for_rejudge(done) == 1
    assert done == {"research.md": "A", "none.md": "none", "gone.md": "A"}
    done["engine.md"] = "B"
    assert ev.reopen_for_rejudge(done) == 0  # only once per JUDGE_VERSION
    assert engine.exists()


def test_audit_asks_a_different_model_and_records_agreement(write_page, monkeypatch, timeline):
    monkeypatch.setattr(ev, "AUDIT_SHARE", 1)
    _, _, pool = judge_page(write_page, monkeypatch, timeline,
                            [{"id": "c1", "relation": "supports", "claims": [1], "why": "x"}],
                            [("OpenAlex", lambda q: [dict(B_PAPER), dict(B_PAPER, url="https://doi.org/10.1/y")])],
                            second=[{"id": "c1", "relation": "background", "claims": [], "why": "general"}])
    assert pool.calls == [None, ["nemotron-super", "gemma"]], "one judgement, then an audit that excludes the first model"
    (rec,) = state.load("evidence_audit")["audits"]
    assert rec["models"] == ["nemotron-ultra", "nemotron-super"] and rec["grades"] == ["B", "none"]
    assert (rec["same"], rec["candidates"]) == (1, 2)  # c2 left out by both; c1 judged differently
    assert "same grade on 0%" in "\n".join(ev.audit_summary())


def test_audit_answered_by_the_same_model_is_not_recorded(write_page, monkeypatch, timeline):
    monkeypatch.setattr(ev, "AUDIT_SHARE", 1)
    judge_page(write_page, monkeypatch, timeline, [], [("OpenAlex", lambda q: [dict(B_PAPER)])],
               second_model="nemotron-ultra")
    assert state.load("evidence_audit") == {}


# --- the event itself is claim 1 (PR #4: archive files named after the event could only be
# background reading, so graded pages fell to none under JUDGE_VERSION 2) ---

class PromptJudge(SaysJudge):
    def generate_json(self, role, prompt, only=None, **k):
        self.prompt = prompt
        return super().generate_json(role, prompt, only=only, **k)


def test_the_event_itself_is_claim_1_so_a_record_of_it_can_grade_the_page(write_page, monkeypatch, timeline):
    write_page("p.md", "Signing of the Treaty", 1900, claims=())
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: [dict(A_RECORD)])])
    pool = PromptJudge([{"id": "c1", "relation": "supports", "claims": [1], "why": "file on the treaty"}])
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert "1. Signing of the Treaty took place in Hong Kong (1900)" in pool.prompt
    assert "no explicit claims" not in pool.prompt
    assert done == {"p.md": "A"}


def test_pages_left_with_only_background_reading_are_judged_again_once(write_page, timeline):
    state.save("evidence_meta", {"judge_version": 2})
    write_page("bg.md", "Harbour survey", extra="\n## Evidence\n\n### Background reading (does not count towards the grade)\n\n- x\n")
    write_page("empty.md", "Plague", extra="\n## Evidence\n\nnothing relevant found yet\n")
    write_page("graded.md", "Treaty", extra="\n## Evidence\n\n### Background reading\n\n- x\n")
    done = {"bg.md": "none", "empty.md": "none", "graded.md": "B"}
    assert ev.reopen_for_rejudge(done) == 1
    assert done == {"empty.md": "none", "graded.md": "B"}
    done["bg.md"] = "none"
    assert ev.reopen_for_rejudge(done) == 0  # only once per JUDGE_VERSION
