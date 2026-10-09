"""Regression tests for persistent workflow partial-failure state."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mark_pipeline_failure as marker


def test_failed_actions_stage_updates_seed_plan_and_preserves_worker_failures(tmp_path):
    plan_path = tmp_path / "seed_plan.json"
    original = {
        "events": [],
        "last_run": {
            "started_at": "2026-10-09T08:00:00",
            "status": "success",
            "failures": [{"stage": "research", "error": "retrieval timeout"}],
        },
    }
    plan_path.write_text(json.dumps(original), encoding="utf-8")

    count = marker.mark_plan_failure(
        plan_path,
        "fetch_sources=success,repair=success,classify=failure,seed=success,save_log=success",
        now="2026-10-09T08:30:00Z",
    )

    updated = json.loads(plan_path.read_text(encoding="utf-8"))
    assert count == 1
    assert updated["last_run"]["status"] == "partial_failure"
    assert updated["last_run"]["finished_at"] == "2026-10-09T08:30:00Z"
    assert updated["last_run"]["started_at"] == original["last_run"]["started_at"]
    assert updated["last_run"]["failures"][0] == {"stage": "research", "error": "retrieval timeout"}
    assert updated["last_run"]["failures"][1] == {
        "stage": "classify", "error": "GitHub Actions step outcome: failure"
    }


def test_successful_actions_outcomes_do_not_modify_seed_plan(tmp_path):
    plan_path = tmp_path / "seed_plan.json"
    original = {"last_run": {"status": "success", "failures": []}}
    plan_path.write_text(json.dumps(original), encoding="utf-8")

    assert marker.mark_plan_failure(plan_path, "classify=success,seed=success") == 0
    assert json.loads(plan_path.read_text(encoding="utf-8")) == original
