#!/usr/bin/env python3
"""Consolidate the multi-AI drafts of any page into one fluent text, with automatic checks and retries.

Owner direction 2026-10-30: one reusable program that does the whole task for any topic. Per section the
writer (an AI pinned through the gateway, default Nemotron) gets the base draft and the sentences of the other
drafts that add something, and must weave them into one flowing text. It may add connectors only: no new
fact, number or name, no model or draft names, no "one draft says". Each section is checked in code; the
problems go back to the writer for up to MAX_TRIES tries, then the section falls back to the plain
base-plus-additions text (flagged in the report). The whole text then passes `consolidate_drafts.check_rewrite`.
Fact markers are placed by `consolidate_drafts.mark_facts`. The report lists every problem and fallback, so the
program can be tuned from real results. The checks prove the text comes from the drafts, not that it is true.

Usage (in the data checkout): consolidate_pipeline.py <page.md> <record.json> [--model ID] [--report FILE]
"""
import argparse
import json
import os
import re
import sys

import consolidate_drafts as cd

MAX_TRIES = 3
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a50b:free"
FORBIDDEN = re.compile(r"\b(drafts?|nemotron|gemini|gemma|claude|gpt|llama|deepseek|qwen|mistral|"
                       r"other (?:ai|models?|sources?)|according to)\b", re.I)
SYSTEM = ("You merge several texts about the same history topic into one flowing passage. You use only what "
          "the texts say. You never add a fact, name, date, number or explanation of your own.")


def section_prompt(title, base, extra, feedback=None):
    lines = [f"Section: {title}", "", "MAIN TEXT:", " ".join(base), "", "EXTRA POINTS (from other texts):"]
    lines += [f"- {s}" for _, s in extra] or ["- (none)"]
    lines += ["", "Rewrite the MAIN TEXT as one fluent passage that also includes EVERY extra point.",
              "Rules:",
              "- Keep every point of the MAIN TEXT; the result must not be shorter than it.",
              "- Work each extra point into the sentence where it belongs, in your own smooth wording.",
              "- Where an extra point differs from or contradicts the main text, state both versions naturally "
              "(for example 'X, although another account gives Y'). Do not choose between them.",
              "- Only linking words or phrases may be new. No new fact, name, number or explanation.",
              "- Never write 'draft', 'text', 'source', 'AI', 'model' or any model name.",
              "- Output the passage only: plain text, no heading, no list."]
    if feedback:
        lines += ["", "Your last try failed these checks, fix them:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def check_section(text, base, extra):
    """Problems of one written section (empty list = passes)."""
    problems = []
    srcs = " ".join(base) + " " + " ".join(s for _, s in extra)
    have = cd.toks(text)
    for n in sorted(cd.nums(text) - cd.nums(srcs)):
        problems.append(f"number not in the texts: {n}")
    for n in sorted(cd.nums(srcs) - cd.nums(text)):
        problems.append(f"number missing: {n}")
    m = FORBIDDEN.search(text)
    if m:
        problems.append(f"do not write '{m.group(0)}'")
    for who, s in list(extra) + [("main", s) for s in base]:
        t = cd.toks(s)
        if len(t) >= 3 and len(t & have) / len(t) < 0.6:
            problems.append(f"point missing: {s[:140]}")
    if len(text.split()) < sum(len(s.split()) for s in base):
        problems.append("shorter than the main text")
    return problems


def write_section(call, title, base, extra, tries=MAX_TRIES):
    """Returns (text, problems_left, tries_used); falls back to the plain merge when no try passes."""
    feedback, best = None, None
    for n in range(1, tries + 1):
        text = re.sub(r"\s+", " ", call(SYSTEM, section_prompt(title, base, extra, feedback))).strip()
        text = re.sub(r"^\**\d+\.\s*[^.]*?\**\s*", "", text) if text.startswith(("**", "#")) else text
        problems = check_section(text, base, extra)
        if best is None or len(problems) < len(best[1]):
            best = (text, problems)
        if not problems:
            return text, [], n
        feedback = problems[:12]
    plain = " ".join(base) + (" " + " ".join(s for _, s in extra) if extra else "")
    return plain, best[1], tries


def run(page_md, record, call, tries=MAX_TRIES):
    _, base, added = cd.plan(page_md)
    paragraphs, report = [], {"sections": []}
    for i in range(7):
        title = cd.CANON[i]
        text, left, used = write_section(call, title, base[i], added[i], tries)
        report["sections"].append({"section": title, "tries": used, "fallback": bool(left),
                                   "problems": left})
        paragraphs.append(f"**{i + 1}. {title}** {text}")
    problems, uncovered = cd.check_rewrite(page_md, paragraphs)
    paragraphs, placed = cd.mark_facts(paragraphs, record["facts"])
    report.update(whole_text_problems=problems, uncovered=len(uncovered),
                  facts_marked=len(placed), facts=len(record["facts"]),
                  words=sum(len(re.sub(r"\{\{[\w-]+\|", "", p).split()) for p in paragraphs))
    record["narrative"] = paragraphs
    return record, report


def gateway_call(model, token, seed=20261030):
    import multi_ai_trial as mt

    def call(system, prompt):
        body = {"capability": "llm.generate", "input": {"system": system, "prompt": prompt},
                "options": {"task": "general", "temperature": 0, "seed": seed,
                            "maxOutputTokens": mt.MAX_OUTPUT_TOKENS, "models": [model]}}
        data = mt.post_gateway(body, token, f"cons-{abs(hash(prompt))}")
        return mt.record_of({"id": "consolidate"}, model, data)["text"]
    return call


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("record")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--report")
    args = ap.parse_args(argv)
    page_md = open(args.page, encoding="utf-8").read()
    record = json.load(open(args.record, encoding="utf-8"))
    record, report = run(page_md, record, gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"]))
    json.dump(record, open(args.record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fb = sum(s["fallback"] for s in report["sections"])
    print(f"{args.page}: {report['words']} words, {fb} of 7 sections fell back, "
          f"{len(report['whole_text_problems'])} whole-text problems, {report['uncovered']} uncovered, "
          f"{report['facts_marked']} of {report['facts']} facts marked")
    return 1 if fb or report["whole_text_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
