#!/usr/bin/env python3
"""Fail-closed validation for pages explicitly entering published history.

Legacy AI drafts remain available as clearly labelled research material. A page only
opts into the authoritative published-history layer with publication_status: published
and must carry claim-level verdicts plus direct evidence URLs.
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_ROOT = PROJECT_ROOT / "content"
PUBLISHED_STATUS = "published"
PUBLISHABLE_CLAIM_STATUSES = {"supported", "disputed"}
CORE_PUBLISHABLE_STATUSES = {"supported", "disputed"}


def parse_frontmatter(text):
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.DOTALL)
    if not match:
        return None, ""
    raw = match.group(1)
    fields = {}
    for line in raw.splitlines():
        scalar = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if scalar:
            fields[scalar.group(1)] = scalar.group(2).strip().strip('"').strip("'")
    return fields, raw


def parse_claims(frontmatter):
    """Parse the deliberately small, documented YAML subset used for claim records."""
    match = re.search(
        r"(?ms)^claims:\s*\n(.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:\s*|\Z)",
        frontmatter,
    )
    if not match:
        return []
    block = match.group(1)
    chunks = re.split(r"(?m)^\s{2}-\s+", block)
    claims = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        def value(key):
            found = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(.*?)\s*$", chunk)
            return found.group(1).strip().strip('"').strip("'") if found else ""
        claims.append({
            "id": value("id"),
            "text": value("text"),
            "importance": value("importance").lower(),
            "status": value("status").lower(),
            "evidence_urls": re.findall(r"https?://[^\s\]>)\"']+", chunk),
            "passage_status": value("passage_status").lower(),
            "evidence_relations": [relation.lower() for relation in re.findall(r"(?m)^\s*relation:\s*(.*?)\s*$", chunk)],
            "passage": value("passage").strip(),
        })
    return claims


def validate_page(path, text):
    fields, frontmatter = parse_frontmatter(text)
    if fields is None:
        return []
    errors = []
    publication_status = fields.get("publication_status", "").lower()
    verification_status = fields.get("verification_status", "").lower()
    confidence = fields.get("confidence", "").lower()
    tags = fields.get("tags", "").lower()

    if verification_status == "verified" and publication_status != PUBLISHED_STATUS:
        errors.append("verification_status: verified requires publication_status: published")

    if publication_status != PUBLISHED_STATUS:
        return errors

    if confidence == "ai-draft" or "ai-draft" in tags:
        errors.append("AI-draft pages cannot be published as authoritative history")
    if verification_status not in {"verified", "disputed"}:
        errors.append("published pages require verification_status: verified or disputed")

    claims = parse_claims(frontmatter)
    if not claims:
        errors.append("published pages require claim-level records under frontmatter 'claims:'")

    for index, claim in enumerate(claims, start=1):
        label = claim["id"] or f"claim #{index}"
        if not claim["id"] or not claim["text"]:
            errors.append(f"{label}: each claim requires id and text")
        if claim["importance"] not in {"core", "supporting"}:
            errors.append(f"{label}: importance must be core or supporting")
        if claim["status"] not in PUBLISHABLE_CLAIM_STATUSES:
            errors.append(f"{label}: status must be supported or explicitly disputed")
        if claim["importance"] == "core" and claim["status"] not in CORE_PUBLISHABLE_STATUSES:
            errors.append(f"{label}: core claim is unresolved")
        if not claim["evidence_urls"]:
            errors.append(f"{label}: claim requires at least one direct evidence URL")
        if claim["passage_status"] not in {"inspectable", "inspectable_text", "inspectable_abstract", "inspectable_record"}:
            errors.append(f"{label}: claim requires inspectable evidence passage; metadata-only sources are not proof")
        passage = claim["passage"].strip().strip(chr(34) + chr(39))
        if len(passage) < 30:
            errors.append(f"{label}: claim requires a non-empty inspectable evidence passage (at least 30 characters)")
        relations = set(claim["evidence_relations"])
        if claim["status"] == "supported" and "supports" not in relations:
            errors.append(f"{label}: supported claims require an evidence relation of supports")
        if claim["status"] == "supported" and "contradicts" in relations:
            errors.append(f"{label}: contradictory evidence blocks a supported verdict; mark the claim disputed")
        if claim["status"] == "disputed" and "contradicts" not in relations:
            errors.append(f"{label}: disputed claims require an evidence relation of contradicts")

    if any(claim["status"] == "disputed" for claim in claims) and verification_status != "disputed":
        errors.append("pages with disputed claims must set verification_status: disputed")
    if not re.search(r"(?m)^##?\s+Evidence\b", text, re.IGNORECASE):
        errors.append("published pages require an Evidence section that discloses the supporting material")

    return errors


def main(argv=None):
    root = Path(argv[0]).resolve() if argv else CONTENT_ROOT
    if not root.is_dir():
        print(f"Publication gate: content directory not found: {root}", file=sys.stderr)
        return 2

    checked = 0
    failures = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            failures.append((path, [f"cannot read file: {exc}"]))
            continue
        fields, _ = parse_frontmatter(text)
        if fields is None:
            continue
        if fields.get("publication_status", "").lower() == PUBLISHED_STATUS or fields.get("verification_status", "").lower() == "verified":
            checked += 1
        errors = validate_page(path, text)
        if errors:
            failures.append((path, errors))

    if failures:
        print(f"PUBLICATION GATE FAILED: {len(failures)} page(s) need correction.")
        for path, errors in failures:
            print(f"- {path.relative_to(root)}")
            for error in errors:
                print(f"  - {error}")
        return 1

    print(f"Publication gate passed: {checked} explicitly published/verified page(s) checked.")
    print("Unverified and AI-draft pages remain research material; evidence grades alone do not publish them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
