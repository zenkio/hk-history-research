import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publication_gate as gate


def published_page(*, confidence="reviewed", verification_status="verified",
                   claim_status="supported", publication_status="published"):
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
---

## Evidence

- [Archive record](https://example.org/archive-record)
"""


def test_valid_claim_level_page_can_be_published(tmp_path):
    page = tmp_path / "event.md"
    assert gate.validate_page(page, published_page()) == []


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
