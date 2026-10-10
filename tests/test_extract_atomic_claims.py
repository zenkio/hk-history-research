import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from extract_atomic_claims import parse_page, run_extraction


def test_parse_page_reads_frontmatter_and_explicit_claims():
    title, date, body, claims = parse_page(
        '---\ntitle: "Harbour trade"\nyear: 1842\n---\n'
        'Narrative about the harbour.\n\n## Claims to verify\n- ❔ The harbour was used for trade.\n'
        '- A new port opened.\n\n## Evidence\nNot a claim.'
    )
    assert title == "Harbour trade"
    assert date == "1842"
    assert "Narrative about the harbour." in body
    assert claims == ["The harbour was used for trade.", "A new port opened."]


def test_single_page_prototype_returns_schema_valid_unverified_records(tmp_path):
    timeline = tmp_path / "content" / "01_Timeline"
    page = timeline / "05-opium-war" / "harbour.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        '---\ntitle: "Harbour trade"\ndate: 1842\n---\n'
        'The harbour was used for trade.\n\n## Claims to verify\n'
        '- The harbour was used for trade.\n',
        encoding="utf-8",
    )

    class FakePool:
        def generate_json(self, role, prompt):
            assert role == "evidence"
            return {"claims": [{
                "text": "The harbour was used for trade.",
                "source_excerpt": "The harbour was used for trade.",
                "claim_type": "action",
                "importance": "core",
            }]}, "fake-model", []

    result = run_extraction(
        page, FakePool(), timeline_root=timeline,
        created_at="2026-10-10T00:00:00Z",
    )
    assert result["page"] == "05-opium-war/harbour.md"
    assert len(result["records"]) == 1
    record = result["records"][0]
    assert record["status"] == "unverified"
    assert record["event_id"] == "event:05-opium-war-harbour"
    assert record["provenance"]["source_page"] == "content/01_Timeline/05-opium-war/harbour.md"
    assert record["id"] == "claim:05-opium-war-harbour-" + __import__("hashlib").sha256(
        "the harbour was used for trade.".encode()
    ).hexdigest()[:10]


def test_single_page_prototype_rejects_page_outside_timeline(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("---\ntitle: Outside\n---\nA draft.", encoding="utf-8")
    with pytest.raises(ValueError, match="inside timeline root"):
        run_extraction(outside, object(), timeline_root=tmp_path / "timeline")


def test_parse_page_excludes_research_sections_from_extraction_prose():
    title, date, prose, claims = parse_page(
        '---\ntitle: "Harbour trade"\ndate: 1842\n---\n'
        'The harbour was used for trade.\n\n'
        '## Claims to verify\n- The harbour served foreign merchants.\n\n'
        '## Evidence\nA catalogue note says the harbour was busy.\n'
        '### Source notes\nMore metadata not part of the original draft.\n\n'
        '## People and places\n- [[02_Entities/Places/hong-kong|Hong Kong]]\n\n'
        '## Wikipedia cross-check\n- The draft omits a precise date.\n\n'
        '## Background\nThe harbour predates the event.\n'
    )
    assert "The harbour was used for trade." in prose
    assert "The harbour predates the event." in prose
    assert "The harbour served foreign merchants." not in prose
    assert "catalogue note" not in prose
    assert "More metadata" not in prose
    assert "Hong Kong" not in prose
    assert "omits a precise date" not in prose
    assert claims == ["The harbour served foreign merchants."]
