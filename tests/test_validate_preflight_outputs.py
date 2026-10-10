import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_preflight_outputs import EXPECTED, build_manifest, validate_file


def valid_record(page):
    return {
        "record_type": "claim",
        "schema_version": 1,
        "id": "claim:test-001",
        "event_id": "event:test",
        "text": "A grounded historical claim.",
        "status": "unverified",
        "provenance": {
            "source_page": f"content/01_Timeline/{page}",
            "source_excerpt": "A grounded historical claim.",
            "model": "test-model",
            "prompt_version": 3,
        },
    }


def test_validator_accepts_nonempty_schema_valid_unverified_records(tmp_path):
    page = EXPECTED["mpf"]
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(valid_record(page)) + "\n", encoding="utf-8")

    result = validate_file(output, page)

    assert result["status"] == "success"
    assert result["claim_count"] == 1
    assert len(result["sha256"]) == 64


def test_validator_rejects_empty_output(tmp_path):
    output = tmp_path / "mpf.jsonl"
    output.write_text("", encoding="utf-8")

    result = validate_file(output, EXPECTED["mpf"])

    assert result["status"] == "failed"
    assert result["reason"] == "output_empty"


def test_validator_rejects_verified_or_published_claim_status(tmp_path):
    page = EXPECTED["mpf"]
    record = valid_record(page)
    record["status"] = "verified"
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = validate_file(output, page)

    assert result["status"] == "failed"
    assert result["reason"] == "claim_not_unverified"


def test_validator_rejects_wrong_source_page_and_duplicate_ids(tmp_path):
    page = EXPECTED["mpf"]
    record = valid_record(page)
    record["provenance"]["source_page"] = "content/01_Timeline/wrong.md"
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert validate_file(output, page)["reason"] == "source_page_mismatch"

    record["provenance"]["source_page"] = f"content/01_Timeline/{page}"
    output.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
    assert validate_file(output, page)["reason"] == "duplicate_record_ids"


def test_manifest_fails_closed_for_missing_pages_and_never_approves_publication(tmp_path):
    manifest = build_manifest(tmp_path)

    assert len(manifest["files"]) == 4
    assert len(manifest["failures"]) == 4
    assert manifest["acceptance"]["bulk_extraction_approved"] is False
    assert manifest["acceptance"]["publication_approved"] is False
    assert manifest["acceptance"]["live_records_modified"] is False



def test_validator_rejects_claims_over_35_words(tmp_path):
    page = EXPECTED["mpf"]
    record = valid_record(page)
    record["text"] = " ".join(["word"] * 36)
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = validate_file(output, page)

    assert result["status"] == "failed"
    assert result["reason"] == "claim_too_long"
