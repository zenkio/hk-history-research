#!/usr/bin/env python3
"""Run a single-page atomic-claim extraction experiment without touching the live store.

Default output is JSONL on stdout. --output creates a new file and refuses to overwrite.
This tool does not modify source pages, research/records, publication status, or the schedule.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from atomic_claims import build_claim_records, extract_atomic_claims
from gemini_pool import ModelPool
from research_record_store import event_id_for_relative_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMELINE_ROOT = PROJECT_ROOT / "content" / "01_Timeline"
CLAIMS_HEADING = re.compile(r"(?im)^#{2,4}\s+claims?\s+to\s+verify\s*$")
NEXT_HEADING = re.compile(r"(?m)^#{1,4}\s+")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)


EXCLUDED_EXTRACTION_HEADINGS = {
    "claims to verify", "claim to verify", "evidence", "sources", "source",
    "references", "further reading", "wikipedia cross-check", "people and places", "see also",
}


def narrative_prose(body):
    """Keep draft prose, excluding research/evidence sections that are not the draft itself."""
    kept = []
    skipped_level = None
    for line in body.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level = len(heading.group(1))
            name = re.sub(r"\s+", " ", heading.group(2)).strip().casefold()
            if skipped_level is not None and level <= skipped_level:
                skipped_level = None
            if skipped_level is None and name in EXCLUDED_EXTRACTION_HEADINGS:
                skipped_level = level
                continue
        if skipped_level is None:
            kept.append(line)
    return "\n".join(kept).strip()


def parse_page(text):
    """Return title, date, prose, and existing explicit claim bullets."""
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("Page must have YAML frontmatter bounded by --- lines")
    metadata, body = match.groups()

    def field(name):
        found = re.search(rf"(?m)^{re.escape(name)}:\s*['\"]?(.*?)['\"]?\s*$", metadata)
        return found.group(1).strip() if found else ""

    title = field("title")
    date = field("date") or field("year")
    if not title:
        raise ValueError("Page frontmatter must contain title")
    claims = []
    heading = CLAIMS_HEADING.search(body)
    if heading:
        tail = body[heading.end():]
        next_heading = NEXT_HEADING.search(tail)
        section = tail[:next_heading.start()] if next_heading else tail
        for line in section.splitlines():
            bullet = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
            if bullet:
                claim = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", bullet.group(1))
                claim = re.sub(r"[*_~]", "", claim).strip()
                claim = re.sub(r"^(?:❔|\[[ xX]\])\s*", "", claim).strip()
                if claim and claim not in claims:
                    claims.append(claim)
    return title, date, narrative_prose(body), claims


def run_extraction(page_path, pool, timeline_root=DEFAULT_TIMELINE_ROOT, created_at=None):
    """Extract and validate one page, returning records without persisting them."""
    page_path = Path(page_path).resolve()
    timeline_root = Path(timeline_root).resolve()
    try:
        relative = page_path.relative_to(timeline_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Page must be inside timeline root: {timeline_root}") from exc
    text = page_path.read_text(encoding="utf-8")
    title, date, body, existing_claims = parse_page(text)
    extraction = extract_atomic_claims(
        pool, title=title, date=date, draft_text=body, existing_claims=existing_claims
    )
    timestamp = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    records = build_claim_records(
        extraction["claims"],
        event_id=event_id_for_relative_path(relative),
        source_page=f"content/01_Timeline/{relative}",
        model=extraction["model"],
        prompt_version=extraction["prompt_version"],
        created_at=timestamp,
    )
    return {"page": relative, "title": title, "model": extraction["model"],
            "prompt_version": extraction["prompt_version"], "records": records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page", type=Path, help="One Markdown page under content/01_Timeline")
    parser.add_argument("--timeline-root", type=Path, default=DEFAULT_TIMELINE_ROOT)
    parser.add_argument("--output", type=Path, help="Create a new JSONL file; never overwrite")
    args = parser.parse_args(argv)
    try:
        result = run_extraction(args.page, ModelPool(), args.timeline_root)
        output = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                         for row in result["records"])
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
        print(f"Extracted {len(result['records'])} unverified claims for {result['page']} "
              f"(model={result['model']}); no live records or pages changed.", file=sys.stderr)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Atomic claim extraction failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
