import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consolidate_pipeline as cp
from test_consolidate_drafts import PAGE

CUR = [{"text": "The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking.", "by": ["Nemotron 3 Ultra"]}]
NEW = ["Pottinger signed for Britain.", "29 August 1843 was given by this draft."]
GOOD = ("[C1,N2] The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking, although another "
        "account gives 29 August 1843.\n[N1] Pottinger signed for Britain.")


def record():
    return {"facts": [{"id": "f1", "text": "Signed 29 August 1842"}]}


def test_each_sentence_records_who_backs_it_from_the_sentences_it_was_made_of():
    units, left, used = cp.fold_section(lambda s, p: GOOD, "What happened", CUR, NEW, "Claude")
    assert (left, used) == ([], 1)
    assert units[0]["by"] == ["Nemotron 3 Ultra", "Claude"]  # merged current + new sentence
    assert units[1]["by"] == ["Claude"]  # only the new draft says it


def test_dropping_a_sentence_or_inventing_a_number_is_refused_and_fed_back():
    prompts = []

    def call(system, prompt):
        prompts.append(prompt)
        return "[C1] The treaty was signed in 1999 off Nanking." if len(prompts) == 1 else GOOD
    units, left, used = cp.fold_section(call, "What happened", CUR, NEW, "Claude")
    assert (left, used) == ([], 2)
    assert "N1 not used" in prompts[1] and "number not in the texts: 1999" in prompts[1]


def test_section_that_never_passes_keeps_current_and_adds_new_unchanged_and_is_reported():
    units, left, used = cp.fold_section(lambda s, p: "no tags here", "What happened", CUR, NEW, "Claude", tries=2)
    assert left and used == 2
    assert [u["text"] for u in units] == [CUR[0]["text"], *NEW] and units[2]["by"] == ["Claude"]


def test_model_names_long_and_repeated_sentences_are_refused():
    cur = [{"text": "The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking.", "by": ["A"]}]
    new = ["Pottinger signed for Britain."]
    bad = ("[C1,N1] The Gemini draft says the treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking.\n"
           "[C1] The treaty was signed on 29 August 1842 aboard HMS Cornwallis at Nanking.")
    lines, tag_problems = cp.parse_fold(bad, 1, 1)
    problems = cp.check_fold(lines, cur, new)
    assert any("do not write" in p for p in problems) and any("repeats itself" in p for p in problems)
    long_line = "[C1,N1] " + "The treaty was signed " + " and the signing was long" * 12 + " 29 August 1842."
    lines, _ = cp.parse_fold(long_line, 1, 1)
    assert any("too long" in p for p in cp.check_fold(lines, cur, new))


def test_whole_page_folds_drafts_in_order_and_ends_with_sections_and_backing():
    seen = []

    def call(system, prompt):
        seen.append(prompt)
        return GOOD if "29 August 1843" in prompt else "[C1,N1] " + "The treaty was signed on 29 August 1842."
    rec, report = cp.run(PAGE, record(), call, tries=1)
    assert report["drafts"][0].startswith("Nemotron")
    assert len(rec["sections"]) == 7 and rec["sections"][0]["units"][0]["by"]
    assert len(rec["sentence_ai"]) == 7 and rec["sentence_facts"][0][0] == ["f1"]


def test_unavailable_writer_falls_back_instead_of_crashing():
    def call(system, prompt):
        raise cp.WriterUnavailable("502 overloaded")
    rec, report = cp.run(PAGE, record(), call, tries=2)
    assert all(f["fallback"] for f in report["folds"]) and report["folds"][0]["problems"] == ["writer unavailable"]
    assert "Pottinger signed for Britain." in " ".join(rec["narrative"])


def test_gateway_call_waits_and_asks_again_when_the_model_is_overloaded(monkeypatch):
    import multi_ai_trial as mt
    answers = [Exception("502 all_models_failed overloaded"), {"output": {"text": "ok"}, "usage": {"billing": "free"}}]

    def fake_post(body, token, key):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(mt, "post_gateway", fake_post)
    monkeypatch.setattr(cp.time, "sleep", lambda s: None)
    assert cp.gateway_call("m", "t")("sys", "prompt") == "ok"
    monkeypatch.setattr(mt, "post_gateway", lambda *a: (_ for _ in ()).throw(Exception("422 no_eligible_route")))
    with pytest.raises(Exception, match="no_eligible_route"):  # a real bug is not retried or hidden
        cp.gateway_call("m", "t")("sys", "prompt")


def test_gateway_call_waits_for_a_resting_model_to_be_free_again(monkeypatch):
    import multi_ai_trial as mt
    slept, calls = [], []

    def fake_post(body, token, key):
        calls.append(1)
        if len(calls) == 1:
            raise mt.QuotaExhausted("quota_exhausted resting, is free again at 2999-01-01T00:00:00Z")
        return {"output": {"text": "ok"}, "usage": {"billing": "free"}}
    monkeypatch.setattr(mt, "post_gateway", fake_post)
    monkeypatch.setattr(mt, "rest_seconds", lambda m, now=None: 42.0)
    monkeypatch.setattr(cp.time, "sleep", slept.append)
    assert cp.gateway_call("m", "t")("s", "p") == "ok" and slept == [47.0]
