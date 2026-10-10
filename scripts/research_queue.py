#!/usr/bin/env python3
"""Build a read-only, prioritised queue of claims needing further research.

The queue is a heuristic, not a historical verdict. It prioritises core claims,
then contradictions/unresolved statuses, missing inspectable passages, and missing
judgements. It never writes to the record store unless --output is supplied, and
that output must be a new file.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from research_records import validate_record

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS_DIR = DEFAULT_PROJECT_ROOT / "research" / "records"
DEFAULT_CONTENT_ROOT = DEFAULT_PROJECT_ROOT / "content"
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




def internal_link_counts(content_root=DEFAULT_CONTENT_ROOT):
    """Count distinct inbound Markdown/Obsidian links to each content page."""
    root = Path(content_root)
    if not root.is_dir():
        return {}
    pages = sorted(path for path in root.rglob("*.md")
                   if not any(part.startswith(".") for part in path.relative_to(root).parts))
    aliases = {}
    for path in pages:
        relative = path.relative_to(root).with_suffix("").as_posix().casefold()
        aliases.setdefault(relative, set()).add(path)
        aliases.setdefault(path.stem.casefold(), set()).add(path)
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:5000]
        except OSError:
            continue
        title_match = re.search(r"(?m)^title:\s*['\"]?(.+?)['\"]?\s*$", head)
        if title_match:
            aliases.setdefault(title_match.group(1).strip().casefold(), set()).add(path)

    inbound = {}
    wiki_link = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for source in pages:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        targets = wiki_link.findall(text) + markdown_link.findall(text)
        seen = set()
        for raw_target in targets:
            target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
            if not target or re.match(r"(?i)^(?:https?:|mailto:|data:)", target):
                continue
            target = target.replace("\\", "/")
            if target.startswith("/"):
                target = target.lstrip("/")
            if target.startswith("content/"):
                target = target[len("content/"):]
            if target.startswith("./"):
                target = (source.parent / target).resolve().relative_to(root.resolve()).as_posix()
            target = target.removesuffix(".md").casefold()
            matches = aliases.get(target, set())
            if not matches:
                matches = aliases.get(Path(target).name, set())
            if len(matches) != 1:
                continue
            destination = next(iter(matches))
            if destination == source or destination in seen:
                continue
            seen.add(destination)
            key = destination.relative_to(root).with_suffix("").as_posix().casefold()
            inbound[key] = inbound.get(key, 0) + 1
    return inbound


def _page_key(claim):
    provenance = claim.get("provenance")
    source_page = provenance.get("source_page") if isinstance(provenance, dict) else None
    if not isinstance(source_page, str) or not source_page.strip():
        return None
    parts = Path(source_page.replace("\\", "/")).parts
    if parts and parts[0].casefold() == "content":
        parts = parts[1:]
    if not parts:
        return None
    return Path(*parts).with_suffix("").as_posix().casefold()


def _event_year(claim):
    text = f"{claim.get('event_id', '')} {claim.get('text', '')}"
    match = re.search(r"(?<!\d)(18|19|20)\d{2}(?!\d)", text)
    return int(match.group(0)) if match else None

def build_queue(records, limit=None, content_root=DEFAULT_CONTENT_ROOT):
    claims = [row for row in records["claims"] if row.get("is_current", True) is True]
    evidence = [row for row in records["evidence"] if row.get("is_current", True) is True]
    evidence_by_claim = {}
    for row in evidence:
        evidence_by_claim.setdefault(row.get("claim_id"), []).append(row)

    link_counts = internal_link_counts(content_root)
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

        contradictions = [row for row in claim_evidence if row.get("relation") == "contradicts"
                          and row.get("passage_status") == "inspectable"
                          and isinstance(row.get("passage"), str)
                          and len(row["passage"].strip()) >= MIN_PASSAGE_LENGTH]
        reasons = []
        if claim.get("importance") == "core":
            reasons.append("core claim")
        if status in UNRESOLVED:
            reasons.append(f"status={status}")
        if contradictions:
            reasons.append("inspectable contradiction present")
        if not inspectable:
            reasons.append("no inspectable passage")
        if not judgement:
            reasons.append("no judgement")
        if judgement and judgement.get("verdict") not in {"supported", "contradicted", "partial", "insufficient"}:
            reasons.append(f"judgement={judgement.get('verdict')}")
        event_year = _event_year(claim)
        core_period = event_year is not None and event_year >= 1841
        page_key = _page_key(claim)
        internal_links = link_counts.get(page_key, 0) if page_key else 0
        if core_period:
            reasons.append("core period (1841+)")
        if internal_links:
            reasons.append(f"linked from {internal_links} internal page(s)")
        rank = (
            0 if core_period else 1,
            0 if claim.get("importance") == "core" else 1,
            STATUS_RANK.get(status, 2),
            -internal_links,
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
            "event_year": event_year,
            "core_period": core_period,
            "internal_link_count": internal_links,
            "source_page": claim.get("provenance", {}).get("source_page") if isinstance(claim.get("provenance"), dict) else None,
            "status": status,
            "text": claim.get("text", ""),
            "evidence_count": len(claim_evidence),
            "inspectable_passage_count": len(inspectable),
            "latest_judgement_verdict": judgement.get("verdict") if judgement else None,
            "latest_judgement_rationale": judgement.get("rationale") if judgement else None,
            "latest_judgement_uncertainty": judgement.get("uncertainty") if judgement else None,
            "judged_evidence_ids": list(judgement.get("evidence_ids") or []) if judgement else [],
            "evidence_ids": [row.get("evidence_id") for row in claim_evidence if row.get("evidence_id")],
            "source_ids": sorted({row.get("source_id") for row in claim_evidence if row.get("source_id")}),
            "has_inspectable_contradiction": bool(contradictions),
            "priority_reasons": reasons,
        }))

    queued.sort(key=lambda item: item[0])
    rows = [dict(priority=index + 1, **item) for index, (_, item) in enumerate(queued)]
    return rows if limit is None else rows[:max(0, limit)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    parser.add_argument("--content-root", type=Path, default=DEFAULT_CONTENT_ROOT,
                        help="content directory used to count internal links")
    parser.add_argument("--limit", type=int, default=100, help="maximum items to emit; use 0 for the full queue")
    parser.add_argument("--output", type=Path, help="Create a new JSONL file; never overwrite")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records_dir)
        full_queue = build_queue(records, content_root=args.content_root)
        queue = full_queue[:args.limit] if args.limit > 0 else full_queue
        output = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in queue)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
        print(f"Research queue: {len(queue)} of {len(full_queue)} eligible claim(s) emitted; read-only; no research records changed.", file=sys.stderr)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Research queue failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
