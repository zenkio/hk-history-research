"""Regression tests for the preview-only narrative reconstruction gate."""
import pytest

from reconstruct_narrative import DEFAULT_RECORDS_DIR, build_preview, load_records


EVENT = "event:05-opium-war-1841-example"
CLAIM = "claim:05-opium-war-1841-example-a1"
SOURCE = "source:example-source"
EVIDENCE = "evidence:example-evidence"
JUDGEMENT = "judgement:example-judgement"


def narrative_body(markdown):
    lines = markdown.splitlines()
    active, body = False, []
    for line in lines:
        if line.startswith("## Narrative assembled from supported claims") or line == "## Narrative":
            active = True
            continue
        if active and line.startswith("## "):
            break
        if active:
            body.append(line)
    return "\\n".join(body)


def records():
    return {
        "claims": [{
            "record_type": "claim", "id": CLAIM, "event_id": EVENT,
            "text": "The event occurred in 1841.", "status": "supported",
            "importance": "core", "is_current": True,
        }],
        "sources": [{
            "record_type": "source", "source_id": SOURCE,
            "title": "Contemporary record", "stable_url": "https://example.org/record",
        }],
        "evidence": [{
            "record_type": "evidence", "evidence_id": EVIDENCE, "source_id": SOURCE,
            "claim_id": CLAIM, "relation": "supports", "passage_status": "inspectable",
            "passage": "The inspected passage explicitly records that the event occurred in 1841.",
            "url": "https://example.org/record", "locator": "page 3", "is_current": True,
        }],
        "judgements": [{
            "record_type": "judgement", "judgement_id": JUDGEMENT, "claim_id": CLAIM,
            "evidence_ids": [EVIDENCE], "verdict": "supported", "judged_at": "2026-10-10T00:00:00Z",
        }],
    }


def test_supported_claim_is_assembled_with_traceable_citation_and_excerpt():
    result = build_preview(records(), EVENT)
    assert result["preview_only"] is True
    assert result["core_evidence_gate_passed"] is True
    assert result["claims_included"] == 1
    assert "The event occurred in 1841." in result["markdown"]
    assert "https://example.org/record" in result["markdown"]
    assert "page 3" in result["markdown"]
    assert "inspected passage explicitly records" in result["markdown"]
    assert "NOT PUBLISHED" in result["markdown"]


def test_unresolved_core_claim_blocks_gate_but_preview_discloses_it():
    data = records()
    data["claims"][0]["status"] = "unverified"
    result = build_preview(data, EVENT)
    assert result["core_evidence_gate_passed"] is False
    assert result["claims_included"] == 0
    assert result["unresolved_core_claims"][0]["claim_id"] == CLAIM
    assert "NOT PASSED" in result["markdown"]
    assert "unverified" in result["markdown"]


def test_metadata_only_source_never_enters_narrative():
    data = records()
    data["evidence"][0]["passage_status"] = "metadata_only"
    data["evidence"][0]["passage"] = None
    result = build_preview(data, EVENT)
    assert result["claims_included"] == 0
    assert result["core_evidence_gate_passed"] is False
    assert "The event occurred in 1841." not in narrative_body(result["markdown"])


def test_current_contradiction_blocks_claim_even_if_latest_judgement_says_supported():
    data = records()
    data["evidence"].append({
        "record_type": "evidence", "evidence_id": "evidence:contrary", "source_id": SOURCE,
        "claim_id": CLAIM, "relation": "contradicts", "passage_status": "inspectable",
        "passage": "A current inspected source directly states that the event did not occur in 1841.",
        "url": "https://example.org/contrary", "is_current": True,
    })
    result = build_preview(data, EVENT)
    assert result["claims_included"] == 0
    assert result["core_evidence_gate_passed"] is False
    assert "current inspectable contradictory evidence exists" in result["unresolved_core_claims"][0]["reasons"]


def test_stale_evidence_and_judgement_do_not_qualify():
    data = records()
    data["evidence"][0]["is_current"] = False
    result = build_preview(data, EVENT)
    assert result["claims_included"] == 0
    assert result["core_evidence_gate_passed"] is False


def test_supporting_claim_can_be_previewed_while_unresolved_core_is_flagged():
    data = records()
    extra_id = "claim:05-opium-war-1841-example-b2"
    extra_evidence = "evidence:supporting"
    data["claims"].append({
        "record_type": "claim", "id": extra_id, "event_id": EVENT,
        "text": "The harbour was busy.", "status": "supported",
        "importance": "supporting", "is_current": True,
    })
    data["evidence"].append({
        **data["evidence"][0], "evidence_id": extra_evidence, "claim_id": extra_id,
        "passage": "The inspected passage describes the harbour as busy during this period.",
    })
    data["judgements"].append({
        **data["judgements"][0], "judgement_id": "judgement:supporting",
        "claim_id": extra_id, "evidence_ids": [extra_evidence],
        "judged_at": "2026-10-10T00:01:00Z",
    })
    data["claims"][0]["status"] = "unverified"
    result = build_preview(data, EVENT)
    assert result["claims_included"] == 1
    assert result["core_evidence_gate_passed"] is False
    assert "The harbour was busy." in result["markdown"]
    assert "The event occurred in 1841." not in narrative_body(result["markdown"])


def test_supporting_only_event_cannot_pass_core_gate():
    data = records()
    data["claims"][0]["importance"] = "supporting"
    result = build_preview(data, EVENT)
    assert result["claims_included"] == 1
    assert result["core_evidence_gate_passed"] is False
    assert "No core claims were present" in result["markdown"]



def test_real_corpus_white_paper_preview_keeps_unsupported_core_claim_unresolved():
    if not (DEFAULT_RECORDS_DIR / "claims.jsonl").exists():
        pytest.skip("private research records are only available in the data-repo CI workspace")
    event_id = "event:15-contention-2014-beijing-issues-white-paper-on-hong-kong"
    result = build_preview(load_records(DEFAULT_RECORDS_DIR), event_id)
    unresolved_ids = {item["claim_id"] for item in result["unresolved_core_claims"]}
    assert result["preview_only"] is True
    assert result["core_evidence_gate_passed"] is False
    assert result["claims_included"] == 3
    assert "claim:15-contention-2014-beijing-issues-white-paper-on-hong-kong-067e6e9272" in unresolved_ids
    assert "NOT PUBLISHED" in result["markdown"]


@pytest.mark.parametrize(
    "event_id",
    [
        "event:05-opium-war-1841-formal-british-possession-of-hong-kong-island",
        "event:08-new-territories-1901-assassination-of-yeung-ku-wan",
        "event:08-new-territories-1908-the-tatsu-maru-boycott-and-anti-japanese-movement",
        "event:13-transition-1987-implementation-of-the-mandatory-provident-fund-planning",
    ],
)
def test_real_corpus_risk_cases_remain_preview_only_and_fail_closed(event_id):
    if not (DEFAULT_RECORDS_DIR / "claims.jsonl").exists():
        pytest.skip("private research records are only available in the data-repo CI workspace")
    data = load_records(DEFAULT_RECORDS_DIR)
    assert any(
        row.get("event_id") == event_id
        and row.get("importance") == "core"
        and row.get("is_current", True) is True
        for row in data["claims"]
    ), f"expected a current core claim for {event_id}"

    result = build_preview(data, event_id)
    assert result["preview_only"] is True
    assert result["core_evidence_gate_passed"] is False, event_id
    assert "RESEARCH PREVIEW — NOT PUBLISHED" in result["markdown"]
    assert "NOT PASSED" in result["markdown"]
