#!/usr/bin/env python3
"""V2.2 source reliability review: several models score each source independently, so the draft
scores get a second opinion and the close-call gap (source_reliability.CLOSE_CALL) is measured from the
reviewers' spread (owner rule 2026-10-20).

The reviewers see the source's description only, never the draft score, so they cannot anchor on it.
Each rates seven criteria 0-10; the score is their sum as a share of full marks. Descriptions, scores
and disputes are private research data: output goes to the private experiment branch, printed lines carry
only model names and counts.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

from score_extraction_models import ROLE, OutOfTime, load_records, open_for_trial, trial_ask

CRITERIA = (
    ("provenance", "who made it, and is that clear and accountable"),
    ("contemporaneity", "how close in time it is to the events it describes"),
    ("traceability", "does it cite or point to its own evidence"),
    ("competence", "did the author have first-hand access or expertise"),
    ("purpose", "how free it is of a stake or incentive to slant the facts (10 = none)"),
    ("completeness", "does it give the full picture rather than a selected part"),
    ("known_reliability", "its record for being right and for correcting errors"),
)
DISPUTE_GAP = 0.10  # a draft this far (share of full marks) from the reviewers' mean is listed for the owner


def describe(record):
    fields = ("title", "institution", "source_type", "source_date", "creator_perspective", "language")
    return "\n".join(f"{name}: {record[name]}" for name in fields if record.get(name))


def prompt_for(record, contested=False):
    scope = ("Rate it for CONTESTED matters: claims where the creator has a stake, or where the topic is disputed."
             if contested else "Rate it for plain facts such as dates, places, names and what happened.")
    rubric = "\n".join(f"- {name}: {what}" for name, what in CRITERIA)
    keys = ", ".join(f'"{name}": 0' for name, _ in CRITERIA)
    return (f"You rate how far a historical source can be trusted about its own subject.\n\n"
            f"Source:\n{describe(record)}\n\n{scope}\nRate each criterion from 0 (worst) to 10 (best):\n{rubric}\n\n"
            f"Answer with one JSON object only, like {{{keys}}}.")


def parse_ratings(text):
    match = re.search(r"\{.*?\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        ratings = {name: float(data[name]) for name, _ in CRITERIA}
    except (ValueError, KeyError, TypeError):
        return None
    return ratings if all(0 <= v <= 10 for v in ratings.values()) else None


def share_of(ratings):
    return sum(ratings.values()) / (10 * len(CRITERIA))


def review(asks, table, records):
    """{source_id: {kind: {model: share}}} where kind is 'plain' or 'contested' (only where the table has one)."""
    out = {}
    for source_id, entry in table["sources"].items():
        record = records.get(source_id)
        if record is None:
            continue
        kinds = [("plain", False)] + ([("contested", True)] if (entry.get("by_kind") or {}).get("contested") is not None else [])
        out[source_id] = {}
        for kind, contested in kinds:
            shares = {}
            for model, ask in asks.items():
                try:
                    ratings = parse_ratings(ask(prompt_for(record, contested)))
                except OutOfTime:
                    continue
                if ratings:
                    shares[model] = share_of(ratings)
            out[source_id][kind] = shares
    return out


def summarise(table, reviews):
    """Spread per source, the suggested close-call gap, and the draft scores that sit far from the reviewers."""
    full = table["full_marks"]
    spreads, disputes = [], []
    for source_id, kinds in reviews.items():
        entry = table["sources"][source_id]
        for kind, shares in kinds.items():
            if len(shares) < 2:
                continue
            spreads.append(max(shares.values()) - min(shares.values()))
            draft = (entry.get("by_kind") or {}).get("contested", entry["score"]) if kind == "contested" else entry["score"]
            mean = statistics.mean(shares.values())
            if abs(draft / full - mean) > DISPUTE_GAP:
                disputes.append({"source_id": source_id, "kind": kind, "draft": draft / full,
                                 "reviewers_mean": round(mean, 3), "models": len(shares)})
    return {"sources_compared": len(spreads),
            "median_spread": round(statistics.median(spreads), 3) if spreads else None,
            "suggested_close_call": round(statistics.median(spreads), 3) if spreads else None,
            "disputes": disputes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=None)
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool, QuotaExhausted, RequestRejected
    from source_reliability import load_table
    table = load_table(args.table)
    records = load_records(args.packets)
    pool = ModelPool()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    asks = {}
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        if name not in pool.routing.get(ROLE, []) or pool.remaining(name, ROLE) == 0:
            print(f"{name} | unavailable in this run")
            continue
        open_for_trial(pool, name)
        asks[name] = trial_ask(pool, name, deadline, [], [], max_rests=1)

    def guarded(ask):
        def run(prompt):
            try:
                return ask(prompt)
            except (QuotaExhausted, RequestRejected):
                raise OutOfTime() from None
        return run

    reviews = review({m: guarded(a) for m, a in asks.items()}, table, records)
    summary = summarise(table, reviews)
    args.output.write_text(json.dumps({
        "purpose": "v2.2 source reliability review by independent models; draft scores were not shown to them",
        "models": list(asks), "reviews": reviews, "summary": summary}, indent=1), encoding="utf-8")
    print(f"reviewed {len(reviews)} sources with {len(asks)} models | compared {summary['sources_compared']} | "
          f"median spread {summary['median_spread']} | disputes {len(summary['disputes'])}")
    return 0 if asks else 2


if __name__ == "__main__":
    sys.exit(main())
