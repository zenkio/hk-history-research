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
    event_claim = next(c for c in claims if c["text"] == "Example event occurred in 1841.")
    assert event_claim["status"] == "supported"
    assert event_claim["claim_type"] == "date"
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
    event_claim = next(c for c in claims if c["text"] == "Example event occurred in 1841.")
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
    event_claim = next(c for c in claims if c["text"] == "Example event occurred in 1841.")
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


def test_markdown_claim_normalisation_keeps_migration_and_store_ids_aligned():
    event_id = "event:05-opium-war-1841-example"
    raw = "**The event** happened [in January](https://example.org/date) 1841."
    normalized = "The event happened in January 1841."
    assert store.normalize_claim_text(raw) == normalized
    assert store.claim_id_for(event_id, raw) == store.claim_id_for(event_id, normalized)


def test_source_metadata_preserves_registry_family_and_rights_metadata():
    source = store._source_metadata({
        "source": "UK National Archives Discovery",
        "institution": "The National Archives (UK)",
        "source_type": "archive_record",
        "authority_level": "primary",
        "language": "en",
        "source_coverage": "UK-held archival catalogue records relating to Hong Kong",
        "retrieval_method": "api",
        "rights_notes": "Catalogue metadata only; not an inspected passage.",
        "title": "CO 129 record",
        "url": "https://discovery.nationalarchives.gov.uk/details/r/123",
        "passage_status": "metadata_only",
    }, "event:example", "2026-10-10T00:00:00Z")
    assert source["source_type"] == "archive_record"
    assert source["authority_level"] == "primary"
    assert source["institution"] == "The National Archives (UK)"
    assert source["language"] == "en"
    assert source["coverage"] == "UK-held archival catalogue records relating to Hong Kong"
    assert source["retrieval_method"] == "api"
    assert source["rights_notes"] == "Catalogue metadata only; not an inspected passage."


def test_registry_metadata_for_scholarship_is_not_downgraded_to_unknown():
    source = store._source_metadata({
        "source": "OpenAlex",
        "institution": "OpenAlex",
        "source_type": "academic_work",
        "authority_level": "scholarly",
        "language": "en",
        "source_coverage": "Scholarly abstracts",
        "retrieval_method": "api",
        "rights_notes": "Abstract is not a substitute for full text.",
        "title": "Academic abstract",
        "url": "https://doi.org/10.1000/example",
        "passage_status": "inspectable_abstract",
    }, "event:example", "2026-10-10T00:00:00Z")
    assert source["source_type"] == "academic_work"
    assert source["authority_level"] == "scholarly"
    assert source["language"] == "en"
    assert source["coverage"] == "Scholarly abstracts"


def test_manual_evidence_survives_automatic_rejudgement_when_claim_is_unchanged(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    records = tmp_path / "records"
    candidate = {
        "source": "Manual official-source audit",
        "title": "Official record",
        "url": "https://example.org/manual-evidence",
        "passage": "The official source states the mint was constructed in 1864.",
        "passage_status": "inspectable_text",
        "relation": "contradicts",
        "claims": [1],
        "why": "Manual source audit; exact passage inspected.",
    }
    store.persist_page_judgement(
        page, timeline, "Example event", "1846", [], [candidate],
        None, "manual-source-audit-2026-10-10", records_dir=records,
    )

    store.persist_page_judgement(
        page, timeline, "Example event", "1846", [], [],
        "test-model", 12, records_dir=records,
    )

    claim = next(
        row for row in read_jsonl(records / "claims.jsonl")
        if row["text"] == "Example event occurred in 1846."
    )
    evidence = read_jsonl(records / "evidence.jsonl")
    current_evidence = [row for row in evidence if row.get("is_current")]
    assert claim["status"] == "contradicted"
    assert len(current_evidence) == 1
    assert current_evidence[0]["relation"] == "contradicts"
    judgements = [
        row for row in read_jsonl(records / "judgements.jsonl")
        if row["claim_id"] == claim["id"]
    ]
    latest = max(judgements, key=lambda row: row["judged_at"])
    assert latest["verdict"] == "contradicted"
    assert current_evidence[0]["evidence_id"] in latest["evidence_ids"]


def test_manual_evidence_is_superseded_when_claim_text_changes(tmp_path):
    timeline = tmp_path / "timeline"
    page = timeline / "05-opium-war" / "1841-example.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: Example\n---\n", encoding="utf-8")
    records = tmp_path / "records"
    candidate = {
        "source": "Manual official-source audit",
        "title": "Official record",
        "url": "https://example.org/manual-evidence",
        "passage": "The official source states the mint was constructed in 1864.",
        "passage_status": "inspectable_text",
        "relation": "contradicts",
        "claims": [1],
        "why": "Manual source audit; exact passage inspected.",
    }
    store.persist_page_judgement(
        page, timeline, "Example event", "1846", [], [candidate],
        None, "manual-source-audit-2026-10-10", records_dir=records,
    )
    store.persist_page_judgement(
        page, timeline, "Example event", "1864", [], [],
        "test-model", 12, records_dir=records,
    )
    evidence = read_jsonl(records / "evidence.jsonl")
    assert len(evidence) == 1
    assert evidence[0]["is_current"] is False
    claims = read_jsonl(records / "claims.jsonl")
    old_claim = next(row for row in claims if row["text"] == "Example event occurred in 1846.")
    new_claim = next(row for row in claims if row["text"] == "Example event occurred in 1864.")
    assert old_claim["is_current"] is False
    assert new_claim["status"] == "unverified"
