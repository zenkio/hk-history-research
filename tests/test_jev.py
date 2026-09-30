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
    assert [len(q) for q in sent] == [16, 2]
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
