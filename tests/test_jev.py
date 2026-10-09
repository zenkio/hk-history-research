"""FreeJev client and the Jev evidence audit, with a fake Jev (no network)."""
import io
import time
import urllib.error

import pytest
import evidence as ev
import jev
import state

LABELS = ev.JEV_CRITERIA


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(jev, "_state", {"off": None, "remaining": None})
    monkeypatch.setattr(ev, "_jev_count", [0])
    monkeypatch.setattr(ev, "_source_fails", {})
    monkeypatch.setattr(ev, "AUDIT_SHARE", 0)
    monkeypatch.setenv("FREEJEV_API_KEY", "test-key\n")


def http_error(code):
    return urllib.error.HTTPError(jev.URL, code, "x", {}, io.BytesIO(b"{}"))


# --- reading answers --------------------------------------------------------------------------

@pytest.mark.parametrize("answer, expected", [
    ("supports", ("supports", None)),
    ({"choice": "background", "probabilities": {"background": 0.7, "out": 0.3}}, ("background", 0.7)),
    ({"answer": "out"}, ("out", None)),
    ({"probabilities": {"out": 0.2, "contradicts": 0.8}}, ("contradicts", 0.8)),
    ({"supports": 0.6, "out": 0.4}, ("supports", 0.6)),
    ("maybe", None),
    ({"reasoning": "text"}, None),
    (None, None),
])
def test_choice_is_read_from_any_likely_answer_shape(answer, expected):
    assert jev.choice_of(answer, LABELS) == expected


def test_unreadable_answer_logs_field_names_never_content():
    assert jev.shape({"secret": "page text", "p": 0.5}) == "{secret: str, p: float}"


# --- calling Jev ------------------------------------------------------------------------------

def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.delenv("FREEJEV_API_KEY")
    monkeypatch.setattr(jev, "_post", lambda body: pytest.fail("called without a key"))
    assert not jev.available() and jev.decide("s", {}) is None


def test_out_of_credits_switches_jev_off_for_the_run(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(jev, "_post", lambda body: calls.append(1) or (_ for _ in ()).throw(http_error(402)))
    assert jev.decide("s", {"q": {}}) is None
    assert not jev.available() and len(calls) == 1
    assert jev.decide("s", {"q": {}}) is None and len(calls) == 1
    assert "no credits left" in capsys.readouterr().out


def test_upstream_failure_is_retried_once(monkeypatch):
    calls = []

    def post(body):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(502)
        return {"answers": {"q": "out"}}
    monkeypatch.setattr(jev, "_post", post)
    assert jev.decide("s", {"q": {}}) == {"q": "out"} and len(calls) == 2


def test_low_balance_keeps_the_reserve(monkeypatch):
    monkeypatch.setattr(jev, "_post", lambda body: {"answers": {}, "usage": {"remaining_credits": 120}})
    assert jev.decide("s", {}) == {}
    assert not jev.available()


def test_requests_name_our_agent_so_cloudflare_lets_them_through(monkeypatch):
    # PR #11: Python's default "Python-urllib" agent got 403 (Cloudflare 1010), read as a bad key
    sent = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def urlopen(req, timeout):
        sent.append(req)
        return Resp(b'{"answers": {}}')
    monkeypatch.setattr(jev.urllib.request, "urlopen", urlopen)
    jev._post({"state": "s", "questions": {}})
    agent = sent[0].get_header("User-agent")
    assert agent and "urllib" not in agent.lower()


def test_bot_filter_403_is_not_reported_as_a_bad_key(monkeypatch, capsys):
    err = urllib.error.HTTPError(jev.URL, 403, "x", {}, io.BytesIO(b"error code: 1010"))
    monkeypatch.setattr(jev, "_post", lambda body: (_ for _ in ()).throw(err))
    assert jev.decide("s", {"q": {}}) is None and not jev.available()
    out = capsys.readouterr().out
    assert "bot filter" in out and "key rejected" not in out


# --- the evidence audit -----------------------------------------------------------------------

def candidates(n):
    return [{"id": f"c{i}", "kind": "archive record" if i % 2 else "scholarship", "grade": "A" if i % 2 else "B",
             "year": 1900, "title": f"Record {i}", "note": "n", "passage": f"Inspected source text about Record {i}.",
             "passage_status": "inspectable_text", "url": f"https://x/{i}", "cite": f"C{i}"}
            for i in range(1, n + 1)]


def test_jev_audit_asks_at_most_16_questions_a_call_and_records_agreement(write_page, timeline, monkeypatch):
    path = write_page("p.md", "Signing of the Treaty", 1900)
    cands = candidates(18)
    sent = []

    def decide(page, questions):
        sent.append(sorted(questions))
        assert "1. Signing of the Treaty occurred in 1900" in page
        return {q: {"choice": "supports" if q == "c1" else "out", "probabilities": {"supports": 0.9, "out": 0.9}}
                for q in questions}
    monkeypatch.setattr(jev, "decide", decide)
    kept = [dict(cands[0], relation="supports", claims=[1]), dict(cands[1], relation="background", claims=[])]
    rec = ev.jev_audit(str(path), "Signing of the Treaty", 1900, [], cands, kept, "nemotron-ultra")
    assert [len(q) for q in sent] == [16, 2, 3], "labels for 18 results, then 3 reason questions on the one dispute"
    assert rec["models"] == ["nemotron-ultra", "Jev"] and rec["grades"] == ["A", "A"]
    assert rec["same"] == 17 and rec["candidates"] == 18  # c2: background vs out
    assert rec["mean_probability"] == 0.9
    assert state.load("evidence_audit")["jev"] == [rec]
    assert "audits" not in state.load("evidence_audit"), "the LLM audit statistics stay separate"


def test_jev_audit_gives_up_on_an_unreadable_answer(write_page, timeline, monkeypatch, capsys):
    path = write_page("p.md", "Treaty", 1900)
    monkeypatch.setattr(jev, "decide", lambda page, q: {k: {"text": "?"} for k in q})
    assert ev.jev_audit(str(path), "Treaty", 1900, [], candidates(2), [], "m") is None
    assert "unreadable answer for c1: {text: str}" in capsys.readouterr().out
    assert state.load("evidence_audit") == {}


class Judge:
    routing = {"evidence": ["nemotron-ultra"]}

    def generate_json(self, role, prompt, **k):
        return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "x"}]}, "nemotron-ultra", []


def test_evidence_run_audits_with_jev_up_to_the_per_run_cap(write_page, timeline, monkeypatch):
    monkeypatch.setattr(ev, "JEV_SHARE", 1)
    monkeypatch.setattr(ev, "JEV_PAGES_PER_RUN", 4)
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(1))])
    audited = []
    monkeypatch.setattr(ev, "jev_audit", lambda path, *a: audited.append(path))
    pages = [f"p{i}.md" for i in range(ev.JEV_PAGES_PER_RUN + 2)]
    for i, f in enumerate(pages):
        write_page(f, f"Event {i}", 1900)
    ev.evidence_batch(Judge(), {}, [{"file": f, "status": "done"} for f in pages], time.time() + 60, limit=50)
    assert len(audited) == ev.JEV_PAGES_PER_RUN


def test_evidence_run_without_a_key_never_calls_jev(write_page, timeline, monkeypatch):
    monkeypatch.delenv("FREEJEV_API_KEY")
    monkeypatch.setattr(ev, "JEV_SHARE", 1)
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(1))])
    monkeypatch.setattr(ev, "jev_audit", lambda *a: pytest.fail("Jev called without a key"))
    write_page("p.md", "Event", 1900)
    done = {}
    ev.evidence_batch(Judge(), done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert done == {"p.md": "A"}


def test_pipeline_passes_the_jev_key_to_the_evidence_step():
    import os
    wf = open(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ingestion.yml")).read()
    assert "FREEJEV_API_KEY: ${{ secrets.FREEJEV_API_KEY }}" in wf


# --- reasons where the two judges disagree (owner, 2026-10-01) --------------------------------

ANSWERS = {"about": "forerunner", "shows": "mention", "check": "right"}


def test_disputes_record_both_judges_reasons(write_page, timeline, monkeypatch, capsys):
    path = write_page("p.md", "First Industrial Exhibition", 1914)
    cands = candidates(3)
    calls = []

    def decide(page, questions):
        calls.append(questions)
        if "c1" in questions:  # the labelling call: Jev disagrees on c2 and c3
            return {"c1": "out", "c2": "contradicts", "c3": "out"}
        assert "c1 |" not in page, "the reasons call shows only the disputed results"
        assert "names the exhibition" not in page, "the judge's words stay out of the shared text"
        return {q: ANSWERS[q.split("_", 1)[1]] for q in questions}
    monkeypatch.setattr(jev, "decide", decide)
    kept = [dict(cands[2], relation="supports", why="The record names the exhibition.")]
    rec = ev.jev_audit(str(path), "First Industrial Exhibition", 1914, [], cands, kept, "judge")
    asked = calls[1]
    assert sorted(asked) == sorted(f"c{i}_{k}" for i in (2, 3) for k in ("about", "shows", "check"))
    assert "left search result c2 out" in asked["c2_check"]["instructions"]
    assert set(asked["c2_check"]["criteria"]) == {"right", "wrong"}
    assert "'supports', because: \"The record names the exhibition.\"" in asked["c3_check"]["instructions"]
    assert set(asked["c3_check"]["criteria"]) == {"right", "overstated", "wrong"}
    d2, d3 = rec["disputes"]
    assert (d2["judge"], d2["judge_why"], d2["jev"], d2["jev_why"]) == ("out", "", "contradicts", ANSWERS)
    assert (d3["judge"], d3["judge_why"], d3["jev"]) == ("supports", "The record names the exhibition.", "out")
    assert d2["url"] == "https://x/2" and d2["title"] == "Record 2"
    assert state.load("evidence_audit")["jev"][0]["disputes"] == rec["disputes"]
    out = capsys.readouterr().out
    assert ("judge out: no reason given (the judge explains only results it keeps) | Jev contradicts: "
            "a plan or forerunner, not the event; only mentions it; the judge is right") in out
    assert "judge supports: The record names the exhibition." in out


def test_reason_questions_fit_16_to_a_call(monkeypatch):
    sent = []
    disputed = [(c, "out", "") for c in candidates(11)]
    monkeypatch.setattr(jev, "decide", lambda page, q: sent.append(len(q)) or {})
    ev.jev_reasons("T", 1900, "1. x", disputed)
    assert sent == [15], "an empty answer stops asking"
    sent.clear()
    monkeypatch.setattr(jev, "decide", lambda page, q: sent.append(len(q)) or {k: "right" for k in q})
    got = ev.jev_reasons("T", 1900, "1. x", disputed)
    assert sent == [15, 15, 3] and len(got) == 11 and got["c1"] == {"check": "right"}


def test_no_dispute_means_no_reason_questions(write_page, timeline, monkeypatch):
    path = write_page("p.md", "Treaty", 1900)
    calls = []
    monkeypatch.setattr(jev, "decide", lambda page, q: calls.append(q) or {k: "out" for k in q})
    rec = ev.jev_audit(str(path), "Treaty", 1900, [], candidates(3), [], "m")
    assert len(calls) == 1 and "disputes" not in rec


# --- Jev as a tip-off: the judge looks again (owner, 2026-10-02) -----------------------------

@pytest.mark.parametrize("judge_label, jev_label, why, expected", [
    ("out", "supports", {"about": "event", "shows": "happened"}, True),          # HKTV, Amoy Gardens
    ("out", "supports", {"about": "moment", "shows": "mention"}, False),         # 2009 Games for 2008 Olympics
    ("out", "supports", {"about": "unrelated", "shows": "nothing"}, False),      # a Cabinet record, tramway strike
    ("supports", "background", {"about": "moment", "shows": "mention", "check": "wrong"}, True),   # mui tsai 1925
    ("supports", "background", {"about": "event", "shows": "detail", "check": "overstated"}, False),  # the 1898 Convention
    ("contradicts", "supports", {"about": "event", "shows": "mention"}, False),  # 1922 dates: both count it
])
def test_second_look_only_where_jevs_reasons_back_its_label(judge_label, jev_label, why, expected):
    assert ev.worth_second_look({"judge": judge_label, "jev": jev_label, "jev_why": why}) is expected


class LookAgainJudge:
    """Keeps Record 1 the first time; on a second look alone it drops Record 1 and keeps Record 2."""
    routing = {"evidence": ["nemotron-ultra"]}

    def __init__(self):
        self.prompts = []

    def generate_json(self, role, prompt, **k):
        self.prompts.append(prompt)
        alone = sum(f"Record {i} |" in prompt for i in (1, 2, 3)) == 1
        if alone and "Record 2 |" in prompt:
            return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "a study of it"}]}, "m", []
        if alone:
            return {"relevant": []}, "m", []
        return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "first look"}]}, "m", []


def jev_disagrees(c1_why, c2_why):
    def decide(page, questions):
        if "c1" in questions:
            return {"c1": "out", "c2": "supports", "c3": "out"}
        why = {"c1": c1_why, "c2": c2_why}
        return {q: why[q.split("_")[0]][q.split("_")[1]] for q in questions}
    return decide


def test_judge_looks_again_where_jev_has_good_reasons_and_its_second_decision_stands(write_page, timeline, monkeypatch):
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(3))])
    monkeypatch.setattr(jev, "decide", jev_disagrees({"about": "moment", "shows": "mention", "check": "wrong"},
                                                     {"about": "event", "shows": "happened", "check": "wrong"}))
    write_page("p.md", "Event", 1900)
    judge, done = LookAgainJudge(), {}
    ev.evidence_batch(judge, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert len(judge.prompts) == 3, "the first look, then one look at each disputed result"
    assert done == {"p.md": "B"}, "Record 1 (an archive record) dropped, Record 2 (a study) kept"
    page = (timeline / "p.md").read_text()
    assert "https://x/2" in page and "https://x/1" not in page
    looks = state.load("evidence_audit")["jev"][-1]["second_look"]
    assert [(o["url"], o["judge"], o["jev"], o["second"]) for o in looks] == [
        ("https://x/1", "supports", "out", "out"), ("https://x/2", "out", "supports", "supports")]


def test_jev_without_good_reasons_changes_nothing(write_page, timeline, monkeypatch):
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(3))])
    monkeypatch.setattr(jev, "decide", jev_disagrees({"about": "event", "shows": "happened", "check": "right"},
                                                     {"about": "moment", "shows": "mention", "check": "wrong"}))
    write_page("p.md", "Event", 1900)
    judge, done = LookAgainJudge(), {}
    ev.evidence_batch(judge, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert len(judge.prompts) == 1 and done == {"p.md": "A"}
    assert "second_look" not in state.load("evidence_audit")["jev"][-1]


def test_pipeline_no_longer_runs_the_trial():
    import seed_history
    assert not hasattr(ev, "jev_trial") and "jev_trial" not in open(seed_history.__file__).read()


# --- the review round of the core eras (owner, 2026-10-02) -----------------------------------

def test_core_pages_judged_by_the_engine_are_reviewed_once(write_page, timeline):
    state.save("evidence_meta", {"judge_version": 3})
    ev_text = "\n## Evidence\n\n- [x](https://x/1) (supports claim 1): y\n"
    write_page("05-opium-war/a.md", "Treaty", extra=ev_text)
    write_page("16-national-security-era/b.md", "Law", extra=ev_text)
    write_page("04-ming-and-qing/c.md", "Older", extra=ev_text)
    write_page("05-opium-war/dr.md", "Researched", extra=ev_text + "\n## Research notes\n\nx\n")
    write_page("05-opium-war/never.md", "Plain")
    done = {"05-opium-war/a.md": "A", "16-national-security-era/b.md": "none", "04-ming-and-qing/c.md": "B",
            "05-opium-war/dr.md": "A", "05-opium-war/never.md": "none"}
    assert ev.reopen_for_rejudge(done) == 3
    assert "05-opium-war/a.md" not in done and "16-national-security-era/b.md" not in done
    assert "04-ming-and-qing/c.md" not in done
    assert state.load("evidence_meta")["rejudged_from"] == {
        "05-opium-war/a.md": "A",
        "16-national-security-era/b.md": "none",
        "04-ming-and-qing/c.md": "B",
    }
    assert ev.reopen_for_rejudge(done) == 0, "once per JUDGE_VERSION"


def test_a_judged_page_keeps_its_evidence_when_a_source_is_down(write_page, timeline, monkeypatch):
    def down(q):
        raise OSError("timed out")
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(2)), ("Internet Archive", down)])
    path = write_page("p.md", "Event", 1900, extra="\n## Evidence\n\n- [x](https://x/9) (supports claim 1): y\n")
    before = path.read_text()
    assert ev.evidence_for_page(LookAgainJudge(), str(path)) == "retry"
    assert path.read_text() == before


def test_core_era_matches_seed_history():
    import seed_history
    assert ev.JEV_REVIEW_FROM == seed_history.CORE_ERA_START


# --- a new judgement can lower a stale grade, recording the change -----------------------------

def graded_page(write_page, grade):
    path = write_page("05-opium-war/p.md", "Event", 1900, extra="\n## Evidence\n\n- [old](https://x/9) (supports claim 1): found before\n")
    path.write_text(path.read_text().replace("---\n", f"---\nevidence_grade: {grade}\n", 1))
    return path


class KeepsNothing:
    routing = {"evidence": ["nemotron-ultra"]}

    def generate_json(self, role, prompt, **k):
        return {"relevant": []}, "m", []


def test_a_new_judgement_can_lower_a_grade_and_records_the_change(write_page, timeline, monkeypatch):
    import state
    monkeypatch.setenv("FREEJEV_API_KEY", "")
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(2))])
    path = graded_page(write_page, "B")
    assert ev.evidence_for_page(KeepsNothing(), str(path)) == "none"
    assert "evidence_grade: none" in path.read_text()
    change = state.load("evidence_meta")["grade_changes"][-1]
    assert (change["from"], change["to"]) == ("B", "none")
    assert change["page"] == "05-opium-war/p.md"


def test_a_second_look_may_lower_a_grade(write_page, timeline, monkeypatch):
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(3))])
    monkeypatch.setattr(jev, "decide", jev_disagrees({"about": "moment", "shows": "mention", "check": "wrong"},
                                                     {"about": "moment", "shows": "mention", "check": "right"}))
    path = graded_page(write_page, "A")
    assert ev.evidence_for_page(LookAgainJudge(), str(path)) == "none"
    assert "https://x/1" not in path.read_text()


def test_a_higher_grade_from_a_new_search_is_written(write_page, timeline, monkeypatch):
    monkeypatch.setenv("FREEJEV_API_KEY", "")
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: candidates(3))])
    path = graded_page(write_page, "B")
    assert ev.evidence_for_page(LookAgainJudge(), str(path)) == "A" and "https://x/1" in path.read_text()
