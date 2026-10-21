import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import quota_preflight as qp
from score_extraction_models import ROLE

# Run 48 (PR for the preflight): a review started with OpenRouter's day spent and measured nothing.


class FakePool:
    def __init__(self, models, left=1000, gateway_quota=None):
        self.models = models
        self.routing = {ROLE: list(models)}
        self.left = left
        self.gateway_quota = gateway_quota or {}

    def remaining(self, name, role):
        return self.left.get(name, 0) if isinstance(self.left, dict) else self.left


MODELS = {"OR": {"provider": "openrouter"}, "GW": {"provider": "gateway"}, "G": {"provider": "google"}}
DEAD_OR = {"GW": {"capacity": {"freeNow": 1}, "models": [
    {"model": "x", "rpmSource": "openrouter:docs", "freeAt": "2026-10-21T00:00:00.000Z",
     "freeAtReason": "dead: free daily allowance used (1004/1000)"},
    {"model": "y", "rpmSource": None, "freeAt": None, "freeAtReason": None}]}}
LIVE = {"GW": {"capacity": {"freeNow": 3}, "models": [
    {"model": "x", "rpmSource": "openrouter:docs", "freeAt": None, "freeAtReason": None}]}}


def test_openrouter_day_spent_stops_the_run():
    problems = qp.check(FakePool(MODELS, gateway_quota=DEAD_OR), ["OR", "GW"], 40)
    assert any(p.startswith("OR:") and "used up" in p for p in problems)
    assert not any(p.startswith("GW:") for p in problems)  # the gateway still has other models


def test_all_models_with_quota_pass():
    assert qp.check(FakePool(MODELS, gateway_quota=LIVE), ["OR", "GW", "G"], 40) == []


def test_too_few_calls_left_or_no_key_stops_that_model():
    problems = qp.check(FakePool(MODELS, left={"OR": 10, "G": 0, "GW": 5}, gateway_quota=LIVE), ["OR", "G"], 40)
    assert any("10 calls left" in p for p in problems) and any(p.startswith("G:") for p in problems)


def test_openrouter_cannot_be_checked_without_gateway_data():
    assert qp.check(FakePool(MODELS), ["OR"], 40)
    assert qp.check(FakePool(MODELS), ["OR"], 40, allow_unchecked=True) == []


def test_gateway_not_free_for_a_long_time_stops_it():
    far = "2999-01-01T00:00:00Z"
    pool = FakePool(MODELS, gateway_quota={"GW": {"capacity": {"freeNow": 0, "nextFreeAt": far}, "models": []}})
    assert any(p.startswith("GW:") for p in qp.check(pool, ["GW"], 40))


def test_unknown_model_is_reported():
    assert qp.check(FakePool(MODELS), ["Nope"], 40) == ["Nope: not in models.json"]


def test_workflow_runs_the_check_before_scoring():
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    assert text.index("quota_preflight.py") < text.index("name: Score models")
