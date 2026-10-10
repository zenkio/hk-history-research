import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atomic_claims import build_claim_records
from validate_preflight_outputs import EXPECTED, build_manifest, validate_file


def valid_record(page):
    return build_claim_records(
        [{
            "text": "A grounded historical claim.",
            "source_excerpt": "A grounded historical claim.",
            "claim_type": "action",
            "importance": "core",
        }],
        event_id="event:test",
        source_page=f"content/01_Timeline/{page}",
        model="test-model",
        prompt_version=6,
        created_at="2026-10-10T00:00:00Z",
    )[0]


def prepare_source(tmp_path, page, prose="A grounded historical claim."):
    timeline_root = tmp_path / "timeline"
    source = timeline_root / page
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        f'---\ntitle: "Test event"\ndate: 1842\n---\n{prose}\n',
        encoding="utf-8",
    )
    return timeline_root


def test_validator_accepts_nonempty_schema_valid_unverified_records(tmp_path):
    page = EXPECTED["mpf"]
    timeline_root = prepare_source(tmp_path, page)
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(valid_record(page)) + "\n", encoding="utf-8")

    result = validate_file(output, page, timeline_root)

    assert result["status"] == "success"
    assert result["claim_count"] == 1
    assert len(result["sha256"]) == 64


def test_validator_rejects_empty_output(tmp_path):
    output = tmp_path / "mpf.jsonl"
    output.write_text("", encoding="utf-8")

    result = validate_file(output, EXPECTED["mpf"], tmp_path / "timeline")

    assert result["status"] == "failed"
    assert result["reason"] == "output_empty"


def test_validator_rejects_supported_claim_status(tmp_path):
    page = EXPECTED["mpf"]
    timeline_root = prepare_source(tmp_path, page)
    record = valid_record(page)
    record["status"] = "supported"
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = validate_file(output, page, timeline_root)

    assert result["status"] == "failed"
    assert result["reason"] == "claim_not_unverified"


def test_validator_rejects_wrong_source_page_and_duplicate_ids(tmp_path):
    page = EXPECTED["mpf"]
    timeline_root = prepare_source(tmp_path, page)
    record = valid_record(page)
    record["provenance"]["source_page"] = "content/01_Timeline/wrong.md"
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert validate_file(output, page, timeline_root)["reason"] == "source_page_mismatch"

    record["provenance"]["source_page"] = f"content/01_Timeline/{page}"
    output.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
    assert validate_file(output, page, timeline_root)["reason"] == "duplicate_record_ids"


def test_validator_rejects_excerpt_not_present_in_source(tmp_path):
    page = EXPECTED["mpf"]
    timeline_root = prepare_source(tmp_path, page, prose="Different source sentence.")
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(valid_record(page)) + "\n", encoding="utf-8")

    result = validate_file(output, page, timeline_root)

    assert result["status"] == "failed"
    assert result["reason"] == "source_excerpt_not_grounded"


def test_manifest_fails_closed_for_missing_pages_and_never_approves_publication(tmp_path):
    manifest = build_manifest(tmp_path, tmp_path / "timeline")

    assert len(manifest["files"]) == 4
    assert len(manifest["failures"]) == 4
    assert manifest["acceptance"]["bulk_extraction_approved"] is False
    assert manifest["acceptance"]["publication_approved"] is False
    assert manifest["acceptance"]["live_records_modified"] is False


def test_validator_rejects_claims_over_35_words(tmp_path):
    page = EXPECTED["mpf"]
    timeline_root = prepare_source(tmp_path, page)
    record = valid_record(page)
    record["text"] = " ".join(["word"] * 36)
    output = tmp_path / "mpf.jsonl"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = validate_file(output, page, timeline_root)

    assert result["status"] == "failed"
    assert result["reason"] == "claim_too_long"
