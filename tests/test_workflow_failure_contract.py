"""Regression tests for workflow-level failure reporting."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ingestion.yml"


def test_classification_failure_is_not_silently_reported_as_success():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    classify = workflow.index("- name: Classify and publish")
    evidence = workflow.index("- name: Evidence, cross-check, photos and drafting")
    fail = workflow.index("- name: Fail run if classification failed")
    save_log = workflow.index("- name: Save the log to the data repository")
    queue_next = workflow.index("- name: Queue the next run")

    classify_block = workflow[classify:evidence]
    assert "id: classify" in classify_block
    assert "continue-on-error: true" in classify_block
    assert fail > evidence, "Evidence/research should still run after classification fails"
    assert fail < save_log, "Failure should be raised before the always-run log saver"
    assert save_log < queue_next
    assert "if: steps.classify.outcome == 'failure'" in workflow[fail:save_log]
    assert 'exit 1' in workflow[fail:save_log]
    assert "if: success() && vars.PIPELINE_ON_ACTIONS == 'on'" in workflow[queue_next:]
