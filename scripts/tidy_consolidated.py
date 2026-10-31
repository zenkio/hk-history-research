#!/usr/bin/env python3
"""Merge near-duplicate sentences of a consolidated record (owner 2026-10-31).

Folding keeps every sentence of every draft, so five drafts that all say "mixed with lime and salt and flushed
into the sea" leave five almost identical sentences in a row. Per section, an AI (pinned through the gateway)
gets the numbered sentences and writes the section again, one line per point, tagged with the sentences it is
made from (`[C1,C4] ...`): sentences that say the same thing become one, and a difference that matters (sea or
Pearl River, a different figure) stays visible in the wording. The same program checks as the fold apply (every
sentence used, no number or name not in the sentences, nothing shrunk to a hint, short, no repeats); the backers
of a merged sentence are the union of its sources' backers. A section that fails its checks keeps its sentences
unchanged. Sentences that only AIs on a low-trust list back (none for now: owner 2026-10-31 wants weak AIs kept until there is proof)
may be left out (`[C5] OMIT`); they are kept in `record["omitted"]`, never deleted. Translations and review flags belong to the old sentences, so merged sentences have none and the
translate and review steps run again after this one.

Usage (in the data checkout): tidy_consolidated.py <record.json> [--model ID] [--report FILE]
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import consolidate_drafts as cd
import consolidate_pipeline as cp

LOW_TRUST = []  # AIs whose lone sentences may be left out. Empty (owner 2026-10-31: no proof a weak AI is wrong, keep them); needs a rating first
OMIT = "OMIT"
SYSTEM = ("You tidy a history text by merging sentences that say the same thing. You use only what the "
          "sentences say. You never add a fact, name, date, number or explanation of your own.")


def omittable(unit, low_trust):
    """A sentence that only low-trust AIs back may be left out of the merged text."""
    return bool(unit.get("by")) and set(unit["by"]) <= set(low_trust)


def prompt(title, units, low_trust, feedback=None):
    lines = [f"Section: {title}", "", "SENTENCES (numbered, with how many AIs back each):"]
    for i, u in enumerate(units, 1):
        n = len(u["by"])
        mark = f" [backed only by a low-trust AI: may be {OMIT}ted]" if omittable(u, low_trust) else ""
        lines.append(f"C{i}. {u['text']} (backed by {n} AI{'s' if n != 1 else ''}){mark}")
    lines += ["", "Write the section again so that sentences about the same point become ONE sentence.",
              "Output one sentence per line, each starting with tags in square brackets naming the numbered "
              "sentences it is made from, e.g. `[C1,C4] ...`.", "Rules:",
              "- Every sentence must be used in at least one line, or be left out by writing `[C5] " + OMIT + "` "
              "(only allowed for sentences marked as omittable).",
              "- Sentences that differ only slightly (a range against a single figure, a loose date against an exact "
              "one, a slightly different method) are one point: state the version most AIs back, and add the other "
              "version in brackets, e.g. 'into the sea (another account: the Pearl River)', 'about 1,200 tonnes "
              "(another account: 1,000 to 1,200)', 'June to July 1839 (another account: 3 to 25 June)'.",
              "- Do not repeat the same point in several sentences.",
              "- A sentence about a different point stays on its own line, unchanged.",
              "- Only linking words and the bracketed alternatives may be new. No new fact, name, number or explanation.",
              "- Never write 'draft', 'text', 'source', 'AI', 'model' or a model name.",
              "- At most 40 words per sentence, exactly one sentence per line.",
              "- Output the tagged lines only: no heading, no list marks, no other text."]
    if feedback:
        lines += ["", "Your last try failed these checks, fix them:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


CHUNK = 7  # a long section is tidied in runs of this many neighbouring sentences: the AI drops sentences from long lists


def tidy_section(call, title, units, tries=cp.MAX_TRIES, low_trust=LOW_TRUST, omitted=None):
    """(units, problems_left, tries). A long section is tidied chunk by chunk; a chunk that fails keeps its sentences."""
    if len(units) <= CHUNK + 2:
        return tidy_chunk(call, title, units, tries, low_trust, omitted)
    out, left, used = [], [], 0
    for k in range(0, len(units), CHUNK):
        chunk, problems, n = tidy_chunk(call, title, units[k:k + CHUNK], tries, low_trust, omitted)
        out += chunk
        left += problems
        used = max(used, n)
    return out, left, used


def tidy_chunk(call, title, units, tries=cp.MAX_TRIES, low_trust=LOW_TRUST, omitted=None):
    if len(units) < 2:
        return units, [], 0
    feedback, problems = None, []
    for n in range(1, tries + 1):
        try:
            raw = call(SYSTEM, prompt(title, units, low_trust, feedback))
        except cp.WriterUnavailable:
            problems = ["writer unavailable"]
            continue
        # a model sometimes thinks aloud before the answer: only the tagged lines count
        tagged = "\n".join(x for x in raw.splitlines() if cp.LINE.match(x))
        lines, problems = cp.parse_fold(tagged, len(units), 0)
        left_out = {i for c, _, text in lines if text.strip().upper() == OMIT for i in c}
        for i in sorted(left_out):
            if not omittable(units[i - 1], low_trust):
                problems.append(f"C{i} may not be left out: it is backed by more than low-trust AIs")
        # for the checks a left-out sentence counts as used, with its own words
        kept = [(c, nn, text) for c, nn, text in lines if text.strip().upper() != OMIT]
        problems += cp.check_fold(kept + [([i], [], units[i - 1]["text"]) for i in sorted(left_out)], units, [])
        if not problems:
            merged = carry(cp.units_of(kept, units, None), units)
            if omitted is not None:
                omitted += [dict(units[i - 1], reason="only low-trust AIs back it") for i in sorted(left_out)]
            return merged, [], n
        feedback = problems[:12]
    return units, problems, tries


def carry(merged, old):
    """A sentence that came through unchanged keeps its translation, flag and facts."""
    by_text = {u["text"]: u for u in old}
    return [dict(by_text[u["text"]], by=u["by"]) if u["text"] in by_text else u for u in merged]


def run(record, call, tries=cp.MAX_TRIES, low_trust=LOW_TRUST):
    sections = record["sections"]
    gone = [[] for _ in sections]  # per section, so the parallel workers never share a list
    with ThreadPoolExecutor(cp.PARALLEL_SECTIONS) as pool:
        results = list(pool.map(lambda k: tidy_section(call, sections[k]["title"], sections[k]["units"], tries,
                                                       low_trust, gone[k]), range(len(sections))))
    record["omitted"] = [dict(u, section=sections[k]["title"]) for k in range(len(sections)) for u in gone[k]]
    report = {"sections": [], "omitted": len(record["omitted"])}
    for sec, (units, left, used) in zip(sections, results):
        before = len(sec["units"])
        sec["units"] = [u if "facts" in u else dict(u, facts=cd.facts_in(u["text"], record["facts"])) for u in units]
        report["sections"].append({"section": sec["title"], "before": before, "after": len(units), "tries": used,
                                   "fallback": bool(left), "problems": left})
        print(f"[tidy] {sec['title']}: {before} -> {len(units)} sentences, {used} tries, "
              f"{'KEPT AS IT WAS' if left else 'ok'}", flush=True)
    record["narrative"] = [f"**{i + 1}. {s['title']}** " + " ".join(u["text"] for u in s["units"])
                           for i, s in enumerate(sections)]
    record["sentence_ai"] = [[u["by"] for u in s["units"]] for s in sections]
    record["sentence_facts"] = [[u["facts"] for u in s["units"]] for s in sections]
    return record, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--report")
    ap.add_argument("--low-trust", nargs="*", default=LOW_TRUST, help="AIs whose lone sentences may be left out")
    args = ap.parse_args(argv)
    record = json.load(open(args.record, encoding="utf-8"))
    record, report = run(record, cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"]), low_trust=args.low_trust)
    json.dump(record, open(args.record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    kept = [s for s in report["sections"] if s["fallback"]]
    print(f"{args.record}: {sum(s['before'] for s in report['sections'])} -> "
          f"{sum(s['after'] for s in report['sections'])} sentences, {len(kept)} section(s) unchanged")
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
