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
def load_structured_records(records_dir):
    """Load the current claim/evidence state used by the research pipeline; malformed/missing data fails closed."""
    records_dir = Path(records_dir or PROJECT_ROOT / "research" / "records")
    loaded = {}
    errors = []
    from research_records import validate_record
    for kind, filename in (("claims", "claims.jsonl"), ("sources", "sources.jsonl"), ("evidence", "evidence.jsonl"), ("judgements", "judgements.jsonl")):
        path = records_dir / filename
        if not path.is_file():
            errors.append(f"structured research records missing: {filename}")
            loaded[kind] = []
            continue
        rows = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = __import__("json").loads(line)
            except ValueError as exc:
                errors.append(f"{filename}:{line_no}: invalid JSON ({exc})")
                continue
            if isinstance(row, dict):
                schema_errors = validate_record(row)
                if schema_errors:
                    errors.append(f"{filename}:{line_no}: invalid research record: " + "; ".join(schema_errors))
                else:
                    rows.append(row)
            else:
                errors.append(f"{filename}:{line_no}: record must be a JSON object")
        loaded[kind] = rows

    # JSON Schema checks shape; these checks enforce the cross-record links that JSON Schema
    # cannot express. A dangling or mismatched evidence record must not be silently ignored.
    claim_ids = {row.get("id") for row in loaded["claims"]}
    source_by_id = {row.get("source_id"): row for row in loaded["sources"]}
    evidence_ids = {row.get("evidence_id") for row in loaded["evidence"]}
    for index, row in enumerate(loaded["evidence"], start=1):
        if row.get("claim_id") not in claim_ids:
            errors.append(f"evidence.jsonl record {index}: unknown claim_id {row.get('claim_id')}")
        source = source_by_id.get(row.get("source_id"))
        if source is None:
            errors.append(f"evidence.jsonl record {index}: unknown source_id {row.get('source_id')}")
        elif str(source.get("stable_url") or "").strip() != str(row.get("url") or "").strip():
            errors.append(f"evidence.jsonl record {index}: evidence URL does not match source stable_url")
    for index, row in enumerate(loaded["judgements"], start=1):
        if row.get("claim_id") not in claim_ids:
            errors.append(f"judgements.jsonl record {index}: unknown claim_id {row.get('claim_id')}")
        for evidence_id in row.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"judgements.jsonl record {index}: unknown evidence_id {evidence_id}")
    return loaded, errors


def validate_against_records(claim, records, record_errors):
    """Require the inline publication claim to agree with the latest structured judgement and evidence."""
    label = claim["id"] or "claim"
    errors = [f"{label}: {error}" for error in record_errors]
    if record_errors:
        return errors
    claim_rows = [
        row for row in records["claims"]
        if row.get("id") == claim["id"] and row.get("is_current", True)
    ]
    if not claim_rows:
        return [f"{label}: no current structured claim record; AI-only claims cannot be published"]
    current = claim_rows[-1]
    status = str(current.get("status", "")).lower()
    judgements = sorted(
        (row for row in records["judgements"] if row.get("claim_id") == claim["id"]),
        key=lambda row: str(row.get("judged_at", "")),
    )
    latest_judgement = judgements[-1] if judgements else None
    latest_verdict = str(latest_judgement.get("verdict", "")).lower() if latest_judgement else ""
    latest_judged_evidence_ids = set(latest_judgement.get("evidence_ids", [])) if latest_judgement else set()
    sources_by_id = {
        row.get("source_id"): row for row in records["sources"]
        if row.get("source_id")
    }
    current_evidence = [
        row for row in records["evidence"]
        if row.get("claim_id") == claim["id"] and row.get("is_current", True)
        and row.get("passage_status") == "inspectable"
        and len(str(row.get("passage") or "").strip()) >= 30
        and str(row.get("url") or "").strip()
        and row.get("source_id") in sources_by_id
        and str(sources_by_id[row.get("source_id")].get("stable_url") or "").strip() == str(row.get("url") or "").strip()
    ]
    inline_evidence = [
        item for item in claim["evidence"]
        if item["url"]
        and item["passage_status"] in {"inspectable", "inspectable_text", "inspectable_abstract", "inspectable_record"}
        and len(item["passage"].strip().strip(chr(34) + chr(39))) >= 30
    ]
    linked_current_evidence = []
    for inline in inline_evidence:
        inline_passage = " ".join(inline["passage"].strip().strip(chr(34) + chr(39)).split())
        for row in current_evidence:
            if (str(row.get("url") or "").strip() != inline["url"]
                    or str(row.get("relation", "")).lower() != inline["relation"]):
                continue
            record_passage = " ".join(str(row.get("passage") or "").strip().split())
            if inline_passage in record_passage or record_passage in inline_passage:
                linked_current_evidence.append(row)
    if not linked_current_evidence:
        errors.append(f"{label}: inline evidence URL, relation and passage must match a current structured inspectable evidence record")
    relations = {str(row.get("relation", "")).lower() for row in current_evidence}
    judged_linked_evidence = [
        row for row in linked_current_evidence
        if row.get("evidence_id") in latest_judged_evidence_ids
    ]
    if linked_current_evidence and not judged_linked_evidence:
        errors.append(
            f"{label}: latest structured judgement must reference the current inline evidence passage"
        )
    linked_relations = {str(row.get("relation", "")).lower() for row in judged_linked_evidence}
    if claim["status"] == "supported":
        if status != "supported" or latest_verdict != "supported":
            errors.append(f"{label}: supported publication requires the latest structured claim and judgement to be supported")
        if "contradicts" in relations:
            errors.append(f"{label}: current structured contradictory evidence blocks a supported verdict; mark the claim disputed")
        if "supports" not in relations or "supports" not in linked_relations:
            errors.append(f"{label}: no current structured inspectable supporting evidence linked to the inline passage")
    elif claim["status"] == "disputed":
        if status not in {"partial", "contradicted"} or latest_verdict not in {"partial", "contradicted"}:
            errors.append(f"{label}: disputed publication requires a current partial/contradicted structured judgement")
        if "contradicts" not in relations or "contradicts" not in linked_relations:
            errors.append(f"{label}: disputed publication requires current structured inspectable contradictory evidence linked to the inline passage")
    return errors


def validate_page(path, text, records_dir=None):
    fields, frontmatter = parse_frontmatter(text)
    if fields is None:
        # A broken frontmatter delimiter must not hide an explicit publication claim.
        if re.search(
            r"(?im)^(?:publication_status\\s*:\\s*published|verification_status\\s*:\\s*verified)\\s*$",
            text,
        ):
            return ["published/verified marker present but frontmatter is missing or malformed"]
        return []
    errors = []
    publication_status = fields.get("publication_status", "").lower()
    verification_status = fields.get("verification_status", "").lower()
    confidence = fields.get("confidence", "").lower()
    origin = fields.get("origin", "").lower()
    tags = fields.get("tags", "").lower()
    is_ai_draft = (confidence == "ai-draft" or "ai-draft" in tags or ((origin == "ai" or bool(fields.get("source_feed"))) and verification_status != "verified" and publication_status != "published"))

    if is_ai_draft and not re.search(r"(?im)^>\s*\[!warning\]\s*AI draft\b", text):
        errors.append("AI-drafted pages must display the explicit AI draft research warning")
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
    records, record_errors = load_structured_records(records_dir)

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
        errors.extend(validate_against_records(claim, records, record_errors))

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
