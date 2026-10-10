import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_health as health


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def claim_record(updated_at, status="unverified"):
    return {
        "record_type": "claim",
        "schema_version": 1,
        "id": "claim:1841-date",
        "event_id": "event:1841-example",
        "text": "The event occurred in 1841.",
        "claim_type": "date",
        "status": status,
        "importance": "core",
        "created_from": "migration",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": updated_at,
        "provenance": {"source_page": "content/01_Timeline/1841-example.md"},
    }


def evidence_record(status="metadata_only"):
    return {
        "record_type": "evidence",
        "schema_version": 1,
        "evidence_id": "evidence:catalogue-1",
        "source_id": "source:catalogue-1",
        "claim_id": "claim:1841-date",
        "relation": "background",
        "passage_status": status,
        "passage": None,
        "locator": None,
        "source_date": None,
        "url": "https://example.org/catalogue/1",
        "retrieved_at": "2026-10-01T00:00:00Z",
        "retrieval_notes": "Catalogue metadata only.",
    }


def test_report_flags_unverified_claims_and_metadata_only_evidence(tmp_path):
    (tmp_path / "claims.jsonl").write_text(
        json.dumps(claim_record("2026-08-01T00:00:00Z")) + "\n", encoding="utf-8"
    )
    write_jsonl(tmp_path / "sources.jsonl", [{
        "record_type": "source",
        "schema_version": 1,
        "source_id": "source:catalogue-1",
        "title": "Example archive catalogue",
        "institution": "Example archive",
        "event_ids": ["event:1841-example"],
        "source_type": "archive_record",
        "authority_level": "discovery_only",
        "coverage": None,
        "language": "und",
        "stable_url": "https://example.org/catalogue/1",
        "catalogue_reference": None,
        "retrieval_method": "api",
        "publication_date": None,
        "discovered_at": "2026-10-01T00:00:00Z",
        "rights_notes": "Metadata only.",
    }])
    write_jsonl(tmp_path / "evidence.jsonl", [evidence_record()])
    write_jsonl(tmp_path / "judgements.jsonl", [])
    write_jsonl(tmp_path / "claim-extraction-queue.jsonl", [])

    report = health.build_report(tmp_path, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert report["core_claims_unresolved"] == 1
    assert report["claims_without_evidence"] == 0
    assert report["claims_without_inspectable_passage"] == 1
    assert report["claims_without_judgement"] == 1
    assert report["stale_unverified_claims"] == 1
    assert report["metadata_only_evidence"] == 1
    assert report["discovery_only_sources"] == 1
    assert report["validation_errors"] == []


def test_strict_report_fails_for_incomplete_core_claims(tmp_path, capsys):
    for filename in health.FILES.values():
        (tmp_path / filename).write_text("", encoding="utf-8")
    (tmp_path / "claims.jsonl").write_text(
        json.dumps(claim_record("2026-10-01T00:00:00Z")) + "\n", encoding="utf-8"
    )
    assert health.main(["--records-dir", str(tmp_path), "--strict"]) == 1
    assert "Unresolved core claims: 1" in capsys.readouterr().out


def test_report_identifies_invalid_json_lines(tmp_path):
    for filename in health.FILES.values():
        (tmp_path / filename).write_text("", encoding="utf-8")
    (tmp_path / "claims.jsonl").write_text("{not json}\n", encoding="utf-8")
    report = health.build_report(tmp_path)
    assert len(report["validation_errors"]) == 1
    assert "invalid JSON" in report["validation_errors"][0]


def test_contradicted_core_claim_remains_unresolved(tmp_path):
    for filename in health.FILES.values():
        (tmp_path / filename).write_text("", encoding="utf-8")
    write_jsonl(tmp_path / "claims.jsonl", [claim_record("2026-10-01T00:00:00Z", "contradicted")])
    report = health.build_report(tmp_path)
    assert report["core_claims_unresolved"] == 1



def test_report_distinguishes_claims_without_search_state(tmp_path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    for filename in health.FILES.values():
        (records_dir / filename).write_text("", encoding="utf-8")
    first = claim_record("2026-10-01T00:00:00Z")
    first["provenance"]["source_page"] = "content/01_Timeline/era/a.md"
    second = dict(first)
    second["id"] = "claim:1842-date"
    second["event_id"] = "event:1842-example"
    second["provenance"] = {"source_page": "content/01_Timeline/era/b.md"}
    write_jsonl(records_dir / "claims.jsonl", [first, second])

    timeline = tmp_path / "content" / "01_Timeline" / "era"
    timeline.mkdir(parents=True)
    (timeline / "a.md").write_text("# A\n", encoding="utf-8")
    (timeline / "b.md").write_text("# B\n", encoding="utf-8")
    state_path = tmp_path / "evidence.json"
    state_path.write_text(json.dumps({"era/a.md": "B"}), encoding="utf-8")

    report = health.build_report(
        records_dir,
        evidence_state_path=state_path,
        content_root=tmp_path / "content" / "01_Timeline",
    )
    assert report["claims_without_search_state"] == 1
    assert report["claims_without_source_page"] == 0
    assert report["pages_without_search_state"] == 1
    assert report["timeline_pages_total"] == 2
    assert report["evidence_state_pages"] == 1
