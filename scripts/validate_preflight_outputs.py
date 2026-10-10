#!/usr/bin/env python3
"""Validate isolated preflight JSONL outputs and always write a non-sensitive manifest."""
import hashlib
import json
import argparse
import re
import sys
from pathlib import Path

from extract_atomic_claims import parse_page
from research_records import validate_record

EXPECTED = {
    "mpf": "13-transition/1987-implementation-of-the-mandatory-provident-fund-planning.md",
    "tatsu-maru": "08-new-territories/1908-the-tatsu-maru-boycott-and-anti-japanese-movement.md",
    "occupation-1841": "05-opium-war/1841-formal-british-possession-of-hong-kong-island.md",
    "yeung-ku-wan": "08-new-territories/1901-assassination-of-yeung-ku-wan.md",
}


def validate_file(path, expected_page, timeline_root):
    if not path.is_file():
        return {"file": path.name, "status": "failed", "reason": "output_missing", "claim_count": 0}
    raw = path.read_bytes()
    if not raw.strip():
        return {"file": path.name, "status": "failed", "reason": "output_empty", "claim_count": 0,
                "sha256": hashlib.sha256(raw).hexdigest()}
    rows = []
    try:
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {"file": path.name, "status": "failed",
                        "reason": f"invalid_jsonl_line_{line_number}", "claim_count": len(rows),
                        "sha256": hashlib.sha256(raw).hexdigest()}
            if not isinstance(row, dict):
                return {"file": path.name, "status": "failed",
                        "reason": f"record_not_object_line_{line_number}", "claim_count": len(rows),
                        "sha256": hashlib.sha256(raw).hexdigest()}
            rows.append(row)
    except UnicodeDecodeError:
        return {"file": path.name, "status": "failed", "reason": "invalid_utf8",
                "claim_count": 0, "sha256": hashlib.sha256(raw).hexdigest()}

    if not rows:
        reason = "no_records"
    else:
        ids = [row.get("id") for row in rows]
        if any(not isinstance(value, str) or not value.strip() for value in ids):
            reason = "missing_record_id"
        elif len(set(ids)) != len(ids):
            reason = "duplicate_record_ids"
        else:
            reason = ""
            for row in rows:
                provenance = row.get("provenance")
                if not isinstance(provenance, dict):
                    reason = "missing_provenance"
                    break
                if validate_record(row):
                    reason = "schema_invalid"
                    break
                if not isinstance(provenance.get("source_excerpt"), str) or not provenance["source_excerpt"].strip():
                    reason = "missing_source_excerpt"
                    break
                source_path = Path(timeline_root) / expected_page
                if not source_path.is_file():
                    reason = "source_page_missing"
                    break
                try:
                    _, _, source_prose, explicit_claims = parse_page(source_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    reason = "source_page_unreadable"
                    break
                source_material = "\n".join([source_prose, *explicit_claims])
                normalise = lambda value: re.sub(r"\s+", " ", re.sub(r"[*_~]", "", re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(value or "")))).strip().casefold()
                if normalise(provenance["source_excerpt"]) not in normalise(source_material):
                    reason = "source_excerpt_not_grounded"
                    break
                checks = [
                    (row.get("record_type") == "claim", "invalid_record_type"),
                    (row.get("schema_version") == 1, "invalid_schema_version"),
                    (row.get("status") == "unverified", "claim_not_unverified"),
                    (isinstance(row.get("event_id"), str) and bool(row["event_id"].strip()), "missing_event_id"),
                    (isinstance(row.get("text"), str) and bool(row["text"].strip()), "missing_claim_text"),
                    (isinstance(provenance.get("source_excerpt"), str) and bool(provenance["source_excerpt"].strip()), "missing_source_excerpt"),
                    (provenance.get("source_page") == f"content/01_Timeline/{expected_page}", "source_page_mismatch"),
                    (isinstance(provenance.get("model"), str) and bool(provenance["model"].strip()), "missing_model"),
                    (provenance.get("prompt_version") == 6, "prompt_version_mismatch"),
                    (len(re.findall(r"\b\w+\b", row.get("text", ""))) <= 35, "claim_too_long"),
                ]
                reason = next((message for valid, message in checks if not valid), "")
                if reason:
                    break

    entry = {
        "file": path.name,
        "status": "success" if not reason else "failed",
        "claim_count": len(rows),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "models": sorted({r["provenance"]["model"] for r in rows
                          if isinstance(r.get("provenance"), dict) and r["provenance"].get("model")}),
        "prompt_versions": sorted({r["provenance"]["prompt_version"] for r in rows
                                   if isinstance(r.get("provenance"), dict) and "prompt_version" in r["provenance"]}),
    }
    if reason:
        entry["reason"] = reason
    return entry


def build_manifest(out_dir, timeline_root):
    files = [validate_file(out_dir / f"{name}.jsonl", page, timeline_root) for name, page in EXPECTED.items()]
    failures = {item["file"]: item.get("reason", "validation_failed")
                for item in files if item["status"] != "success"}
    return {
        "experiment": "evidence-first-preflight",
        "prompt_version": 6,
        "files": files,
        "failures": failures,
        "acceptance": {
            "all_reference_pages_have_nonempty_valid_jsonl": not failures,
            "all_claims_unverified": not any(item.get("reason") == "claim_not_unverified" for item in files),
            "live_records_modified": False,
            "bulk_extraction_approved": False,
            "publication_approved": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--timeline-root", type=Path, required=True)
    args = parser.parse_args(argv)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(out_dir, args.timeline_root.resolve())
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PREFLIGHT_SUMMARY " + json.dumps({
        "successful_pages": sum(item["status"] == "success" for item in manifest["files"]),
        "failed_pages": len(manifest["failures"]),
        "claim_counts": {item["file"]: item["claim_count"] for item in manifest["files"]},
    }, sort_keys=True))
    return 1 if manifest["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
