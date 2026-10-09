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
    pages_seen, pages_without_claims = 0, []
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
        if not page_claims:
            pages_without_claims.append(path.relative_to(content_root).as_posix())
            relative_page = path.relative_to(content_root.parent).as_posix()
            era_slug = path.relative_to(content_root).parts[0] if len(path.relative_to(content_root).parts) > 1 else ""
            priority = "core" if era_slug >= "05-opium-war" or re.search(r"(?:18[4-9]\d|19\d{2}|20\d{2})", path.stem) else "deferred"
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
            normalized_claim = re.sub(r"\s+", " ", claim_text).strip().casefold()
            claim_digest = hashlib.sha256(normalized_claim.encode("utf-8")).hexdigest()[:10]
            claim_id = f"claim:{event_id.removeprefix('event:')}-{claim_digest}"
            record = {
                "record_type": "claim",
                "schema_version": 1,
                "id": claim_id,
                "event_id": event_id,
                "text": claim_text,
                "claim_type": "other",
                "status": "unverified",
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
                "language": "en",
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
        "sources": [unique_sources[key] for key in sorted(unique_sources)],
        "claim_extraction_queue": claim_extraction_queue,
    }


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


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
    print(f"Explicit claims extracted: {len(result['claims'])}")
    print(f"Source candidates retained: {len(result['sources'])}")
    print(f"Pages with no explicit Claims to verify section: {len(result['pages_without_explicit_claims'])}")
    print(f"Claim-extraction tasks queued: {len(result['claim_extraction_queue'])}")
    if result["pages_without_explicit_claims"]:
        print("Those pages remain unmigrated for claim extraction; no claims were invented.")
    if not args.write:
        print("Preview only; no files written. Re-run with --write to save JSONL records.")
        return 0
    write_jsonl(args.output_dir / "claims.jsonl", result["claims"])
    write_jsonl(args.output_dir / "sources.jsonl", result["sources"])
    write_jsonl(args.output_dir / "claim-extraction-queue.jsonl", result["claim_extraction_queue"])
    print(f"Wrote records to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
