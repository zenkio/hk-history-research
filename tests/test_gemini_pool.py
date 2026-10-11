"""Model pool routing and error handling, with fake providers (no Google client, no network)."""
import io
import json
import os

import gemini_pool as gp

OR = {"OpenRouter Large": {"provider": "openrouter"}, "Gemma 4 31B": {"provider": "google"}}
ROUTING = {"evidence": ["OpenRouter Large", "Gemma 4 31B"]}


def gemma_answers(pool):
    pool._call_google = lambda *a, **k: ('{"ok": 1}', [], 10)


def test_rejected_openrouter_key_switches_to_the_backup(make_pool):
    # PR #17 (was #14): the first secret had a leading space and every call got 401.
    p = make_pool(OR, ROUTING, or_keys=[("OPENROUTER_API_KEY", "bad"), ("OPEN_ROUTER_KEY_RESEARCHER", "good")])

    def call(m, prompt):
        if p.or_key != "good":
            raise Exception('401 {"error":{"message":"Missing Authentication header"}}')
        return '{"ok": 1}', [], 10
    p._call_openrouter = call
    assert p._generate("evidence", "x", gp._parse_json, False, None, None)[1] == "OpenRouter Large"
    assert p.or_key_name == "OPEN_ROUTER_KEY_RESEARCHER"


def test_all_keys_rejected_skips_openrouter_for_the_run(make_pool):
    p = make_pool(OR, ROUTING, or_keys=[("OPENROUTER_API_KEY", "bad")])
    p._call_openrouter = lambda m, prompt: (_ for _ in ()).throw(Exception("401 Unauthorized"))
    gemma_answers(p)
    assert p._generate("evidence", "x", gp._parse_json, False, None, None)[1] == "Gemma 4 31B"
    assert "OpenRouter Large" in p.unavailable


def test_openrouter_rate_limit_hands_over_at_once(make_pool):
    # PR #17 (was #15): 38-49 sleeps of 60 s a run left the evidence worker grading 0-3 pages.
    p = make_pool(OR, ROUTING, or_keys=[("OPENROUTER_API_KEY", "k")])
    calls = []

    def limited(m, prompt):
        calls.append(1)
        raise Exception('429 {"error":{"message":"Rate limit exceeded: free-models-per-min"}}')
    p._call_openrouter = limited
    gemma_answers(p)
    assert p._generate("evidence", "x", gp._parse_json, False, None, None)[1] == "Gemma 4 31B"
    assert p._generate("evidence", "x", gp._parse_json, False, None, None)[1] == "Gemma 4 31B"
    assert len(calls) == 1, "a resting model must not be called again"


def test_keys_are_stripped_of_whitespace(monkeypatch, make_pool):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-abc\n")
    monkeypatch.delenv("OPEN_ROUTER_KEY_RESEARCHER", raising=False)
    p = make_pool({}, {})
    p.models = {"OpenRouter Large": {"provider": "openrouter", "display": "OpenRouter Large", "pick": ["zzz"]}}
    p.state = {}
    # Resolving also lists the free models; only the key handling is under test here.
    monkeypatch.setattr(gp.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    p._resolve_openrouter()
    assert p.or_key == "sk-or-abc"


def test_json_replies_are_parsed_from_code_fences():
    assert gp._parse_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}


class FakeResponse:
    def __init__(self, data):
        self.body = json.dumps(data).encode()

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, *a):
        return False


def limit_after_check(monkeypatch, make_pool, answer):
    p = make_pool(OR, ROUTING, or_keys=[("OPENROUTER_API_KEY", "k")])
    entries = [p.models["OpenRouter Large"]]

    def fake(req, timeout=None):
        if isinstance(answer, Exception):
            raise answer
        assert req.full_url.endswith("/key") and req.headers["Authorization"] == "Bearer k"
        return FakeResponse(answer)
    monkeypatch.setattr(gp.urllib.request, "urlopen", fake)
    p._read_openrouter_limit(entries)
    return p.config["providers"]["openrouter"]["rpd"], entries[0]["rpd"]


def test_account_with_credits_gets_1000_openrouter_calls_a_day(monkeypatch, make_pool):
    # 2026-09-28: models.json assumed 50 a day although the owner's account allows 1,000.
    assert limit_after_check(monkeypatch, make_pool, {"data": {"is_free_tier": False}}) == (1000, 1000)


def test_free_tier_account_keeps_50(monkeypatch, make_pool):
    assert limit_after_check(monkeypatch, make_pool, {"data": {"is_free_tier": True}}) == (50, 50)


def test_limit_check_failing_keeps_the_safe_limit(monkeypatch, make_pool):
    assert limit_after_check(monkeypatch, make_pool, OSError("offline"))[0] == 50


def test_real_config_routes_evidence_and_verify_to_the_large_models_first():
    # 2026-09-28 audit: Gemma kept general-topic works as evidence for specific events.
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "scripts", "models.json"), encoding="utf-8"))
    for role in ("evidence", "verify"):
        assert cfg["routing"][role][:2] == ["OpenRouter Large", "OpenRouter Medium"], role
    openrouter_rpm = sum(m["rpm"] for m in cfg["models"] if m.get("provider") == "openrouter")
    assert openrouter_rpm < 20, "OpenRouter's per-minute free limit is shared by the account"


# --- Google unavailable (Google key rejected from 2026-09-30; PR #8) --------------------------------
# Every run kept sending rejected calls: a model list, then each Gemini/Gemma model in turn.

GOOGLE_AND_OR = {"Gemini 3.1 Flash Lite": {"provider": "google"}, "Gemma 4 31B": {"provider": "google"},
                 "OpenRouter Medium": {"provider": "openrouter"}}


def real_pool(monkeypatch, tmp_path, client=None, key=None):
    monkeypatch.setattr(gp, "STATE_FILE", str(tmp_path / "quota_state.json"))
    for name in ("GEMINI_API_KEY",) + gp.OPENROUTER_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    if key:
        monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.setattr(gp.genai, "Client", client or (lambda **k: (_ for _ in ()).throw(AssertionError("Google client made"))))
    return gp.ModelPool()


def test_no_gemini_key_means_no_google_client_and_no_google_models(monkeypatch, tmp_path):
    pool = real_pool(monkeypatch, tmp_path)
    google = {k for k, m in pool.models.items() if m.get("provider", "google") == "google"}
    assert google and google <= pool.unavailable
    assert pool.client is None and pool.google_off == "no GEMINI_API_KEY"
    assert all(pool.remaining(k, "classify") == 0 for k in google)


def test_rejected_model_list_turns_google_off_before_any_model_call(monkeypatch, tmp_path):
    class Rejecting:
        def __init__(self, **k):
            self.models = self

        def list(self):
            raise Exception("401 UNAUTHENTICATED. The bound service account is disabled")
    pool = real_pool(monkeypatch, tmp_path, client=Rejecting, key="dead-key")
    assert pool.google_off.startswith("the key was rejected")
    assert {k for k, m in pool.models.items() if m.get("provider", "google") == "google"} <= pool.unavailable


def test_one_google_refusal_stops_every_google_model_and_openrouter_takes_over(make_pool):
    p = make_pool(GOOGLE_AND_OR, {"classify": list(GOOGLE_AND_OR)})
    p.google_off = None
    google_calls = []

    def refuse(m, *a, **k):
        google_calls.append(m["display"])
        raise Exception("401 UNAUTHENTICATED. {'error': {'code': 401}}")
    p._call_google = refuse
    p._call_openrouter = lambda m, prompt: ('{"ok": 1}', [], 10)
    p.remaining = lambda k, r: 0 if k in p.unavailable else 5
    data, model, _ = p.generate_json("classify", "x")
    assert (data, model) == ({"ok": 1}, "OpenRouter Medium")
    assert google_calls == ["Gemini 3.1 Flash Lite"], "the second Google model is never tried"
    assert {"Gemini 3.1 Flash Lite", "Gemma 4 31B"} <= p.unavailable


def test_real_config_classifies_with_openrouter_when_google_is_unavailable():
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "scripts", "models.json"), encoding="utf-8"))
    providers = {m["display"]: m.get("provider", "google") for m in cfg["models"]}
    for role in ("classify", "video_text", "evidence", "verify"):
        assert any(providers[k] == "openrouter" for k in cfg["routing"][role]), role


def test_seeding_runs_on_openrouter_alone(monkeypatch):
    import seed_history
    for name in ("GEMINI_API_KEY",) + gp.OPENROUTER_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert not seed_history.any_ai_key()
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    assert not seed_history.any_ai_key(), "a blank secret is no key"
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert seed_history.any_ai_key()


# Run 38181951012: no free model matched the comparison model's preferences, so the v2.1
# comparison run had no model. "*" now takes the largest free model left, never an avoided family.
def resolve_with_free(monkeypatch, make_pool, entries, free_ids):
    p = make_pool({}, {}, or_keys=[("OPENROUTER_API_KEY", "k")])
    p.models = {e["display"]: {"provider": "openrouter", **e} for e in entries}
    p.state = {}
    monkeypatch.setattr(p, "_read_openrouter_limit", lambda entries: None)
    data = {"data": [{"id": i, "context_length": 1000 - n} for n, i in enumerate(free_ids)]}
    monkeypatch.setattr(gp.urllib.request, "urlopen", lambda *a, **k: FakeResponse(data))
    p._resolve_openrouter()
    return {name: m["api_id"] for name, m in p.models.items()}


def test_wildcard_pick_takes_largest_free_model_outside_avoided_family(monkeypatch, make_pool):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    ids = resolve_with_free(monkeypatch, make_pool, [
        {"display": "Large", "pick": ["nemotron-3-ultra"]},
        {"display": "Compare", "pick": ["deepseek", "*"], "avoid": ["nemotron"]},
    ], ["nvidia/nemotron-3-ultra:free", "nvidia/nemotron-3-super:free", "acme/big-chat:free"])
    assert ids == {"Large": "nvidia/nemotron-3-ultra:free", "Compare": "acme/big-chat:free"}


def test_avoided_family_is_never_picked_even_by_preference(monkeypatch, make_pool):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    ids = resolve_with_free(monkeypatch, make_pool, [
        {"display": "Compare", "pick": ["super", "*"], "avoid": ["nemotron"]},
    ], ["nvidia/nemotron-3-super:free"])
    assert ids == {"Compare": None}


# Run 38182972425: a free model answered 403 "only available on ..." and the pool dropped the
# account's only OpenRouter key, so every OpenRouter model was off for the run.
GATED = '403 {"error":{"message":"vendor/gated:free is only available on another plan"}}'


def test_openrouter_403_refuses_the_model_not_the_key(make_pool):
    models = {"OpenRouter Large": {"provider": "openrouter", "api_id": "vendor/gated:free"},
              "OpenRouter Medium": {"provider": "openrouter", "api_id": "vendor/ok:free"}}
    p = make_pool(models, {"evidence": ["OpenRouter Large", "OpenRouter Medium"]},
                  or_keys=[("OPENROUTER_API_KEY", "k")])

    def call(m, prompt):
        if m["api_id"] == "vendor/gated:free":
            raise Exception(GATED)
        return '{"ok": 1}', [], 10
    p._call_openrouter = call
    assert p._generate("evidence", "x", gp._parse_json, False, None, None)[1] == "OpenRouter Medium"
    assert p.or_keys == [("OPENROUTER_API_KEY", "k")] and "OpenRouter Large" in p.unavailable


def test_wildcard_entry_moves_to_the_next_free_model_after_a_403(make_pool):
    models = {"OpenRouter Compare": {"provider": "openrouter", "api_id": "vendor/gated:free",
                                     "pick": ["deepseek", "*"], "avoid": ["nemotron"]}}
    p = make_pool(models, {"source_first_compare": ["OpenRouter Compare"]}, or_keys=[("OPENROUTER_API_KEY", "k")])
    p.or_free = ["vendor/gated:free", "nvidia/nemotron-x:free", "acme/open:free"]
    p.or_refused = set()
    used = []

    def call(m, prompt):
        used.append(m["api_id"])
        if m["api_id"] == "vendor/gated:free":
            raise Exception(GATED)
        return '{"ok": 1}', [], 10
    p._call_openrouter = call
    assert p._generate("source_first_compare", "x", gp._parse_json, False, None, None)[1] == "OpenRouter Compare"
    assert used == ["vendor/gated:free", "acme/open:free"]
    assert p.models["OpenRouter Compare"]["api_id"] == "acme/open:free"


# Run 38183882474: the wildcard fell through to preview models; one failed every request with
# 400 "Provider returned error", which ended the run instead of moving to the next free model.
def test_wildcard_moves_on_after_a_provider_error_and_tries_previews_last(make_pool):
    models = {"OpenRouter Compare": {"provider": "openrouter", "api_id": "acme/broken:free",
                                     "pick": ["*"], "avoid": ["nemotron"]}}
    p = make_pool(models, {"source_first_compare": ["OpenRouter Compare"]}, or_keys=[("OPENROUTER_API_KEY", "k")])
    p.or_free = ["acme/broken:free", "acme/x-preview:free", "acme/stable:free"]
    p.or_refused = set()
    used = []

    def call(m, prompt):
        used.append(m["api_id"])
        if m["api_id"] == "acme/broken:free":
            raise Exception('400 {"error":{"message":"Provider returned error","code":400}}')
        return '{"ok": 1}', [], 10
    p._call_openrouter = call
    assert p._generate("source_first_compare", "x", gp._parse_json, False, None, None)[1] == "OpenRouter Compare"
    assert used == ["acme/broken:free", "acme/stable:free"]


def test_a_400_on_a_fixed_model_is_still_a_rejected_request(make_pool):
    p = make_pool(OR, ROUTING, or_keys=[("OPENROUTER_API_KEY", "k")])
    p.or_free, p.or_refused = ["other:free"], set()
    p._call_openrouter = lambda m, prompt: (_ for _ in ()).throw(
        Exception('400 {"error":{"message":"Provider returned error"}}'))
    try:
        p._generate("evidence", "x", gp._parse_json, False, None, None)
    except gp.RequestRejected:
        pass
    else:
        raise AssertionError("a fixed model's 400 must not silently switch models")
