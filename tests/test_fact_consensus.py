import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consensus_run as cr
import fact_consensus as fc

# V2.2 multi-AI consensus (owner direction 2026-10-18). All sentences are synthetic.
SENTENCE = "On 3 March 1850, the harbour office was opened at Pier Head by the Harbour Master."


def fact(action, **slots):
    base = {"subject": "", "action": action, "agent": "", "when": "", "where": "", "negated": False, "kind": "event"}
    return dict(base, **slots)


def answer(facts, tags=None, view="Example Harbour Department", stance="neutral"):
    return {"facts": facts, "tags": tags or {k: [] for k in fc.fx.TAG_KINDS},
            "angle": {"view_of": view, "stance": stance}}


def test_a_fact_two_models_found_is_settled_and_keeps_who_backed_it():
    pooled = fc.pool_sentence({
        "A": answer([fact("was opened", subject="the harbour office", where="Pier Head")]),
        "B": answer([fact("opened", subject="the harbour office", where="Pier Head")]),
    })
    (claim,) = pooled["facts"]
    assert claim["status"] == fc.SETTLED and claim["backed_by"] == ["A", "B"] and claim["not_found_by"] == []


def test_a_fact_only_one_model_found_is_single_and_names_who_missed_it():
    pooled = fc.pool_sentence({"A": answer([fact("was opened")]), "B": answer([])})
    (claim,) = pooled["facts"]
    assert claim["status"] == fc.SINGLE and claim["backed_by"] == ["A"] and claim["not_found_by"] == ["B"]


def test_models_that_differ_on_a_detail_make_a_questioned_claim_with_both_values():
    pooled = fc.pool_sentence({
        "A": answer([fact("was opened", when="3 March 1850")]),
        "B": answer([fact("was opened", when="4 March 1850")]),
    })
    (claim,) = pooled["facts"]
    assert claim["status"] == fc.QUESTIONED
    assert claim["variants"]["when"] == {"3 March 1850": ["A"], "4 March 1850": ["B"]}


def test_a_detail_that_only_adds_words_is_not_a_disagreement_and_empty_is_not_a_value():
    pooled = fc.pool_sentence({
        "A": answer([fact("was opened", when="March 1850", where="")]),
        "B": answer([fact("was opened", when="3 March 1850", where="Pier Head")]),
    })
    (claim,) = pooled["facts"]
    assert claim["status"] == fc.SETTLED and claim["variants"] == {} and claim["where"] == "Pier Head"


def test_one_model_never_backs_a_claim_twice():
    pooled = fc.pool_sentence({"A": answer([fact("was opened"), fact("opened")])})
    assert len(pooled["facts"]) == 2 and all(c["status"] == fc.SINGLE for c in pooled["facts"])


def test_tags_and_angle_are_pooled_with_their_backers():
    tags_a = {"people": ["Harbour Master"], "groups": [], "places": ["Pier Head"], "things": []}
    tags_b = {"people": ["Harbour Master"], "groups": [], "places": [], "things": []}
    pooled = fc.pool_sentence({"A": answer([], tags_a, view="X"), "B": answer([], tags_b, view="Y")})
    by_text = {t["text"]: t for t in pooled["tags"]}
    assert by_text["Harbour Master"]["status"] == fc.SETTLED
    assert by_text["Pier Head"]["status"] == fc.SINGLE and by_text["Pier Head"]["not_found_by"] == ["B"]
    assert pooled["angle"]["view_of"]["status"] == fc.QUESTIONED
    assert pooled["angle"]["stance"]["status"] == fc.SETTLED


def test_the_checker_sees_the_sentence_and_the_claim_but_never_a_model_name():
    pooled = fc.pool_sentence({"Alpha": answer([fact("was opened", subject="the harbour office")]),
                               "Beta": answer([])})
    seen = []

    def beta(prompt):
        seen.append(prompt)
        return "1"
    fc.check_singles(pooled, SENTENCE, {"Alpha": lambda p: "3", "Beta": beta}, [])
    assert SENTENCE in seen[0] and "was opened" in seen[0]
    assert "Alpha" not in seen[0] and "Beta" not in seen[0]


def test_a_single_claim_is_settled_by_agree_questioned_by_disagree_and_left_by_unsure():
    for reply, status in (("1", fc.SETTLED), ("2", fc.QUESTIONED), ("3", fc.SINGLE)):
        pooled = fc.pool_sentence({"A": answer([fact("was opened")]), "B": answer([])})
        fc.check_singles(pooled, SENTENCE, {"A": lambda p: "3", "B": lambda p: reply}, [])
        (claim,) = pooled["facts"]
        assert claim["status"] == status and claim["checked_by"][0]["model"] == "B"


def test_a_claim_is_never_checked_by_the_model_that_made_it_and_settled_claims_are_not_checked():
    pooled = fc.pool_sentence({"A": answer([fact("was opened")])})
    log = []
    fc.check_singles(pooled, SENTENCE, {"A": lambda p: "1"}, log)
    assert pooled["facts"][0]["status"] == fc.SINGLE and log == [{"step": "cross_check", "skipped": "no other model"}]
    both = fc.pool_sentence({"A": answer([fact("was opened")]), "B": answer([fact("was opened")])})
    asked = []
    fc.check_singles(both, SENTENCE, {"A": asked.append, "B": asked.append}, [])
    assert asked == []


def test_a_checker_that_fails_leaves_the_claim_single():
    pooled = fc.pool_sentence({"A": answer([fact("was opened")]), "B": answer([])})

    def broken(prompt):
        raise RuntimeError("provider down")
    log = []
    fc.check_singles(pooled, SENTENCE, {"A": broken, "B": broken}, log)
    assert pooled["facts"][0]["status"] == fc.SINGLE and log[-1]["error"] == "RuntimeError"


def rows_for(run_id, date, a_finds, status="single"):
    pooled = {"models": ["A", "B"], "tags": [], "facts": [
        {"claim_type": "fact", "action": "was opened", "backed_by": ["A"] if a_finds else ["B"],
         "checked_by": [], "status": status}]}
    return fc.history_rows(run_id, date, "s1", pooled)


def test_history_shows_a_model_whose_answer_changed_and_a_claim_whose_status_changed(tmp_path):
    day1, day2 = rows_for("1", "2026-10-18", True), rows_for("2", "2026-10-19", False, status="settled")
    path = tmp_path / "history.jsonl"
    fc.append_history(path, day1)
    fc.append_history(path, day2)
    assert len(fc.read_history(path)) == 4 and fc.read_history(tmp_path / "none.jsonl") == []
    moved = fc.changes(day1, day2)
    assert moved["status_changes"] == [{"source_id": "s1", "claim": "was opened", "was": "single", "now": "settled"}]
    assert {(f["model"], f["was_found"], f["now_found"]) for f in moved["answer_flips"]} == {
        ("A", True, False), ("B", False, True)}
    report = fc.model_report(day2)
    assert report["B"]["found_and_settled"] == 1 and report["A"]["missed_settled"] == 1


KEY = {"sentences": [{"source_id": "s1", "sentence": SENTENCE, "era": ["05-opium-war"],
                      "facts": [], "angle": {}, "tags": {}}]}
RECORD = {"source_id": "s1", "institution": "Example Harbour Department",
          "source_type": "contemporary_official_report", "source_date": "1850-03-04"}


def test_a_run_pools_the_models_checks_single_claims_and_drops_a_model_that_runs_out(monkeypatch):
    class OutOfQuota(Exception):
        pass

    def fake_extract(ask, sentence, record):
        return ask(sentence)
    monkeypatch.setattr(cr, "extract_sentence", fake_extract)
    a_answer = answer([fact("was opened", subject="the harbour office")])

    def ask_a(sentence):
        return a_answer

    def ask_b(sentence):
        raise OutOfQuota()
    sentences, rows, stopped = cr.run_consensus({"A": ask_a, "B": ask_b}, KEY, {"s1": RECORD}, "9", "2026-10-18",
                                                stop_on=(OutOfQuota,))
    assert stopped == {"B": "OutOfQuota"}
    (claim,) = sentences[0]["pooled"]["facts"]
    assert claim["backed_by"] == ["A"] and claim["status"] == fc.SINGLE
    assert [r["model"] for r in rows] == ["A"] and rows[0]["found"] is True


def test_models_answer_a_sentence_side_by_side_not_one_after_another(monkeypatch):
    import threading
    both_inside = threading.Barrier(2, timeout=5)   # only passes if both models are asking at once
    monkeypatch.setattr(cr, "extract_sentence", lambda ask, sentence, record: ask(sentence))

    def ask(sentence):
        both_inside.wait()
        return answer([fact("was opened", subject="the harbour office")])
    sentences, rows, stopped = cr.run_consensus({"A": ask, "B": ask}, KEY, {"s1": RECORD}, "9", "2026-10-19")
    assert stopped == {} and sentences[0]["pooled"]["facts"][0]["backed_by"] == ["A", "B"]


def test_main_stops_with_a_message_when_no_model_can_be_used(tmp_path, monkeypatch, capsys):
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "topic.json").write_text(json.dumps({"sources": [RECORD]}))
    (tmp_path / "key.json").write_text(json.dumps(KEY))

    class FakePool:
        routing = {cr.ROLE: ["Model A"]}
        models = {"Model A": {"api_id": "a-1"}}

        def remaining(self, name, role):
            return 0
    import gemini_pool
    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    args = ["--key", str(tmp_path / "key.json"), "--packets", str(packets),
            "--models", "Model A, Model Z", "--output-dir", str(tmp_path / "out")]
    assert cr.main(args) == 1
    out = capsys.readouterr().out
    assert "Model A | unavailable" in out and f"Model Z | not in routing role {cr.ROLE}" in out
    (tmp_path / "key.json").write_text(json.dumps({"sentences": [dict(KEY["sentences"][0], source_id="nope")]}))
    assert cr.main(args) == 2
