#!/usr/bin/env python3
"""Create non-destructive claim/source migration records from legacy timeline pages.

This is an initial extraction pass, not verification. It only extracts explicit
"Claims to verify" bullets; it never invents claims from narrative prose. Existing
external links are retained as source candidates, not evidence. Run without --write
to preview counts before creating JSONL files.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from research_records import require_valid_record
from research_record_store import claim_id_for, normalize_claim_text
from state import atomic_write

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTENT_ROOT = PROJECT_ROOT / "content" / "01_Timeline"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "research" / "records"
CLAIMS_HEADING = re.compile(r"(?im)^#{2,4}\s+claims?\s+to\s+verify\s*$")
NEXT_HEADING = re.compile(r"(?m)^#{1,4}\s+")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BARE_URL = re.compile(r"(?<![\"'(])https?://[^\s<>\])]+", re.IGNORECASE)


def slug(value):
    value = value.lower().replace("\\", "-").replace("/", "-")
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


def event_id_for(path, content_root):
    relative = path.relative_to(content_root).with_suffix("")
    return "event:" + slug(relative.as_posix())


def migration_event_date(text):
    """Avoid treating a conventional YYYY-01-01 placeholder as a known exact date."""
    date_value = frontmatter_value(text, "date")
    year_value = frontmatter_value(text, "year")
    match = re.fullmatch(r"(\d{4})-01-01", date_value)
    if not match or year_value != match.group(1):
        return date_value or year_value

    frontmatter = re.match(r"\A---\s*\n.*?\n---\s*\n(.*)\Z", text, re.S)
    body = frontmatter.group(1) if frontmatter else text
    year = match.group(1)
    explicit_january_first = re.search(
        rf"(?i)(?:\b{year}-01-01\b|\b1\s+January\s+{year}\b|"
        rf"\bJanuary\s+1,?\s+{year}\b|\bJan(?:uary)?\s+1,?\s+{year}\b|"
        rf"\b1\s+Jan(?:uary)?\s+{year}\b)",
        body,
    )
    return date_value if explicit_january_first else year_value


def frontmatter_value(text, key):
    match = re.match(r"\A---\s*\n(.*?)\n---", text, re.S)
    if not match:
        return ""
    value = re.search(rf'(?m)^{re.escape(key)}: *"?(.*?)"?$', match.group(1))
    return value.group(1).strip() if value else ""

def extract_claim_bullets(text):
    """Return only explicit bullets under a Claims to verify heading."""
    match = CLAIMS_HEADING.search(text)
    if not match:
        return []
    tail = text[match.end():]
    next_heading = NEXT_HEADING.search(tail)
    section = tail[:next_heading.start()] if next_heading else tail
    claims = []
    for line in section.splitlines():
        bullet = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
        if not bullet:
            continue
        claim = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", bullet.group(1))
        claim = re.sub(r"[*_~]", "", claim).strip()
        claim = re.sub(r"^(?:❔|\[[ xX]\])\s*", "", claim).strip()
        if claim and claim not in claims:
            claims.append(claim)
    return claims


def external_source_links(text):
    """Return unique non-Wikipedia URLs linked or cited in a legacy page."""
    found = []
    candidates = [url for _, url in MARKDOWN_LINK.findall(text)]
    candidates.extend(BARE_URL.findall(text))
    for url in candidates:
        url = url.rstrip(".,;:")
        host = (urlparse(url).hostname or "").lower()
        if not host or host == "wikipedia.org" or host.endswith(".wikipedia.org") or host == "wikidata.org" or host.endswith(".wikidata.org"):
            continue
        if url not in found:
            found.append(url)
    return found


def build_records(content_root, now=None, limit=None):
    """Build validated claim and source-candidate records without changing source pages."""
    content_root = Path(content_root).resolve()
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    claims, sources, claim_extraction_queue = [], [], []
    pages_seen, pages_without_claims, explicit_claims_extracted = 0, [], 0
    paths = sorted(content_root.rglob("*.md"))
    if limit is not None:
        paths = paths[:limit]
    for path in paths:
        if any(part.startswith(".") for part in path.relative_to(content_root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Cannot read {path}: {exc}") from exc
        pages_seen += 1
        event_id = event_id_for(path, content_root)
        page_claims = extract_claim_bullets(text)
        explicit_claims_extracted += len(page_claims)
        seen_claim_ids = set()
        event_title = frontmatter_value(text, "title")
        event_date = migration_event_date(text)
        if event_title and event_date:
            event_claim_text = f"{event_title} occurred in {event_date}."
            event_claim_id = claim_id_for(event_id, event_claim_text)
            event_claim = {
                "record_type": "claim", "schema_version": 1, "id": event_claim_id,
                "event_id": event_id, "text": event_claim_text, "claim_type": "date",
                "status": "unverified", "is_current": True, "superseded_at": None,
                "importance": "core", "created_from": "migration", "created_at": timestamp,
                "updated_at": timestamp,
                "provenance": {"source_page": path.relative_to(content_root.parent).as_posix(),
                               "extraction": "event title/date"},
            }
            claims.append(require_valid_record(event_claim))
            seen_claim_ids.add(event_claim_id)
        if not page_claims:
            pages_without_claims.append(path.relative_to(content_root).as_posix())
            relative_page = path.relative_to(content_root.parent).as_posix()
            # Core-period priority starts at 1841, not at an era-folder boundary.
            # Prefer the page date when present; otherwise use the filename year.
            year_source = event_date or path.stem
            year_match = re.search(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2})(?!\d)", year_source)
            event_year = int(year_match.group(0)) if year_match else None
            priority = "core" if event_year is not None and event_year >= 1841 else "deferred"
            task = {
                "record_type": "claim_extraction_task",
                "schema_version": 1,
                "task_id": "task:claim-extraction-" + event_id.removeprefix("event:"),
                "event_id": event_id,
                "source_page": relative_page,
                "status": "queued",
                "priority": priority,
                "reason": "No explicit Claims to verify section; claim extraction is required before claim-level verification.",
                "created_at": timestamp,
            }
            claim_extraction_queue.append(require_valid_record(task))
        for claim_text in page_claims:
            claim_text = normalize_claim_text(claim_text)
            claim_id = claim_id_for(event_id, claim_text)
            if claim_id in seen_claim_ids:
                continue
            seen_claim_ids.add(claim_id)
            record = {
                "record_type": "claim",
                "schema_version": 1,
                "id": claim_id,
                "event_id": event_id,
                "text": claim_text,
                "claim_type": "other",
                "status": "unverified",
                "is_current": True,
                "superseded_at": None,
                "importance": "core",
                "created_from": "migration",
                "created_at": timestamp,
                "updated_at": timestamp,
                "provenance": {
                    "source_page": path.relative_to(content_root.parent).as_posix(),
                    "extraction": "explicit Claims to verify bullet",
                },
            }
            claims.append(require_valid_record(record))
        for url in external_source_links(text):
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            record = {
                "record_type": "source",
                "schema_version": 1,
                "source_id": f"source:{digest}",
                "title": urlparse(url).netloc,
                "institution": None,
                "event_ids": [event_id],
                "source_type": "other",
                "authority_level": "discovery_only",
                "coverage": None,
                "language": "und",
                "stable_url": url,
                "catalogue_reference": None,
                "retrieval_method": "imported",
                "publication_date": None,
                "discovered_at": timestamp,
                "rights_notes": "Imported URL only; source content has not been inspected or cleared for AI processing.",
            }
            sources.append(require_valid_record(record))
    unique_sources = {}
    for source in sources:
        existing = unique_sources.get(source["source_id"])
        if existing:
            existing["event_ids"] = sorted(set(existing["event_ids"] + source["event_ids"]))
        else:
            unique_sources[source["source_id"]] = source
    return {
        "pages_seen": pages_seen,
        "pages_without_explicit_claims": pages_without_claims,
        "claims": claims,
        "explicit_claims_extracted": explicit_claims_extracted,
        "sources": [unique_sources[key] for key in sorted(unique_sources)],
        "claim_extraction_queue": claim_extraction_queue,
    }


def merge_existing_records(path, incoming, key):
    """Merge a migration into existing records without resetting later research state.

    Existing records win on status, timestamps, provenance and inspected metadata. New
    records fill gaps, and source event links are unioned. Unrelated records are retained.
    """
    existing = []
    if path.exists():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict) or not record.get(key):
                raise ValueError(f"{path}:{line_no}: existing record must be an object with {key}")
            existing.append(require_valid_record(record))

    merged = {}
    for record in existing:
        merged[record[key]] = record
    for record in incoming:
        record = require_valid_record(record)
        identity = record[key]
        previous = merged.get(identity)
        if previous:
            combined = {**record, **previous}
            if key == "source_id":
                combined["event_ids"] = sorted(set(previous.get("event_ids", []) + record.get("event_ids", [])))
            merged[identity] = require_valid_record(combined)
        else:
            merged[identity] = record
    return list(merged.values())


def write_jsonl(path, records):
    """Atomically write a fully prepared JSONL snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    atomic_write(str(path), content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-root", type=Path, default=DEFAULT_CONTENT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="preview only the first N pages")
    parser.add_argument("--write", action="store_true", help="write JSONL records; otherwise preview counts only")
    args = parser.parse_args(argv)
    if not args.content_root.is_dir():
        print(f"Content root not found: {args.content_root}", file=sys.stderr)
        return 2
    try:
        result = build_records(args.content_root, limit=args.limit)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Migration preview failed: {exc}", file=sys.stderr)
        return 2
    print(f"Pages scanned: {result['pages_seen']}")
    print(f"Explicit claims extracted: {result['explicit_claims_extracted']}")
    print(f"Total claim records prepared: {len(result['claims'])}")
    print(f"Source candidates retained: {len(result['sources'])}")
    print(f"Pages with no explicit Claims to verify section: {len(result['pages_without_explicit_claims'])}")
    print(f"Claim-extraction tasks queued: {len(result['claim_extraction_queue'])}")
    if result["pages_without_explicit_claims"]:
        print("Those pages remain unmigrated for claim extraction; no claims were invented.")
    if not args.write:
        print("Preview only; no files written. Re-run with --write to save JSONL records.")
        return 0
    # Merge all outputs before writing any file: repeated migration must never reset a
    # previously judged claim to unverified or erase source/evidence links from later runs.
    output_claims = merge_existing_records(args.output_dir / "claims.jsonl", result["claims"], "id")
    output_sources = merge_existing_records(args.output_dir / "sources.jsonl", result["sources"], "source_id")
    output_queue = merge_existing_records(args.output_dir / "claim-extraction-queue.jsonl",
                                          result["claim_extraction_queue"], "task_id")
    write_jsonl(args.output_dir / "claims.jsonl", output_claims)
    write_jsonl(args.output_dir / "sources.jsonl", output_sources)
    write_jsonl(args.output_dir / "claim-extraction-queue.jsonl", output_queue)
    print(f"Wrote/merged records to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
