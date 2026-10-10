#!/usr/bin/env python3
"""Build a read-only, prioritised queue of claims needing further research.

The queue is a heuristic, not a historical verdict. It prioritises core claims,
then contradictions/unresolved statuses, missing inspectable passages, and missing
judgements. It never writes to the record store unless --output is supplied, and
that output must be a new file.
"""
import argparse
import json
import sys
from pathlib import Path

from research_records import validate_record

DEFAULT_RECORDS_DIR = Path(__file__).resolve().parent.parent / "research" / "records"
FILES = {
    "claims": "claims.jsonl",
    "sources": "sources.jsonl",
    "evidence": "evidence.jsonl",
    "judgements": "judgements.jsonl",
}
UNRESOLVED = {"unverified", "partial", "insufficient", "contradicted"}
STATUS_RANK = {"contradicted": 0, "unverified": 1, "partial": 2, "insufficient": 3, "supported": 4}
MIN_PASSAGE_LENGTH = 30


def read_jsonl(path):
    rows = []
    if not path.exists():
        raise ValueError(f"missing record file: {path.name}")
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_no}: invalid JSON ({exc.msg})") from exc
        errors = validate_record(row)
        if errors:
            raise ValueError(f"{path.name}:{line_no}: invalid record ({'; '.join(errors)})")
        rows.append(row)
    return rows


def load_records(records_dir=DEFAULT_RECORDS_DIR):
    root = Path(records_dir)
    return {key: read_jsonl(root / filename) for key, filename in FILES.items()}


def build_queue(records, limit=None):
    claims = [row for row in records["claims"] if row.get("is_current", True) is True]
    evidence = [row for row in records["evidence"] if row.get("is_current", True) is True]
    evidence_by_claim = {}
    for row in evidence:
        evidence_by_claim.setdefault(row.get("claim_id"), []).append(row)

    latest_judgement = {}
    for row in records["judgements"]:
        claim_id = row.get("claim_id")
        if not claim_id:
            continue
        previous = latest_judgement.get(claim_id)
        stamp = str(row.get("judged_at") or "")
        if previous is None or (stamp, str(row.get("judgement_id") or "")) > (
            str(previous.get("judged_at") or ""), str(previous.get("judgement_id") or "")
        ):
            latest_judgement[claim_id] = row

    queued = []
    for claim in claims:
        claim_id = claim.get("id")
        claim_evidence = evidence_by_claim.get(claim_id, [])
        inspectable = [
            row for row in claim_evidence
            if row.get("passage_status") == "inspectable"
            and isinstance(row.get("passage"), str)
            and len(row["passage"].strip()) >= MIN_PASSAGE_LENGTH
        ]
        judgement = latest_judgement.get(claim_id)
        status = claim.get("status", "unverified")
        if status == "supported" and inspectable and judgement:
            continue

        reasons = []
        if claim.get("importance") == "core":
            reasons.append("core claim")
        if status in UNRESOLVED:
            reasons.append(f"status={status}")
        if not inspectable:
            reasons.append("no inspectable passage")
        if not judgement:
            reasons.append("no judgement")
        if judgement and judgement.get("verdict") not in {"supported", "contradicted", "partial", "insufficient"}:
            reasons.append(f"judgement={judgement.get('verdict')}")
        rank = (
            0 if claim.get("importance") == "core" else 1,
            STATUS_RANK.get(status, 2),
            0 if not inspectable else 1,
            0 if not judgement else 1,
            str(claim.get("updated_at") or ""),
            str(claim_id or ""),
        )
        queued.append((rank, {
            "claim_id": claim_id,
            "event_id": claim.get("event_id"),
            "claim_type": claim.get("claim_type"),
            "importance": claim.get("importance"),
            "status": status,
            "text": claim.get("text", ""),
            "evidence_count": len(claim_evidence),
            "inspectable_passage_count": len(inspectable),
            "latest_judgement_verdict": judgement.get("verdict") if judgement else None,
            "priority_reasons": reasons,
        }))

    queued.sort(key=lambda item: item[0])
    rows = [dict(priority=index + 1, **item) for index, (_, item) in enumerate(queued)]
    return rows if limit is None else rows[:max(0, limit)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, help="Create a new JSONL file; never overwrite")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records_dir)
        queue = build_queue(records, limit=args.limit)
        output = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in queue)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
        print(f"Research queue: {len(queue)} claim(s) emitted; read-only; no research records changed.", file=sys.stderr)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Research queue failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
