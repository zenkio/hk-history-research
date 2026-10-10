#!/usr/bin/env python3
"""Report claim-research completeness without printing historical claim text."""
import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_records import validate_record

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS_DIR = DEFAULT_PROJECT_ROOT / "research" / "records"
DEFAULT_EVIDENCE_STATE = Path(__file__).resolve().parent / "state" / "evidence.json"
DEFAULT_TIMELINE_DIR = DEFAULT_PROJECT_ROOT / "content" / "01_Timeline"
FILES = {
    "claims": "claims.jsonl",
    "sources": "sources.jsonl",
    "evidence": "evidence.jsonl",
    "judgements": "judgements.jsonl",
    "queue": "claim-extraction-queue.jsonl",
}


def read_jsonl(path, label):
    records, errors = [], []
    if not path.exists():
        return records, errors
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}:{line_no}: invalid JSON ({exc.msg})")
            continue
        schema_errors = validate_record(record)
        if schema_errors:
            errors.append(f"{label}:{line_no}: " + "; ".join(schema_errors))
            continue
        records.append(record)
    return records, errors




def _page_key_from_source_page(source_page):
    if not isinstance(source_page, str) or not source_page.strip():
        return None
    normalized = source_page.replace("\\", "/").lstrip("/")
    if "01_Timeline/" in normalized:
        return normalized.split("01_Timeline/", 1)[1]
    if normalized.startswith("content/"):
        normalized = normalized[len("content/"):]
    if normalized.startswith("01_Timeline/"):
        normalized = normalized[len("01_Timeline/"):]
    return normalized or None


def _load_evidence_state(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def build_report(records_dir, stale_days=30, now=None, evidence_state_path=DEFAULT_EVIDENCE_STATE, content_root=DEFAULT_TIMELINE_DIR):
    records_dir = Path(records_dir)
    loaded, errors, missing = {}, [], []
    for key, filename in FILES.items():
        path = records_dir / filename
        loaded[key], file_errors = read_jsonl(path, filename)
        errors.extend(file_errors)
        if not path.exists():
            missing.append(filename)

    claims = [row for row in loaded["claims"] if row.get("is_current", True)]
    sources = loaded["sources"]
    evidence = [row for row in loaded["evidence"] if row.get("is_current", True)]
    judgements = loaded["judgements"]
    queue = loaded["queue"]
    evidence_by_claim = {}
    judgements_by_claim = {}
    for item in evidence:
        evidence_by_claim.setdefault(item["claim_id"], []).append(item)
    for item in judgements:
        judgements_by_claim.setdefault(item["claim_id"], []).append(item)

    current = now or datetime.now(timezone.utc)
    stale_before = current - timedelta(days=stale_days)
    stale_unverified = []
    for claim in claims:
        if claim["status"] != "unverified":
            continue
        try:
            updated = datetime.fromisoformat(claim["updated_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if updated < stale_before:
            stale_unverified.append(claim["id"])

    missing_evidence = [c["id"] for c in claims if not evidence_by_claim.get(c["id"])]
    no_inspectable_passage = [
        c["id"] for c in claims
        if not any(
            item["passage_status"] == "inspectable"
            and isinstance(item.get("passage"), str)
            and len(item["passage"].strip()) >= 30
            for item in evidence_by_claim.get(c["id"], [])
        )
    ]
    missing_judgement = [c["id"] for c in claims if not judgements_by_claim.get(c["id"])]
    evidence_state = _load_evidence_state(evidence_state_path)
    claims_without_search_state = None
    claims_without_source_page = None
    pages_without_search_state = None
    timeline_pages_total = None
    evidence_state_pages = None
    if evidence_state is not None:
        searched_pages = {str(key).replace("\\", "/") for key in evidence_state}
        claim_page_keys = [_page_key_from_source_page(
            claim.get("provenance", {}).get("source_page") if isinstance(claim.get("provenance"), dict) else None
        ) for claim in claims]
        claims_without_source_page = sum(1 for key in claim_page_keys if not key)
        claims_without_search_state = sum(1 for key in claim_page_keys if not key or key not in searched_pages)
        evidence_state_pages = len(searched_pages)
        timeline_root = Path(content_root)
        if timeline_root.is_dir():
            page_paths = [path for path in timeline_root.rglob("*.md")
                          if not any(part.startswith(".") for part in path.relative_to(timeline_root).parts)]
            timeline_pages_total = len(page_paths)
            pages_without_search_state = sum(
                1 for path in page_paths
                if path.relative_to(timeline_root).as_posix() not in searched_pages
            )
    report = {
        "records_dir": str(records_dir),
        "claims_without_search_state": claims_without_search_state,
        "claims_without_source_page": claims_without_source_page,
        "pages_without_search_state": pages_without_search_state,
        "timeline_pages_total": timeline_pages_total,
        "evidence_state_pages": evidence_state_pages,
        "evidence_state_missing": evidence_state is None,
        "claims_total": len(claims),
        "claim_status_counts": dict(Counter(c["status"] for c in claims)),
        "core_claims_unresolved": sum(
            1 for c in claims if c["importance"] == "core" and c["status"] in {"unverified", "partial", "insufficient", "contradicted"}
        ),
        "claims_without_evidence": len(missing_evidence),
        "claims_without_inspectable_passage": len(no_inspectable_passage),
        "claims_without_judgement": len(missing_judgement),
        "stale_unverified_claims": len(stale_unverified),
        "metadata_only_evidence": sum(1 for e in evidence if e["passage_status"] == "metadata_only"),
        "retrieval_failures": sum(1 for e in evidence if e["passage_status"] == "retrieval_failed"),
        "discovery_only_sources": sum(1 for s in sources if s["authority_level"] == "discovery_only"),
        "queued_claim_extraction_tasks": sum(1 for q in queue if q["status"] == "queued"),
        "missing_files": missing,
        "validation_errors": errors,
    }
    return report


def print_report(report):
    print(f"Claims: {report['claims_total']}")
    print(f"Claim statuses: {json.dumps(report['claim_status_counts'], sort_keys=True)}")
    for key, label in [
        ("core_claims_unresolved", "Unresolved core claims"),
        ("claims_without_evidence", "Claims without an evidence record"),
        ("claims_without_inspectable_passage", "Claims without an inspectable passage"),
        ("claims_without_judgement", "Claims without a judgement"),
        ("stale_unverified_claims", "Stale unverified claims"),
        ("metadata_only_evidence", "Metadata-only evidence records"),
        ("retrieval_failures", "Evidence retrieval failures"),
        ("discovery_only_sources", "Discovery-only source candidates"),
        ("queued_claim_extraction_tasks", "Queued claim-extraction tasks"),
    ]:
        print(f"{label}: {report[key]}")
    if report["evidence_state_missing"]:
        print("Claims without search state: unavailable (evidence state file missing or invalid)")
    else:
        print(f"Claims without search state: {report['claims_without_search_state']}")
        print(f"Claims without source page: {report['claims_without_source_page']}")
        print(f"Timeline pages without search state: {report['pages_without_search_state']} of {report['timeline_pages_total']}")
    if report["missing_files"]:
        print("Missing record files: " + ", ".join(report["missing_files"]))
    for error in report["validation_errors"]:
        print("VALIDATION ERROR: " + error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--strict", action="store_true", help="exit non-zero for invalid records or incomplete core claims")
    args = parser.parse_args(argv)
    report = build_report(args.records_dir, stale_days=args.stale_days)
    print_report(report)
    if not args.strict:
        return 0
    if report["validation_errors"] or report["missing_files"] or not report["claims_total"]:
        return 1
    if any(report[key] for key in (
        "core_claims_unresolved", "claims_without_evidence",
        "claims_without_inspectable_passage", "claims_without_judgement",
        "stale_unverified_claims", "retrieval_failures", "queued_claim_extraction_tasks",
    )):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
