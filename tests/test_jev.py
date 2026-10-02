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
             "year": 1900, "title": f"Record {i}", "note": "n", "url": f"https://x/{i}", "cite": f"C{i}"}
            for i in range(1, n + 1)]


def test_jev_audit_asks_at_most_16_questions_a_call_and_records_agreement(write_page, timeline, monkeypatch):
    path = write_page("p.md", "Signing of the Treaty", 1900)
    cands = candidates(18)
    sent = []

    def decide(page, questions):
        sent.append(sorted(questions))
        assert "1. Signing of the Treaty took place in Hong Kong" in page
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


# --- the Jev trial on already-judged pages (owner, 2026-10-01: 100 pages) ----------------------

class TrialJudge:
    """The evidence judge in the trial: keeps c1 as supports and c3 as background."""
    routing = {"evidence": ["nemotron-ultra"]}

    def __init__(self):
        self.calls = 0

    def generate_json(self, role, prompt, **k):
        self.calls += 1
        return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "names it"},
                             {"id": "c3", "relation": "background", "claims": [], "why": "general"}]}, "nemotron-ultra", []


EVIDENCE = "\n## Evidence\n\n> [!abstract] Evidence grade: **A**\n\n- [CO 129/1](https://x/1) (supports claim 1): the file\n"


def test_trial_asks_the_judge_again_on_the_same_results_then_goes_on_to_graded_pages(write_page, timeline, monkeypatch):
    # PR #12: version 1 compared Jev with the page's list, but the judge may never have seen a result
    # the page leaves out, so both judges now label the same search results
    monkeypatch.setattr(ev, "JEV_TRIAL_PAGES", 2)
    monkeypatch.setattr(ev, "JEV_TRIAL_GRADED_PAGES", 1)
    for i in range(4):
        write_page(f"p{i}.md", f"Event {i}", 1900, extra=EVIDENCE)
    write_page("research.md", "Researched", 1900, extra=EVIDENCE + "\n## Research notes\n\nx\n")
    write_page("unjudged.md", "Plain", 1900)
    monkeypatch.setattr(ev, "gather", lambda q: (candidates(3), []))
    seen = []

    def fake_audit(path, title, date, claims, cands, kept, model, trial=False, phase=None):
        seen.append((path.rsplit("/", 1)[-1], phase))
        assert trial == ev.TRIAL_VERSION and model == "nemotron-ultra"
        assert [c["id"] for c in cands] == ["c1", "c2", "c3"]
        assert {c["id"]: (c["relation"], c["why"]) for c in kept} == {"c1": ("supports", "names it"),
                                                                       "c3": ("background", "general")}
        log = state.load("evidence_audit")
        rec = {"page": path.rsplit("/", 1)[-1], "trial": trial, "grades": ["A", "A"], "labels": []}
        if phase:
            rec["phase"] = phase
        log.setdefault("jev", []).append(rec)
        state.save("evidence_audit", log)
        return True
    monkeypatch.setattr(ev, "jev_audit", fake_audit)
    judge = TrialJudge()
    done = {"p0.md": "A", "p1.md": "B", "p2.md": "none", "p3.md": "A", "research.md": "A", "unjudged.md": "none"}
    assert ev.jev_trial(judge, done, time.time() + 60) == 2 and judge.calls == 2
    assert all(phase is None for _, phase in seen)
    assert ev.jev_trial(judge, done, time.time() + 60) == 1, "then a graded page not yet tried"
    page, phase = seen[-1]
    assert phase == "graded" and done[page] in ("A", "B") and page not in [p for p, _ in seen[:-1]]
    assert ev.jev_trial(judge, done, time.time() + 60) == 0, "the trial ends at JEV_TRIAL_GRADED_PAGES"
    assert "research.md" not in [p for p, _ in seen] and "unjudged.md" not in [p for p, _ in seen]


def test_version_1_trial_records_do_not_count(write_page, timeline, monkeypatch):
    state.save("evidence_audit", {"jev": [{"page": "p0.md", "trial": True, "grades": ["A", "none"],
                                           "labels": [["supports", "out"]]}]})
    assert ev.jev_trial_summary() == "No trial results yet."
    write_page("p0.md", "Event", 1900, extra=EVIDENCE)
    monkeypatch.setattr(ev, "gather", lambda q: (candidates(1), []))
    monkeypatch.setattr(jev, "decide", lambda page, q: {k: "supports" for k in q})
    assert ev.jev_trial(TrialJudge(), {"p0.md": "A"}, time.time() + 60) == 1, "the page is tried again"


def test_trial_records_labels_and_summarises(write_page, timeline, monkeypatch):
    path = write_page("p.md", "Signing of the Treaty", 1900)
    monkeypatch.setattr(jev, "decide", lambda page, q: {k: ("supports" if k == "c1" else "out") for k in q})
    kept = [dict(candidates(2)[0], relation="supports"), dict(candidates(2)[1], relation="background")]
    rec = ev.jev_audit(str(path), "Signing of the Treaty", 1900, [], candidates(2), kept, "judge", trial=ev.TRIAL_VERSION)
    assert rec["trial"] == ev.TRIAL_VERSION and rec["labels"] == [["supports", "supports"], ["background", "out"]]
    assert ev.jev_trial_summary() == ("Same grade on 1/1 pages; same label on 1/2 results; "
                                      "of the 2 results the judge kept, Jev agreed on 1.")


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
