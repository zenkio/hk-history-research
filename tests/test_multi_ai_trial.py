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
    assert records == [] and failures[0]["error"] == "quota_exhausted" and len(failures) == 2  # a, then b; then stop

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


def test_summary_counts_failures_by_error_so_a_failed_run_can_be_diagnosed():
    out = mat.summarise([], [], [{"event": "e1", "model": "a", "error": "400 bad_request"},
                                  {"event": "e2", "model": "a", "error": "400 bad_request"}])
    assert "failure x2: 400 bad_request" in out


def test_limit_takes_only_the_first_events(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_TOKEN", "t")
    seen = []
    monkeypatch.setattr(mat, "post_gateway", lambda body, token, key: seen.append(key) or answer("m"))
    monkeypatch.setattr(mat.time, "sleep", lambda s: None)
    events = tmp_path / "e.json"
    events.write_text(json.dumps(EVENTS))
    assert mat.main([str(events), "--models", "m", "--output-dir", str(tmp_path / "o"), "--limit", "1"]) == 0
    assert len(seen) == 1


def test_auto_entries_let_the_gateway_choose_but_exclude_models_that_already_answered():
    bodies = []
    names = iter(["alpha", "beta", "gamma"])

    def post(body, key):
        bodies.append(body["options"])
        return answer(next(names))

    records, _, failures = mat.run_trial(EVENTS[:1], ["auto1", "auto2", "auto3"], 1, post, sleep=lambda s: None)
    assert not failures and len(records) == 3
    assert all("models" not in o for o in bodies)
    assert [o["exclude"] for o in bodies] == [[], ["alpha-id"], ["alpha-id", "beta-id"]]
    assert [r["answered_model"] for r in records] == ["alpha-id", "beta-id", "gamma-id"]


def test_list_models_prints_and_saves_the_gateway_list_without_events(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AI_GATEWAY_TOKEN", "t")
    monkeypatch.setattr(mat, "list_models", lambda token: {"models": [{"id": "m1", "free": True}]})
    assert mat.main(["--list-models", "--output-dir", str(tmp_path)]) == 0
    assert '"m1"' in capsys.readouterr().out
    assert json.loads((tmp_path / "models.json").read_text())["models"][0]["id"] == "m1"


def test_one_model_out_of_quota_is_skipped_and_the_others_go_on():
    # the first real run stopped after one answer because gemma-4-31b had no quota left (PR for this fix)
    def post(body, key):
        model = body["options"]["models"][0]
        if model == "a":
            raise mat.QuotaExhausted("quota_exhausted")
        return answer(model)

    records, repeat, failures = mat.run_trial(EVENTS, ["a", "b"], 1, post, repeat_event="e1", repeats=2, sleep=lambda s: None)
    assert [r["asked_model"] for r in records] == ["b", "b"]
    assert len(failures) == 1 and repeat == [{"model": "b", "calls": 2, "distinct_answers": 1}]


def test_a_short_rest_is_waited_out_once_and_the_model_is_not_given_up():
    # the 2026-10-29 run gave up on every model after one minute limit ("free again at ...")
    from datetime import datetime, timezone
    now = datetime(2026, 10, 29, 0, 20, 0, tzinfo=timezone.utc)
    assert mat.rest_seconds("is free again at 2026-10-29T00:20:14.389Z (x)", now) == 14.389
    assert mat.rest_seconds("no time here", now) is None
    calls, slept = [], []

    def post(body, key):
        calls.append(key)
        if len(calls) == 1:
            raise mat.QuotaExhausted("quota_exhausted is free again at 2999-01-01T00:00:00Z")
        return answer("a")

    # far in the future: longer than the cap, so it is given up at once (no endless wait)
    records, _, failures = mat.run_trial(EVENTS[:1], ["a"], 1, post, sleep=slept.append)
    assert records == [] and len(failures) == 1 and len(calls) == 1


def test_a_rest_that_ends_soon_is_waited_for_and_the_call_retried():
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    calls, slept = [], []

    def post(body, key):
        calls.append(key)
        if len(calls) == 1:
            raise mat.QuotaExhausted(f"quota_exhausted first is free again at {soon}")
        return answer("a")

    records, _, failures = mat.run_trial(EVENTS[:1], ["a"], 1, post, sleep=slept.append)
    assert len(records) == 1 and not failures and len(calls) == 2
    assert any(25 < s < 40 for s in slept)  # it waited for the rest to end


def test_a_model_with_a_short_rest_is_tried_again_for_the_next_event():
    # run 15 (2026-10-29): nemotron and gemma were given up for good after one minute limit
    calls = []

    def post(body, key):
        calls.append(body["options"]["models"][0])
        if len(calls) == 1:
            raise mat.QuotaExhausted("quota_exhausted first is free again at 2999-01-01T00:00:00Z")
        return answer("a")

    records, _, failures = mat.run_trial(EVENTS, ["a"], 1, post, sleep=lambda s: None)
    assert len(records) == 1 and len(failures) == 1 and calls == ["a", "a"]  # event 2 still asked
