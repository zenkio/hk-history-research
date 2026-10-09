import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate_claim_records as migration
import research_record_store as store


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_store_ids_match_migration_ids(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    event_id = store.event_id_for_relative_path("05-opium-war/1841-example.md")
    assert event_id == migration.event_id_for(page, timeline)
    text = "A claim to verify."
    assert store.claim_id_for(event_id, text) == "claim:" + event_id.removeprefix("event:") + "-" + __import__("hashlib").sha256(text.casefold().encode()).hexdigest()[:10]


def test_record_store_persists_and_then_supersedes_claim_evidence(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    records = tmp_path / "records"
    kept = [{
        "source": "Internet Archive",
        "kind": "contemporary publication",
        "grade": "A",
        "year": 1841,
        "title": "Example contemporary publication",
        "url": "https://archive.org/details/example-book",
        "cite": "Example publication",
        "note": "Public-domain publication.",
        "passage": "The inspected text explicitly records the event in Hong Kong in 1841.",
        "passage_status": "inspectable_text",
        "relation": "supports",
        "claims": [1],
        "why": "The inspected passage states the event and date.",
    }]

    first = store.persist_page_judgement(
        page, timeline, "Example event", "1841", ["The event occurred in 1841."],
        kept, "test-model", 7, records_dir=records,
    )
    assert first == {"event_id": "event:05-opium-war-1841-example", "claims": 2, "sources": 1, "evidence": 1, "judgements": 2}
    claims = read_jsonl(records / "claims.jsonl")
    event_claim = next(c for c in claims if c["text"] == "Example event took place in Hong Kong (1841)")
    assert event_claim["status"] == "supported"
    assert event_claim["is_current"] is True
    evidence = read_jsonl(records / "evidence.jsonl")
    assert evidence[0]["passage_status"] == "inspectable"
    assert evidence[0]["is_current"] is True
    assert len(read_jsonl(records / "judgements.jsonl")) == 2

    second = store.persist_page_judgement(
        page, timeline, "Example event", "1841", ["The event occurred in 1841."],
        [], None, 7, records_dir=records,
    )
    claims = read_jsonl(records / "claims.jsonl")
    event_claim = next(c for c in claims if c["text"] == "Example event took place in Hong Kong (1841)")
    assert event_claim["status"] == "unverified"
    evidence = read_jsonl(records / "evidence.jsonl")
    assert evidence[0]["is_current"] is False
    assert evidence[0]["superseded_at"]
    assert len(read_jsonl(records / "judgements.jsonl")) == 4
    assert second["evidence"] == 0


def test_conflicting_inspectable_passages_leave_core_claim_partial(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    records = tmp_path / "records"
    candidates = [
        {
            "source": "Internet Archive", "kind": "contemporary publication", "year": 1841,
            "title": "Contemporary account", "url": "https://archive.org/details/account-a",
            "passage": "The inspected text explicitly states that the event occurred in 1841.",
            "passage_status": "inspectable_text", "relation": "supports", "claims": [1],
            "why": "Directly supports the event date.",
        },
        {
            "source": "Internet Archive", "kind": "contemporary publication", "year": 1841,
            "title": "Contrary contemporary account", "url": "https://archive.org/details/account-b",
            "passage": "The inspected text explicitly states that the event did not occur in 1841.",
            "passage_status": "inspectable_text", "relation": "contradicts", "claims": [1],
            "why": "Directly contradicts the event date.",
        },
    ]
    store.persist_page_judgement(
        page, timeline, "Example event", "1841", [], candidates, "test-model", 7,
        records_dir=records,
    )
    claims = read_jsonl(records / "claims.jsonl")
    event_claim = next(c for c in claims if c["text"] == "Example event took place in Hong Kong (1841)")
    assert event_claim["status"] == "partial"
    judgements = read_jsonl(records / "judgements.jsonl")
    event_judgement = next(j for j in judgements if j["claim_id"] == event_claim["id"])
    assert event_judgement["verdict"] == "partial"
    assert len(event_judgement["evidence_ids"]) == 2


def test_date_evidence_does_not_automatically_support_location_claim(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    records = tmp_path / "records"
    store.persist_page_judgement(
        page, timeline, "Example event", "1841",
        ["The event occurred in 1841.", "The event occurred in Hong Kong."],
        [{
            "source": "Internet Archive", "kind": "contemporary publication", "year": 1841,
            "title": "Contemporary account", "url": "https://archive.org/details/date-only",
            "passage": "The inspected text explicitly states that the event occurred in 1841.",
            "passage_status": "inspectable_text", "relation": "supports", "claims": [2],
            "why": "The passage establishes the date only.",
        }],
        "test-model", 7, records_dir=records,
    )
    claims = read_jsonl(records / "claims.jsonl")
    date_claim = next(c for c in claims if c["text"] == "The event occurred in 1841.")
    location_claim = next(c for c in claims if c["text"] == "The event occurred in Hong Kong.")
    assert date_claim["status"] == "supported"
    assert location_claim["status"] == "unverified"
