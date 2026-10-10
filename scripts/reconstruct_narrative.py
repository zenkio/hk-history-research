#!/usr/bin/env python3
"""Build a traceable, preview-only narrative from claim/evidence records.

This tool never edits source pages, records, scheduled jobs, or publication status. It
includes only claims whose current judgement and current inspectable supporting evidence
agree, and reports unresolved core claims rather than filling gaps from the old draft.
"""
import argparse
import json
import re
import sys
from pathlib import Path


DEFAULT_RECORDS_DIR = Path(__file__).resolve().parent.parent / "research" / "records"
RECORD_FILES = {
    "claims": "claims.jsonl",
    "sources": "sources.jsonl",
    "evidence": "evidence.jsonl",
    "judgements": "judgements.jsonl",
}
MIN_PASSAGE_LENGTH = 30


def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON ({exc.msg})") from exc
    return rows


def _current(row):
    return row.get("is_current", True) is True


def _markdown_safe(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_preview(records, event_id):
    """Return a preview plus explicit unresolved-core status; never claims to publish."""
    claims = [row for row in records["claims"]
              if row.get("event_id") == event_id and _current(row)]
    sources = {row.get("source_id"): row for row in records["sources"] if row.get("source_id")}
    evidence = [row for row in records["evidence"] if _current(row)]
    evidence_by_claim = {}
    for row in evidence:
        evidence_by_claim.setdefault(row.get("claim_id"), []).append(row)

    latest_judgement = {}
    for row in records["judgements"]:
        claim_id = row.get("claim_id")
        if not claim_id:
            continue
        old = latest_judgement.get(claim_id)
        stamp = str(row.get("judged_at") or "")
        if old is None or (stamp, str(row.get("judgement_id") or "")) > (
            str(old.get("judged_at") or ""), str(old.get("judgement_id") or "")
        ):
            latest_judgement[claim_id] = row

    core_claims = [claim for claim in claims if claim.get("importance") == "core"]
    included, unresolved_core = [], []
    for claim in claims:
        claim_id = claim.get("id")
        claim_evidence = evidence_by_claim.get(claim_id, [])
        supporting = [
            row for row in claim_evidence
            if row.get("relation") == "supports"
            and row.get("passage_status") == "inspectable"
            and isinstance(row.get("passage"), str)
            and len(row["passage"].strip()) >= MIN_PASSAGE_LENGTH
            and row.get("source_id") in sources
            and (row.get("url") or sources[row["source_id"]].get("stable_url"))
        ]
        contradictory = [
            row for row in claim_evidence
            if row.get("relation") == "contradicts"
            and row.get("passage_status") == "inspectable"
            and isinstance(row.get("passage"), str)
            and len(row["passage"].strip()) >= MIN_PASSAGE_LENGTH
        ]
        judgement = latest_judgement.get(claim_id)
        judged_support_ids = set(judgement.get("evidence_ids") or []) if judgement else set()
        accepted = [
            row for row in supporting
            if row.get("evidence_id") in judged_support_ids
        ]
        valid = (
            claim.get("status") == "supported"
            and judgement is not None
            and judgement.get("verdict") == "supported"
            and bool(accepted)
            and not contradictory
        )
        if valid:
            included.append((claim, accepted))
        elif claim.get("importance") == "core":
            reasons = []
            if claim.get("status") != "supported":
                reasons.append("claim status is not supported")
            if judgement is None or judgement.get("verdict") != "supported":
                reasons.append("latest judgement is not supported")
            if not accepted:
                reasons.append("no current inspectable supporting passage linked by the judgement")
            if contradictory:
                reasons.append("current inspectable contradictory evidence exists")
            unresolved_core.append({
                "claim_id": claim_id,
                "text": claim.get("text", ""),
                "reasons": reasons or ["evidence gate not met"],
            })

    core_gate_passed = bool(core_claims) and not unresolved_core
    lines = [
        "# Research narrative preview",
        "",
        "> **RESEARCH PREVIEW — NOT PUBLISHED.** This is a deterministic assembly of existing claims, not a new historical assertion. It does not update publication status.",
        "",
        f"Event: {event_id}",
        f"Supported claims included: {len(included)}",
        f"Unresolved core claims: {len(unresolved_core)}",
        f"Core evidence gate: {'passed for this preview' if core_gate_passed else 'NOT PASSED'}",
        "",
    ]
    if not core_claims:
        lines += ["No core claims were present; the prototype cannot pass the core evidence gate without them.", ""]
    if unresolved_core:
        lines += [
            "## Unresolved core claims",
            "",
            "These claims prevent this event from passing the prototype's core evidence gate:",
            "",
        ]
        for item in unresolved_core:
            claim_status = next((row.get("status", "unknown") for row in claims if row.get("id") == item["claim_id"]), "unknown")
            lines.append(f"- **{_markdown_safe(item['text'])}** ({item['claim_id']}; status: {claim_status}): {'; '.join(item['reasons'])}")
        lines.append("")

    if included:
        lines += ["## Narrative assembled from supported claims", ""]
        for claim, accepted in included:
            lines.append(f"- {_markdown_safe(claim['text'])}")
            for item in accepted:
                source = sources[item["source_id"]]
                url = item.get("url") or source.get("stable_url")
                title = _markdown_safe(source.get("title") or source.get("institution") or item["source_id"])
                locator = _markdown_safe(item.get("locator"))
                citation = f"[{title}](<{url}>)"
                if locator:
                    citation += f" — {locator}"
                lines.append(f"  - Evidence: {citation}")
                passage = _markdown_safe(item.get("passage"))
                lines.append(f"  - Inspected passage: “{passage[:500]}{'…' if len(passage) > 500 else ''}”")
            lines.append("")
    else:
        lines += ["## Narrative", "", "No claim passed the prototype's evidence gate, so no narrative statements were assembled.", ""]

    lines += [
        "## Limitations",
        "",
        "- This output is always a preview; a passing core evidence gate is not automatic publication approval.",
        "- Claim wording is reused verbatim; no missing facts are inferred or filled from the original AI draft.",
        "- A current inspected contradiction blocks inclusion even if a judgement says supported.",
        "- Source authority and the number of sources do not replace claim-specific passage inspection.",
        "",
    ]
    return {
        "event_id": event_id,
        "preview_only": True,
        "core_evidence_gate_passed": core_gate_passed,
        "claims_included": len(included),
        "unresolved_core_claims": unresolved_core,
        "markdown": "\n".join(lines),
    }


def load_records(records_dir):
    records_dir = Path(records_dir)
    return {key: read_jsonl(records_dir / filename) for key, filename in RECORD_FILES.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", required=True, help="Stable event ID such as event:05-opium-war-1841-example")
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    parser.add_argument("--output", type=Path, help="Create a new Markdown preview file; never overwrite")
    parser.add_argument("--require-core-evidence", action="store_true",
                        help="return exit code 1 when any core claim fails the evidence gate")
    args = parser.parse_args(argv)
    try:
        preview = build_preview(load_records(args.records_dir), args.event_id)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(preview["markdown"])
        else:
            sys.stdout.write(preview["markdown"])
        print(
            f"Preview only: {preview['claims_included']} claim(s) included; "
            f"{len(preview['unresolved_core_claims'])} unresolved core claim(s). No live data changed.",
            file=sys.stderr,
        )
        return 1 if args.require_core_evidence and not preview["core_evidence_gate_passed"] else 0
    except (OSError, ValueError) as exc:
        print(f"Narrative preview failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
