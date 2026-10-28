import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import multi_ai_trial as mat

EVENTS = [{"id": "e1", "title": "Treaty of Nanking", "year": 1842}, {"id": "e2", "title": "Convention of Peking", "year": 1860}]


def answer(model, text="draft", applied=0, finish="stop", billing="free"):
    return {"output": {"text": text}, "choice": {"temperatureApplied": applied, "seedApplied": 5, "finishReason": finish},
            "usage": {"modelId": model + "-id", "billing": billing}}


def test_request_pins_one_model_with_temperature_zero_seed_and_long_output():
    body = mat.request_body(EVENTS[0], "kimi", 7)
    o = body["options"]
    assert o["models"] == ["kimi"] and o["temperature"] == 0 and o["seed"] == 7
    assert o["maxOutputTokens"] >= 4000  # the gateway default of 2,048 cuts a page off
    assert "Treaty of Nanking" in body["input"]["prompt"] and "Britain" in body["input"]["prompt"]


def test_every_event_is_drafted_by_every_model_and_gateway_facts_are_kept():
    calls = []

    def post(body, key):
        calls.append((body["options"]["models"][0], key))
        return answer(body["options"]["models"][0], applied="ignored" if body["options"]["models"][0] == "kimi" else 0)

    records, repeat, failures = mat.run_trial(EVENTS, ["kimi", "qwen"], 1, post, sleep=lambda s: None)
    assert len(records) == 4 and not failures and repeat == []
    assert len({k for _, k in calls}) == 4  # distinct idempotency keys
    assert {r["temperature_applied"] for r in records if r["asked_model"] == "kimi"} == {"ignored"}
    assert all(r["answered_model"].endswith("-id") for r in records)


def test_repeat_test_counts_distinct_answers_and_uses_new_keys():
    seen = {"n": 0}
    keys = []

    def post(body, key):
        keys.append(key)
        seen["n"] += 1
        return answer("m", text="same" if seen["n"] % 2 else "other")

    _, repeat, _ = mat.run_trial(EVENTS[:1], ["m"], 1, post, repeat_event="e1", repeats=4, sleep=lambda s: None)
    assert repeat == [{"model": "m", "calls": 4, "distinct_answers": 2}]
    assert len(set(keys)) == len(keys)


def test_quota_exhausted_stops_the_run_and_a_paid_answer_is_refused():
    def post(body, key):
        raise mat.QuotaExhausted("quota_exhausted")

    records, _, failures = mat.run_trial(EVENTS, ["a", "b"], 1, post, sleep=lambda s: None)
    assert records == [] and failures[0]["error"] == "quota_exhausted" and len(failures) == 1

    def paid(body, key):
        return answer("a", billing="paid")

    records, _, failures = mat.run_trial(EVENTS, ["a"], 1, paid, sleep=lambda s: None)
    assert records == [] and failures


def test_other_failures_are_recorded_and_the_run_goes_on():
    def post(body, key):
        if body["options"]["models"][0] == "bad":
            raise Exception("502 all_models_failed")
        return answer("good")

    records, _, failures = mat.run_trial(EVENTS[:1], ["bad", "good"], 1, post, sleep=lambda s: None)
    assert [r["asked_model"] for r in records] == ["good"] and failures[0]["model"] == "bad"


def test_summary_prints_counts_only_no_titles_or_text():
    records = [mat.record_of(EVENTS[0], "kimi", answer("kimi", text="secret draft text", finish="length"))]
    out = mat.summarise(records, [], [])
    assert "kimi" in out and "truncated 1" in out
    assert "secret" not in out and "Nanking" not in out


def test_main_refuses_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_TOKEN", raising=False)
    events = tmp_path / "e.json"
    events.write_text(json.dumps(EVENTS))
    assert mat.main([str(events), "--models", "a", "--output-dir", str(tmp_path / "o")]) == 1
