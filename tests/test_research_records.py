import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_records as records


def claim_record(**overrides):
    record = {
        "record_type": "claim",
        "schema_version": 1,
        "id": "claim:1841-british-landing-date",
        "event_id": "event:first-opium-war",
        "text": "British forces landed on Hong Kong Island in January 1841.",
        "claim_type": "date",
        "status": "unverified",
        "importance": "core",
        "created_from": "migration",
        "created_at": "2026-10-09T10:00:00Z",
        "updated_at": "2026-10-09T10:00:00Z",
        "provenance": {"source_page": "01_Timeline/example.md"},
    }
    record.update(overrides)
    return record


def test_valid_claim_record_passes_schema():
    assert records.validate_record(claim_record()) == []


def test_claim_requires_stable_ids_and_explicit_verification_state():
    record = claim_record(id="1841-date", status="probably true")
    errors = records.validate_record(record)
    assert any("id" in error for error in errors)
    assert any("status" in error for error in errors)


def test_inspectable_evidence_requires_actual_passage():
    record = {
        "record_type": "evidence",
        "schema_version": 1,
        "evidence_id": "evidence:archive-passage-1",
        "source_id": "source:archive-catalogue-1",
        "claim_id": "claim:1841-british-landing-date",
        "relation": "supports",
        "passage_status": "inspectable",
        "retrieved_at": "2026-10-09T10:00:00Z",
    }
    errors = records.validate_record(record)
    assert any("passage" in error for error in errors)


def test_metadata_only_evidence_may_not_claim_an_inspected_passage():
    record = {
        "record_type": "evidence",
        "schema_version": 1,
        "evidence_id": "evidence:archive-catalogue-1",
        "source_id": "source:archive-catalogue-1",
        "claim_id": "claim:1841-british-landing-date",
        "relation": "background",
        "passage_status": "metadata_only",
        "passage": None,
        "retrieved_at": "2026-10-09T10:00:00Z",
    }
    assert records.validate_record(record) == []


def test_judgement_can_express_contradiction_without_promoting_claim():
    record = {
        "record_type": "judgement",
        "schema_version": 1,
        "judgement_id": "judgement:1841-date-review-1",
        "claim_id": "claim:1841-british-landing-date",
        "evidence_ids": ["evidence:archive-passage-1"],
        "verdict": "contradicted",
        "rationale": "The inspected record gives a different date.",
        "uncertainty": "The record may refer to a different landing party.",
        "model": "test-model",
        "prompt_version": "1",
        "judged_at": "2026-10-09T10:00:00Z",
    }
    assert records.validate_record(record) == []
