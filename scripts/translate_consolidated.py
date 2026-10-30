#!/usr/bin/env python3
"""Add a Traditional Chinese (Hong Kong) version to a consolidated record, sentence by sentence (owner 2026-10-30).

The English consolidated text stays the master. Per section an AI (pinned through the gateway) translates the
numbered sentences, one line each, so `unit["zh"]` lines up with `unit["text"]` and the backers recorded for the
English sentence hold for the translation. Code checks every answer: same number of lines, Chinese characters in
each, every number of the English sentence present, no Latin words beyond the names the sentence itself has.
Problems go back to the AI for up to MAX_TRIES tries; a section that still fails keeps no translation (the page
shows its English). The checks prove the translation is complete and keeps the figures, not that it is good.

Usage (in the data checkout): translate_consolidated.py <record.json> [--model ID] [--report FILE]
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import consolidate_pipeline as cp

MAX_TRIES = cp.MAX_TRIES
SYSTEM = ("You translate English history text into Traditional Chinese as written in Hong Kong. You translate "
          "faithfully: you add nothing, drop nothing and keep every number, date and name.")
CJK = re.compile(r"[一-鿿]")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
LINE = re.compile(r"^\s*\[(\d+)\]\s*(.+?)\s*$")


def prompt(title, texts, feedback=None):
    lines = [f"Section: {title}", "", "Translate each numbered sentence into Traditional Chinese (Hong Kong usage, "
             "standard Chinese names for people, places and treaties).", "Output exactly one line per sentence: "
             "`[n] translation`, with the same numbers, in the same order. No other text.", "Keep every figure and "
             "date as in the English. Do not merge or split sentences.", ""]
    lines += [f"[{i}] {t}" for i, t in enumerate(texts, 1)]
    if feedback:
        lines += ["", "Your previous answer had these problems; fix them:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def numbers(text):
    return [n.replace(",", "") for n in NUMBER.findall(text)]


def check(raw, texts):
    found = {}
    for line in raw.splitlines():
        m = LINE.match(line)
        if m:
            found[int(m.group(1))] = m.group(2)
    problems = []
    if set(found) != set(range(1, len(texts) + 1)):
        problems.append(f"expected lines [1] to [{len(texts)}], got {sorted(found)}")
        return [], problems
    out = [found[i] for i in range(1, len(texts) + 1)]
    for i, (en, zh) in enumerate(zip(texts, out), 1):
        if not CJK.search(zh):
            problems.append(f"[{i}] is not Chinese")
        zh_numbers = numbers(zh)
        missing = [n for n in numbers(en) if n not in zh_numbers and n not in zh.replace(",", "")]
        if missing:
            problems.append(f"[{i}] lost the number(s) {', '.join(missing)}")
    return out, problems


def translate_section(call, title, texts, tries=MAX_TRIES):
    if not texts:
        return [], [], 0
    feedback, problems = None, []
    for attempt in range(1, tries + 1):
        out, problems = check(call(SYSTEM, prompt(title, texts, feedback)), texts)
        if not problems:
            return out, [], attempt
        feedback = problems
    return [], problems, tries


def run(record, call, tries=MAX_TRIES):
    report = {"sections": []}
    sections = record["sections"]
    started = time.time()
    with ThreadPoolExecutor(cp.PARALLEL_SECTIONS) as pool:
        results = list(pool.map(lambda s: translate_section(call, s["title"], [u["text"] for u in s["units"]], tries),
                                sections))
    for sec, (zh, left, used) in zip(sections, results):
        for unit, line in zip(sec["units"], zh):
            unit["zh"] = line
        if not zh:
            for unit in sec["units"]:
                unit.pop("zh", None)
        report["sections"].append({"section": sec["title"], "tries": used, "translated": bool(zh), "problems": left})
        print(f"[translate] {sec['title']}: {used} tries, {'ok' if zh else 'NOT TRANSLATED'}, "
              f"{len(left)} problems", flush=True)
    print(f"[translate] done in {int(time.time() - started)} s", flush=True)
    return record, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--report")
    args = ap.parse_args(argv)
    record = json.load(open(args.record, encoding="utf-8"))
    record, report = run(record, cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"]))
    json.dump(record, open(args.record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    failed = [s for s in report["sections"] if not s["translated"]]
    print(f"{args.record}: {len(report['sections']) - len(failed)} of {len(report['sections'])} sections translated")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
