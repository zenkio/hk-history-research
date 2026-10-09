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
    """Parse claim records and their nested evidence entries from the documented YAML subset."""
    match = re.search(
        r"(?ms)^claims:[ \t]*\n(.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:[ \t]*|\Z)",
        frontmatter,
    )
    if not match:
        return []
    block = match.group(1)
    chunks = re.split(r"(?m)^[ \t]{2}-[ \t]+", block)
    claims = []

    def scalar(key, text):
        found = re.search(rf"(?m)^[ \t]*{re.escape(key)}:[ \t]*(.*?)[ \t]*$", text)
        return found.group(1).strip().strip('"').strip("'") if found else ""

    for chunk in chunks:
        if not chunk.strip():
            continue
        evidence_match = re.search(
            r"(?ms)^[ \t]{4}evidence:[ \t]*\n(.*?)(?=^[ \t]{4}[A-Za-z_][A-Za-z0-9_-]*:[ \t]*|\Z)",
            chunk,
        )
        evidence_block = evidence_match.group(1) if evidence_match else ""
        evidence = []
        for entry in re.split(r"(?m)^[ \t]{6}-[ \t]+", evidence_block):
            urls = re.findall(r"https?://[^\s\]>)\"']+", entry)
            if not urls and not re.search(r"(?m)^[ \t]*relation:", entry):
                continue
            evidence.append({
                "url": urls[0] if urls else "",
                "relation": scalar("relation", entry).lower(),
                "passage_status": scalar("passage_status", entry).lower(),
                "passage": scalar("passage", entry).strip(),
            })
        claims.append({
            "id": scalar("id", chunk),
            "text": scalar("text", chunk),
            "importance": scalar("importance", chunk).lower(),
            "status": scalar("status", chunk).lower(),
            "evidence": evidence,
            # Kept as derived fields for diagnostics/backward-compatible callers.
            "evidence_urls": [item["url"] for item in evidence if item["url"]],
            "passage_status": scalar("passage_status", chunk).lower(),
            "evidence_relations": [item["relation"] for item in evidence if item["relation"]],
            "passage": scalar("passage", chunk).strip(),
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
        evidence = claim["evidence"]
        if not evidence or not any(item["url"] for item in evidence):
            errors.append(f"{label}: claim requires at least one direct evidence URL")
        inspectable = []
        for item in evidence:
            passage = item["passage"].strip().strip(chr(34) + chr(39))
            if (item["url"]
                    and item["passage_status"] in {"inspectable", "inspectable_text", "inspectable_abstract", "inspectable_record"}
                    and len(passage) >= 30):
                inspectable.append(item)
        if not inspectable:
            errors.append(f"{label}: claim requires an inspectable evidence passage tied to its own source URL (at least 30 characters)")
        relations = {item["relation"] for item in inspectable}
        if claim["status"] == "supported" and "supports" not in relations:
            errors.append(f"{label}: supported claims require inspectable evidence with relation supports")
        if claim["status"] == "supported" and "contradicts" in relations:
            errors.append(f"{label}: contradictory evidence blocks a supported verdict; mark the claim disputed")
        if claim["status"] == "disputed" and "contradicts" not in relations:
            errors.append(f"{label}: disputed claims require inspectable evidence with relation contradicts")

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
