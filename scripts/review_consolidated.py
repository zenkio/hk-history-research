#!/usr/bin/env python3
"""Find sentences of a consolidated record that contradict other sentences of the same page (owner 2026-10-31).

The fold only guarantees nothing was dropped; it cannot see that a sentence one AI wrote says the opposite of
what the others say (e.g. China "importing British tea" where five drafts have Britain importing Chinese tea).
Here an AI (pinned through the gateway) reads every numbered sentence of the page and lists sentences that
cannot both be true with another sentence, one line each: `[n] conflicts with [m]: short reason`. Code checks
the numbers exist and differ and the reason is non-empty; each flagged unit gets `conflict: {with, note}` and the
page shows it as disputed. Different figures or dates that the text already presents as separate accounts
("another account gives ...") are not conflicts. This is an AI judgement, recorded as such (`judged_by`), not a
finding of fact.

Usage (in the data checkout): review_consolidated.py <record.json> [--model ID] [--report FILE]
"""
import argparse
import json
import os
import re
import sys

import consolidate_pipeline as cp

SYSTEM = ("You check a history text for internal contradictions. You use only what the numbered sentences say, "
          "never outside knowledge of your own about what is true.")
LINE = re.compile(r"^\s*\[(\d+)\]\s*conflicts? with\s*\[(\d+)\]\s*:\s*(.+?)\s*$", re.I)


def flat(record):
    return [u for sec in record["sections"] for u in sec["units"]]


def prompt(units):
    lines = ["Below are numbered sentences from one page about one topic.", "",
             "List every sentence that cannot be true at the same time as another sentence in the list, because "
             "it says the opposite (who did what to whom, which direction something went, whether something "
             "happened). Do not list sentences that only add detail, or that give a different date or figure "
             "as a separate account (for example 'another account gives ...').",
             "Output one line per conflict: `[n] conflicts with [m]: short reason`, where [n] is the sentence "
             "that stands apart from the rest and [m] one it conflicts with. If there is none, output `NONE`.", ""]
    return "\n".join(lines + [f"[{i}] {u['text']}" for i, u in enumerate(units, 1)])


def parse(raw, count):
    found, problems = [], []
    for line in raw.splitlines():
        if not line.strip() or line.strip().upper().startswith("NONE"):
            continue
        m = LINE.match(line)
        if not m:
            problems.append(f"not a conflict line: {line[:60]}")
            continue
        n, other, note = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= n <= count and 1 <= other <= count) or n == other:
            problems.append(f"bad numbers in: {line[:60]}")
            continue
        found.append((n, other, note))
    return found, problems


def run(record, call, model="", tries=cp.MAX_TRIES):
    units = flat(record)
    feedback, problems = [], []
    for attempt in range(1, tries + 1):
        raw = call(SYSTEM, prompt(units) + ("\n\nFix these problems in your last answer:\n- " + "\n- ".join(feedback)
                                            if feedback else ""))
        found, problems = parse(raw, len(units))
        if not problems:
            break
        feedback = problems
    else:
        return record, {"reviewed": False, "problems": problems, "conflicts": 0}
    for u in units:
        u.pop("conflict", None)
    for n, other, note in found:
        units[n - 1]["conflict"] = {"with": [units[other - 1]["text"]], "note": note, "judged_by": model}
    tally = {}  # per AI: sentences it backs that were flagged, of all the sentences it backs (a rating input)
    for u in units:
        for ai in u.get("by", []):
            row = tally.setdefault(ai, {"flagged": 0, "sentences": 0})
            row["sentences"] += 1
            row["flagged"] += bool(u.get("conflict"))
    return record, {"reviewed": True, "problems": [], "conflicts": len(found), "by_ai": tally,
                    "flagged": [{"text": units[n - 1]["text"], "with": units[o - 1]["text"], "note": note}
                                for n, o, note in found]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--report")
    args = ap.parse_args(argv)
    record = json.load(open(args.record, encoding="utf-8"))
    record, report = run(record, cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"]), args.model)
    json.dump(record, open(args.record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{args.record}: reviewed={report['reviewed']}, {report['conflicts']} conflicting sentence(s)")
    return 0 if report["reviewed"] else 1


if __name__ == "__main__":
    sys.exit(main())
