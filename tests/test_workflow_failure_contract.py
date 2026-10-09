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
    persist_failure = workflow.index("- name: Record partial-failure state")
    marker = workflow.index("- name: Where to read the details")

    classify_block = workflow[classify:evidence]
    assert "id: classify" in classify_block
    assert "continue-on-error: true" in classify_block
    assert fail > evidence, "Evidence/research should still run after classification fails"
    assert fail < save_log, "Failure should be raised before the always-run log saver"
    assert save_log < persist_failure < marker
    assert "if: steps.classify.outcome == 'failure'" in workflow[fail:save_log]
    assert 'exit 1' in workflow[fail:save_log]
    failure_block = workflow[persist_failure:marker]
    assert "if: failure()" in failure_block
    assert "mark_pipeline_failure.py --outcomes" in failure_block
    assert "steps.classify.outcome" in failure_block
    assert "git push origin main" in failure_block
    assert "Queue the next run" not in workflow
    assert "gh workflow run ingestion.yml" not in workflow
