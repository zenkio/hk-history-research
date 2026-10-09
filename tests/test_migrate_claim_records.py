import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate_claim_records as migration
import research_record_store as store


def test_migration_extracts_only_explicit_claim_bullets_and_preserves_source_candidates(tmp_path):
    root = tmp_path / "content" / "01_Timeline"
    root.mkdir(parents=True)
    page = root / "1841-example.md"
    page.write_text(
        "---\ntitle: Example\ntags: [ai-draft]\n---\n"
        "## What happened\nThe event happened in 1841.\n"
        "## Claims to verify\n- ❔ The event happened in January 1841.\n"
        "- The proclamation was issued by Elliot.\n"
        "## Evidence\n[Archive catalogue](https://example.org/catalogue/1)\n"
        "[Wikipedia](https://en.wikipedia.org/wiki/Example)\n",
        encoding="utf-8",
    )
    result = migration.build_records(root, now="2026-10-09T10:00:00Z")

    assert result["pages_seen"] == 1
    assert len(result["claims"]) == 2
    assert result["claims"][0]["status"] == "unverified"
    assert result["claims"][0]["text"] == "The event happened in January 1841."
    assert result["claims"][0]["importance"] == "core"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["authority_level"] == "discovery_only"
    assert result["sources"][0]["language"] == "und"
    assert result["sources"][0]["event_ids"] == ["event:1841-example"]
    assert "passage" not in result["sources"][0]


def test_migration_does_not_invent_claims_for_pages_without_claim_section(tmp_path):
    root = tmp_path / "timeline"
    root.mkdir()
    (root / "1841-example.md").write_text(
        "---\ntitle: Example\n---\n## What happened\nA narrative claim in prose.\n",
        encoding="utf-8",
    )
    result = migration.build_records(root, now="2026-10-09T10:00:00Z")
    assert result["claims"] == []
    assert result["pages_without_explicit_claims"] == ["1841-example.md"]
    assert len(result["claim_extraction_queue"]) == 1
    task = result["claim_extraction_queue"][0]
    assert task["status"] == "queued"
    assert task["priority"] == "core"


def test_migration_writes_jsonl_only_when_explicitly_requested(tmp_path):
    root = tmp_path / "timeline"
    root.mkdir()
    (root / "1841-example.md").write_text(
        "---\ntitle: Example\n---\n## Claims to verify\n- A claim to verify.\n",
        encoding="utf-8",
    )
    output = tmp_path / "records"
    assert migration.main(["--content-root", str(root), "--output-dir", str(output)]) == 0
    assert not output.exists()

    assert migration.main([
        "--content-root", str(root), "--output-dir", str(output), "--write"
    ]) == 0
    claims = [json.loads(line) for line in (output / "claims.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(claims) == 1
    assert claims[0]["id"].startswith("claim:1841-example-")
    assert (output / "claim-extraction-queue.jsonl").exists()


def test_claim_ids_do_not_change_when_bullets_are_reordered(tmp_path):
    root = tmp_path / "timeline"
    root.mkdir()
    page = root / "1841-example.md"
    header = "---\ntitle: Example\n---\n## Claims to verify\n"
    first = "- Date is 1841.\n- Elliot issued a proclamation.\n"
    page.write_text(header + first, encoding="utf-8")
    a = {item["text"]: item["id"] for item in migration.build_records(root)["claims"]}
    page.write_text(header + "- Elliot issued a proclamation.\n- Date is 1841.\n", encoding="utf-8")
    b = {item["text"]: item["id"] for item in migration.build_records(root)["claims"]}
    assert a == b


def test_migration_seeds_unverified_event_date_claim_without_inventing_support(tmp_path):
    root = tmp_path / "timeline"
    root.mkdir()
    (root / "1841-example.md").write_text(
        '---\ntitle: "Treaty signing"\nyear: 1841\n---\n'
        '## What happened\nThe draft says the treaty was signed.\n',
        encoding="utf-8",
    )
    result = migration.build_records(root, now="2026-10-09T10:00:00Z")
    event_claim = next(c for c in result["claims"] if c["provenance"]["extraction"] == "event title/date")
    assert event_claim["text"] == "Treaty signing occurred in 1841."
    assert event_claim["claim_type"] == "date"
    assert event_claim["id"] == store.claim_id_for("event:1841-example", event_claim["text"])
    assert event_claim["status"] == "unverified"
    assert result["explicit_claims_extracted"] == 0
    assert len(result["claim_extraction_queue"]) == 1


def test_repeated_write_preserves_existing_verdicts_and_research_metadata(tmp_path):
    root = tmp_path / "timeline"
    root.mkdir()
    page = root / "1841-example.md"
    page.write_text(
        '---\ntitle: Example\nyear: 1841\n---\n'
        '## Claims to verify\n- The event happened in 1841.\n'
        '## Evidence\n[Archive catalogue](https://example.org/catalogue/1)\n',
        encoding="utf-8",
    )
    output = tmp_path / "records"
    args = ["--content-root", str(root), "--output-dir", str(output), "--write"]
    assert migration.main(args) == 0

    claims_path = output / "claims.jsonl"
    claims = [json.loads(line) for line in claims_path.read_text(encoding="utf-8").splitlines()]
    claims[0]["status"] = "supported"
    claims[0]["updated_at"] = "2026-10-01T00:00:00Z"
    migration.write_jsonl(claims_path, claims)

    sources_path = output / "sources.jsonl"
    sources = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
    sources[0]["event_ids"] = sorted(set(sources[0]["event_ids"] + ["event:previously-researched"]))
    sources[0]["authority_level"] = "institutional"
    migration.write_jsonl(sources_path, sources)

    assert migration.main(args) == 0
    claims_after = [json.loads(line) for line in claims_path.read_text(encoding="utf-8").splitlines()]
    preserved = next(row for row in claims_after if row["id"] == claims[0]["id"])
    assert preserved["status"] == "supported"
    assert preserved["updated_at"] == "2026-10-01T00:00:00Z"

    sources_after = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
    source = next(row for row in sources_after if row["stable_url"] == "https://example.org/catalogue/1")
    assert source["authority_level"] == "institutional"
    assert source["event_ids"] == ["event:1841-example", "event:previously-researched"]
