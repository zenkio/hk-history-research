#!/usr/bin/env python3
"""Find sentences of a consolidated record that contradict other sentences of the same page (owner 2026-10-31).

The fold only guarantees nothing was dropped; it cannot see that a sentence one AI wrote says the opposite of
what the others say (e.g. China "importing British tea" where five drafts have Britain importing Chinese tea).
One call over the whole page missed this, so each sentence is checked on its own against the few sentences that
share most words with it (an AI pinned through the gateway answers `CONFLICT [n]: reason` or `NONE`). Code
checks the answer form and that [n] is one of the sentences shown; each flagged unit gets `conflict: {with, note}` and the
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

SYSTEM = ("You check one history sentence against related sentences from the same page. You use only what the "
          "sentences say, never outside knowledge of your own about what is true.")
ANSWER = re.compile(r"^\s*(?:CONFLICT\s*\[(\d+)\]\s*:\s*(.+?)|NONE)\s*$", re.I | re.S)
RELATED = 6  # related sentences shown with each sentence
STOP = set("the a an of in to and was were is are for on at by with as that this it its from which their his her "
           "had has have be been who not but or also after before into over under than then".split())


def flat(record):
    return [u for sec in record["sections"] for u in sec["units"]]


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def related(units, i):
    """The sentences sharing the most content words with sentence i (so a reversed relation sits beside its twin)."""
    mine = words(units[i]["text"])
    scored = sorted(((len(mine & words(u["text"])), j) for j, u in enumerate(units) if j != i), reverse=True)
    return [j for score, j in scored[:RELATED] if score]


def backing(unit):
    n = len(unit.get("by", []))
    return f" (backed by {n} AI{'s' if n != 1 else ''})"


def prompt(sentence, others, own="", backed=()):
    lines = ["SENTENCE:", sentence + own, "", "RELATED SENTENCES:"] + [
        f"[{k}] {t}{b}" for k, (t, b) in enumerate(zip(others, backed or [""] * len(others)), 1)]
    lines += ["", "How many AIs back a sentence is only a hint where to look, never proof that it is right: "
              "look hardest when a sentence backed by few AIs differs from related sentences backed by many.", "Does SENTENCE say the opposite of a related sentence, so that both cannot be true: who did what "
              "to whom, which direction something went, whether something happened? Different dates or figures given "
              "as separate accounts, extra detail, or a related sentence about another aspect of the same subject "
              "are NOT conflicts. A sentence that says something was absent in one respect does not conflict "
              "with one that says it was present in another respect.",
              "Answer with exactly one line: `CONFLICT [n]: short reason` naming the related sentence, or `NONE`."]
    return "\n".join(lines)


def review_one(call, units, i, tries):
    others = related(units, i)
    if not others:  # nothing to conflict with
        return None, True
    feedback = ""
    for _ in range(tries):
        raw = call(SYSTEM, prompt(units[i]["text"], [units[j]["text"] for j in others], backing(units[i]),
                                  [backing(units[j]) for j in others]) + feedback).strip()
        m = ANSWER.match(raw.splitlines()[0] if raw else "")
        if m and not m.group(1):
            return None, True
        if m and 1 <= int(m.group(1)) <= len(others):
            return (others[int(m.group(1)) - 1], m.group(2)), True
        feedback = "\n\nYour last answer was not in the required form. Answer with one line only."
    return None, False


def run(record, call, model="", tries=cp.MAX_TRIES):
    from concurrent.futures import ThreadPoolExecutor
    units = flat(record)
    with ThreadPoolExecutor(cp.PARALLEL_SECTIONS) as pool:
        results = list(pool.map(lambda i: review_one(call, units, i, tries), range(len(units))))
    flagged, unreviewed = [], 0
    for i, (hit, ok) in enumerate(results):
        units[i].pop("conflict", None)
        unreviewed += not ok
        if hit:
            j, note = hit
            units[i]["conflict"] = {"with": [units[j]["text"]], "note": note, "judged_by": model}
            flagged.append({"text": units[i]["text"], "with": units[j]["text"], "note": note})
    tally = {}  # per AI: sentences it backs that were flagged, of all the sentences it backs (a rating input)
    for u in units:
        for ai in u.get("by", []):
            row = tally.setdefault(ai, {"flagged": 0, "sentences": 0})
            row["sentences"] += 1
            row["flagged"] += bool(u.get("conflict"))
    return record, {"reviewed": unreviewed == 0, "unreviewed": unreviewed, "conflicts": len(flagged),
                    "by_ai": tally, "flagged": flagged}


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
