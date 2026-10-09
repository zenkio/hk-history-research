import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publication_gate as gate


def published_page(*, confidence="reviewed", verification_status="verified",
                   claim_status="supported", publication_status="published", evidence_relation="supports"):
    return f"""---
title: "Example event"
confidence: {confidence}
publication_status: {publication_status}
verification_status: {verification_status}
claims:
  - id: claim:example-date
    text: "The event occurred in 1841."
    importance: core
    status: {claim_status}
    evidence:
      - https://example.org/archive-record
        relation: {evidence_relation}
        passage_status: inspectable
        passage: "The contemporary archive record explicitly describes the event and its date in the official register."
---

## Evidence

- [Archive record](https://example.org/archive-record)
"""



def write_structured_records(records_dir, *, status="supported", relation="supports"):
    passage = "The contemporary archive record explicitly describes the event and its date in the official register."
    claim_status = status
    verdict = status
    (records_dir / "claims.jsonl").write_text(json.dumps({
        "record_type": "claim", "schema_version": 1,
        "id": "claim:example-date", "event_id": "event:example",
        "text": "The event occurred in 1841.", "claim_type": "date",
        "status": claim_status, "importance": "core", "created_from": "manual",
        "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z",
        "is_current": True, "superseded_at": None, "provenance": {"source_page": "example.md"},
    }) + "\n", encoding="utf-8")
    (records_dir / "sources.jsonl").write_text(json.dumps({
        "record_type": "source", "schema_version": 1, "source_id": "source:example",
        "title": "Example archive record", "institution": "Example archive",
        "event_ids": ["event:example"], "source_type": "archive_record",
        "authority_level": "institutional", "coverage": None, "language": "en",
        "stable_url": "https://example.org/archive-record", "catalogue_reference": "EX-1",
        "retrieval_method": "manual", "publication_date": "1841",
        "discovered_at": "2026-10-09T00:00:00Z", "rights_notes": "Test fixture.",
    }) + "\n", encoding="utf-8")
    (records_dir / "evidence.jsonl").write_text(json.dumps({
        "record_type": "evidence", "schema_version": 1,
        "claim_id": "claim:example-date", "evidence_id": "evidence:example",
        "source_id": "source:example", "relation": relation,
        "passage_status": "inspectable", "passage": passage,
        "url": "https://example.org/archive-record", "retrieved_at": "2026-10-09T00:00:00Z",
        "is_current": True, "superseded_at": None, "locator": "page 1",
        "source_date": "1841", "retrieval_notes": "Inspected source passage.",
    }) + "\n", encoding="utf-8")
    (records_dir / "judgements.jsonl").write_text(json.dumps({
        "record_type": "judgement", "schema_version": 1,
        "judgement_id": "judgement:example", "claim_id": "claim:example-date",
        "evidence_ids": ["evidence:example"], "verdict": verdict,
        "rationale": "The inspected passage directly addresses the claim.",
        "uncertainty": "No further uncertainty recorded.", "model": "test-model",
        "prompt_version": "1", "judged_at": "2026-10-09T00:00:00Z",
    }) + "\n", encoding="utf-8")


def test_valid_claim_level_page_can_be_published(tmp_path):
    page = tmp_path / "event.md"
    write_structured_records(tmp_path)
    assert gate.validate_page(page, published_page(), records_dir=tmp_path) == []




def test_fabricated_inline_passage_cannot_replace_the_structured_passage(tmp_path):
    page = tmp_path / "event.md"
    write_structured_records(tmp_path)
    content = published_page().replace(
        "The contemporary archive record explicitly describes the event and its date in the official register.",
        "This fabricated passage is long enough to pass a length-only check but is not the stored excerpt.",
    )
    errors = gate.validate_page(page, content, records_dir=tmp_path)
    assert any("URL, relation and passage must match a current structured inspectable evidence record" in error for error in errors)


def test_current_structured_contradiction_blocks_page_that_omits_it(tmp_path):
    page = tmp_path / "event.md"
    write_structured_records(tmp_path)
    source_path = tmp_path / "sources.jsonl"
    with source_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "record_type": "source", "schema_version": 1,
            "source_id": "source:contradiction", "title": "Contradictory archive record",
            "institution": "Example archive", "event_ids": ["event:example"],
            "source_type": "archive_record", "authority_level": "institutional",
            "coverage": None, "language": "en",
            "stable_url": "https://example.org/contradictory-record",
            "catalogue_reference": "EX-2", "retrieval_method": "manual",
            "publication_date": "1842", "discovered_at": "2026-10-09T00:00:00Z",
            "rights_notes": "Test fixture.",
        }) + chr(10))
    evidence_path = tmp_path / "evidence.jsonl"
    with evidence_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "record_type": "evidence", "schema_version": 1,
            "claim_id": "claim:example-date", "evidence_id": "evidence:contradiction",
            "source_id": "source:contradiction", "relation": "contradicts",
            "passage_status": "inspectable",
            "passage": "A second inspected historical record explicitly gives a different date for this event.",
            "url": "https://example.org/contradictory-record",
            "retrieved_at": "2026-10-09T00:00:00Z", "is_current": True,
            "superseded_at": None, "locator": "page 2", "source_date": "1842",
            "retrieval_notes": "Contradictory inspected passage.",
        }) + chr(10))
    errors = gate.validate_page(page, published_page(), records_dir=tmp_path)
    assert any("current structured contradictory evidence blocks a supported verdict" in error for error in errors)

def test_structured_unverified_claim_cannot_be_published_as_supported(tmp_path):
    page = tmp_path / "event.md"
    write_structured_records(tmp_path, status="unverified", relation="background")
    errors = gate.validate_page(page, published_page(), records_dir=tmp_path)
    assert any("latest structured claim and judgement to be supported" in error for error in errors)



def test_published_claim_without_structured_records_fails_closed(tmp_path):
    page = tmp_path / "event.md"
    errors = gate.validate_page(page, published_page(), records_dir=tmp_path)
    assert any("structured research records missing" in error for error in errors)


def test_ai_draft_cannot_be_published_even_with_evidence_grade(tmp_path):
    page = tmp_path / "event.md"
    errors = gate.validate_page(page, published_page(confidence="ai-draft"))
    assert any("AI-draft pages cannot be published" in error for error in errors)


def test_unresolved_core_claim_blocks_publication(tmp_path):
    page = tmp_path / "event.md"
    errors = gate.validate_page(page, published_page(claim_status="unverified"))
    assert any("status must be supported or explicitly disputed" in error for error in errors)
    assert any("core claim is unresolved" in error for error in errors)


def test_claim_without_direct_evidence_url_blocks_publication(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace("      - https://example.org/archive-record\n", "")
    errors = gate.validate_page(page, content)
    assert any("claim requires at least one direct evidence URL" in error for error in errors)


def test_disputed_claim_requires_disputed_page_status(tmp_path):
    page = tmp_path / "event.md"
    errors = gate.validate_page(page, published_page(claim_status="disputed"))
    assert any("verification_status: disputed" in error for error in errors)


def test_verified_page_must_explicitly_enter_published_layer(tmp_path):
    page = tmp_path / "event.md"
    errors = gate.validate_page(page, published_page(publication_status="research"))
    assert any("requires publication_status: published" in error for error in errors)


def test_legacy_ai_draft_remains_available_as_research_material(tmp_path):
    page = tmp_path / "legacy.md"
    content = """---
title: "Legacy draft"
confidence: ai-draft
tags: ["ai-draft"]
---
> [!warning] AI draft
"""
    assert gate.validate_page(page, content) == []



def test_ai_draft_without_visible_warning_fails_gate(tmp_path):
    page = tmp_path / "legacy.md"
    content = """---
title: "Legacy draft"
confidence: ai-draft
origin: ai
verification_status: unverified
---
Historical narrative without a warning.
"""
    errors = gate.validate_page(page, content)
    assert any("must display the explicit AI draft research warning" in error for error in errors)


def test_published_page_requires_claim_records_and_evidence_section(tmp_path):
    page = tmp_path / "event.md"
    content = """---
title: "Example event"
publication_status: published
verification_status: verified
confidence: reviewed
---
No claim records.
"""
    errors = gate.validate_page(page, content)
    assert any("claim-level records" in error for error in errors)
    assert any("Evidence section" in error for error in errors)


def test_metadata_only_source_cannot_support_publication(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace("passage_status: inspectable", "passage_status: metadata_only")
    errors = gate.validate_page(page, content)
    assert any("requires an inspectable evidence passage tied to its own source URL" in error for error in errors)


def test_short_placeholder_passage_cannot_support_publication(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace(
        "The contemporary archive record explicitly describes the event and its date in the official register.",
        "Source says event happened.",
    )
    errors = gate.validate_page(page, content)
    assert any("at least 30 characters" in error for error in errors)


def test_support_status_cannot_be_backed_only_by_contradictory_evidence(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace("relation: supports", "relation: contradicts")
    errors = gate.validate_page(page, content)
    assert any("supported claims require inspectable evidence with relation supports" in error for error in errors)



def test_contradictory_evidence_blocks_a_supported_claim(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace(
        '        passage: "The contemporary archive record explicitly describes the event and its date in the official register."',
        '        passage: "The contemporary archive record explicitly describes the event and its date in the official register."' + chr(10)
        + '      - https://example.org/contradictory-record' + chr(10)
        + '        relation: contradicts' + chr(10)
        + '        passage_status: inspectable' + chr(10)
        + '        passage: "A second inspected record explicitly gives a different date for this event."',
    )
    errors = gate.validate_page(page, content)
    assert any("contradictory evidence blocks a supported verdict" in error for error in errors)

def test_passage_from_an_unlinked_source_cannot_validate_another_source_url(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace(
        "passage_status: inspectable",
        "passage_status: metadata_only",
    ).replace(
        '        passage: "The contemporary archive record explicitly describes the event and its date in the official register."',
        '        passage: "The contemporary archive record explicitly describes the event and its date in the official register."' + chr(10)
        + '      - title: "Unlinked passage"' + chr(10)
        + '        relation: supports' + chr(10)
        + '        passage_status: inspectable' + chr(10)
        + '        passage: "This unrelated passage is long enough but has no source URL linked to it."',
    )
    errors = gate.validate_page(page, content)
    assert any("requires an inspectable evidence passage tied to its own source URL" in error for error in errors)

def test_disputed_claim_requires_contradictory_evidence(tmp_path):
    page = tmp_path / "event.md"
    content = published_page(claim_status="disputed", verification_status="disputed")
    errors = gate.validate_page(page, content)
    assert any("disputed claims require inspectable evidence with relation contradicts" in error for error in errors)



def test_explicit_dispute_with_current_contradiction_can_be_published(tmp_path):
    page = tmp_path / "event.md"
    write_structured_records(tmp_path, status="partial", relation="contradicts")
    content = published_page(
        claim_status="disputed",
        verification_status="disputed",
        evidence_relation="contradicts",
    )
    assert gate.validate_page(page, content, records_dir=tmp_path) == []


def test_engine_inspectable_record_status_can_pass_gate(tmp_path):
    page = tmp_path / "event.md"
    content = published_page().replace("passage_status: inspectable", "passage_status: inspectable_record")
    write_structured_records(tmp_path)
    assert gate.validate_page(page, content, records_dir=tmp_path) == []
