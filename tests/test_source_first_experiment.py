import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_first_experiment as source_first


def packet():
    return {
        "event_question": "What happened during the 1841 landing and what did the records establish?",
        "sources": [{
            "source_id": "hk-yearbook-2021",
            "title": "Hong Kong Yearbook 2021, Chapter 22",
            "institution": "Hong Kong Government",
            "source_date": "2021",
            "url": "https://www.yearbook.gov.hk/2021/en/pdf/E22.pdf",
            "source_type": "official_retrospective",
            "locator": "Chapter 22, printed p. 322, lines 122-126",
            "language": "en",
            "inspection_status": "inspected",
            "rights_status": "approved_for_processing",
            "creator_perspective": "Hong Kong government retrospective account",
            "passage": "On 26 January, a naval landing party hoisted the British flag at Possession Point and the island was formally occupied.",
        }],
    }


def valid_result():
    return {
        "record_statements": [{
            "statement_id": "S1",
            "source_id": "hk-yearbook-2021",
            "statement": "The Yearbook retrospectively states that the island was formally occupied on 26 January.",
            "source_excerpt": "the island was formally occupied",
            "locator": "Chapter 22, printed p. 322, lines 122-126",
            "statement_kind": "retrospective_summary",
        }],
        "candidate_claims": [{
            "claim_id": "C1",
            "text": "The Yearbook states that Hong Kong Island was formally occupied on 26 January 1841.",
            "claim_type": "date",
            "source_statement_ids": ["S1"],
            "status": "unverified",
        }],
        "perspectives": [{
            "perspective_id": "P1",
            "actor_or_institution": "Hong Kong government retrospective account",
            "documented_position": "The account describes a formal occupation on 26 January.",
            "source_statement_ids": ["S1"],
            "known_limits": "A retrospective account does not establish the Qing court's position.",
        }],
        "gaps": ["Locate a contemporaneous Chinese-side record."],
    }


def test_prompt_contains_source_records_but_not_draft_prose():
    prompt = source_first.build_source_first_prompt(packet())
    assert "INSPECTED SOURCE RECORDS" in prompt
    assert "Do not use outside knowledge" in prompt
    assert "draft_text" not in prompt


def test_source_packet_rejects_old_draft_input():
    value = packet()
    value["draft_text"] = "The old AI paragraph."
    try:
        source_first.validate_source_packet(value)
        assert False, "draft input must fail closed"
    except ValueError as exc:
        assert "must not contain old draft prose" in str(exc)


def test_source_packet_rejects_catalogue_only_and_unreviewed_rights():
    value = packet()
    value["sources"][0]["inspection_status"] = "catalogue_only"
    try:
        source_first.validate_source_packet(value)
        assert False, "catalogue metadata must not be treated as a passage"
    except ValueError as exc:
        assert "not marked inspected" in str(exc)
    value = packet()
    value["sources"][0]["rights_status"] = "review_required"
    try:
        source_first.validate_source_packet(value)
        assert False, "rights review must fail closed"
    except ValueError as exc:
        assert "not passed rights/processing review" in str(exc)


def test_output_requires_exact_passage_excerpt_and_valid_links():
    report = source_first.validate_source_first_output(packet(), valid_result())
    assert report["status"] == "unverified"
    assert report["live_records_modified"] is False
    bad = valid_result()
    bad["record_statements"][0]["source_excerpt"] = "British forces surrendered the island"
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "invented excerpt must fail"
    except ValueError as exc:
        assert "not an exact supplied-source excerpt" in str(exc)


def test_output_cannot_mark_claim_verified_or_emit_narrative():
    bad = valid_result()
    bad["candidate_claims"][0]["status"] = "verified"
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "claims must remain unverified"
    except ValueError as exc:
        assert "must remain unverified" in str(exc)
    bad = valid_result()
    bad["narrative_preview"] = "The British occupied Hong Kong."
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "source-first extraction cannot write a narrative"
    except ValueError as exc:
        assert "cannot output a narrative" in str(exc)


def test_perspective_requires_source_statement_provenance():
    bad = valid_result()
    bad["perspectives"][0]["source_statement_ids"] = ["S999"]
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "unsupported perspective must fail"
    except ValueError as exc:
        assert "link to existing record statements" in str(exc)
