#!/usr/bin/env python3
"""Consolidate the multi-AI drafts of any page, one draft at a time (owner idea 2026-10-30).

The first draft (Nemotron 3 Ultra) is the consolidated version as it stands. Each further draft is folded in:
per section, an AI (pinned through the gateway) gets the current consolidated sentences and the new draft's
sentences and writes the next version, tagging every sentence with the numbered sentences it is made from
(`[C2,N1] text`). Who backs a sentence is then recorded by the process itself: the backers of the current
sentences it uses, plus the new draft when it uses a new sentence. Code checks every fold: every current and
every new sentence is used, no number that neither input has, no model or draft names, short sentences, no
repeats, each sentence's words found in the inputs it names. Problems go back to the AI for up to MAX_TRIES
tries; then the section falls back to current + new sentences unchanged (flagged in the report). The checks
prove the text comes from the drafts, not that it is true. The writer is an AI; this program only feeds it
and checks it.

Usage (in the data checkout): consolidate_pipeline.py <page.md> <record.json> [--model ID] [--report FILE]
"""
import argparse
import http.client
import json
import os
import re
import sys
import time

import consolidate_drafts as cd

MAX_TRIES = 3
MAX_SENTENCE_WORDS = 45
RETRY_WAITS = (30, 60, 120, 240)  # seconds between tries of a call the gateway could not serve (overloaded, 5xx)
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
FORBIDDEN = re.compile(r"\b(drafts?|nemotron|gemini|gemma|claude|gpt|llama|deepseek|qwen|mistral|xing|"
                       r"other (?:ai|models?|sources?)|according to)\b", re.I)
SYSTEM = ("You merge texts about the same history topic into one flowing passage. You use only what the texts "
          "say. You never add a fact, name, date, number or explanation of your own.")
LINE = re.compile(r"^\s*\[([CN0-9,\s]+)\]\s*(.+?)\s*$")


class WriterUnavailable(Exception):
    pass


def split_sentences(text):
    from render_consolidated_facts import split_sentences as sp
    return sp(text)[1] or [text]


def fold_prompt(title, current, new, feedback=None):
    lines = [f"Section: {title}", "", "CURRENT TEXT (numbered):"]
    lines += [f"C{i}. {u['text']}" for i, u in enumerate(current, 1)]
    lines += ["", "NEW TEXT (numbered):"] + [f"N{i}. {t}" for i, t in enumerate(new, 1)]
    lines += ["", "Write the updated section: the CURRENT TEXT with everything the NEW TEXT adds worked in.",
              "Output one sentence per line. Start each line with tags in square brackets naming the numbered "
              "sentences it is made from, e.g. `[C1,C2] ...`, `[C3,N1] ...` or `[N2] ...`.",
              "Rules:",
              "- Every C and every N sentence must be used in at least one line. Nothing may be dropped.",
              "- Keep the CURRENT wording wherever the NEW TEXT adds nothing (then tag it with its C numbers only).",
              "- Put each new point where it belongs, in smooth wording. Where the NEW TEXT differs from the CURRENT "
              "TEXT, state both versions naturally (for example 'X, although another account gives Y') and tag both.",
              "- Same point in both texts: say it once and tag it with both.",
              "- Only linking words or phrases may be new. No new fact, name, number or explanation.",
              "- Never write 'draft', 'text', 'source', 'AI', 'model' or any model name.",
              "- One point per sentence, at most 35 words, and exactly one sentence per line. Do not join points with endless commas.",
              "- Output the tagged lines only: no heading, no list marks, no other text."]
    if feedback:
        lines += ["", "Your last try failed these checks, fix them:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def parse_fold(raw, n_cur, n_new):
    """[(cur_indexes, new_indexes, text)], plus problems with the tags themselves."""
    out, problems = [], []
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = LINE.match(line)
        if not m:
            problems.append(f"line without [tags]: {line[:60]}")
            continue
        cur = {int(x) for x in re.findall(r"C(\d+)", m.group(1))}
        new = {int(x) for x in re.findall(r"N(\d+)", m.group(1))}
        if not (cur or new) or any(not 1 <= i <= n_cur for i in cur) or any(not 1 <= i <= n_new for i in new):
            problems.append(f"unknown sentence number in [{m.group(1)}]")
            continue
        out.append((sorted(cur), sorted(new), m.group(2)))
    return out, problems


def check_fold(lines, current, new):
    """Problems of one folded section (empty list = passes)."""
    problems = []
    used_c = {i for c, _, _ in lines for i in c}
    used_n = {i for _, n, _ in lines for i in n}
    for i in range(1, len(current) + 1):
        if i not in used_c:
            problems.append(f"C{i} not used: {current[i - 1]['text'][:70]}")
    for i in range(1, len(new) + 1):
        if i not in used_n:
            problems.append(f"N{i} not used: {new[i - 1][:70]}")
    all_src = " ".join(u["text"] for u in current) + " " + " ".join(new)
    seen = []
    for c, n, text in lines:
        src = " ".join([current[i - 1]["text"] for i in c] + [new[i - 1] for i in n])
        for x in sorted(cd.nums(text) - cd.nums(all_src)):
            problems.append(f"number not in the texts: {x}")
        m = FORBIDDEN.search(text)
        if m and not FORBIDDEN.search(all_src):
            problems.append(f"do not write '{m.group(0)}'")
        t = cd.toks(text)
        if len(t) >= 3 and len(t & cd.toks(src)) / len(t) < 0.5:
            problems.append(f"words not found in the sentences it names: {text[:80]}")
        if len(split_sentences(text)) > 1:
            problems.append(f"two sentences on one line, give each its own line: {text[:60]}")
        if len(text.split()) > MAX_SENTENCE_WORDS:
            problems.append(f"sentence too long ({len(text.split())} words), split it: {text[:60]}")
        for prev in seen:
            if len(t) >= 4 and len(prev) >= 4 and len(t & prev) / len(t | prev) > 0.6:
                problems.append(f"repeats itself: {text[:60]}")
        seen.append(t)
    for x in sorted(cd.nums(all_src) - cd.nums(" ".join(t for _, _, t in lines))):
        problems.append(f"number missing: {x}")
    return problems


def fold_section(call, title, current, new, draft, tries=MAX_TRIES):
    """Folds one draft's sentences `new` into `current` ([{text, by}]). Returns (units, problems_left, tries)."""
    if not new:
        return current, [], 0
    if not current:
        return [{"text": t, "by": [draft]} for t in new], [], 0
    feedback, best = None, None
    for n in range(1, tries + 1):
        try:
            raw = call(SYSTEM, fold_prompt(title, current, new, feedback))
        except WriterUnavailable:
            feedback = None
            best = best or (None, ["writer unavailable"])
            continue
        lines, problems = parse_fold(raw, len(current), len(new))
        problems += check_fold(lines, current, new)
        if best is None or best[0] is None or len(problems) < len(best[1]):
            best = (lines, problems)
        if not problems:
            return units_of(lines, current, draft), [], n
        feedback = problems[:12]
    return current + [{"text": t, "by": [draft]} for t in new], best[1] or ["no usable answer"], tries


def units_of(lines, current, draft):
    units = []
    for c, n, text in lines:
        by = []
        for i in c:
            for m in current[i - 1]["by"]:
                if m not in by:
                    by.append(m)
        if n and draft not in by:
            by.append(draft)
        units.append({"text": text, "by": by})
    return units


def run(page_md, record, call, tries=MAX_TRIES):
    order = cd.draft_order(page_md)
    sections = {i: [] for i in range(7)}
    report = {"drafts": [d for d, _ in order], "folds": []}
    for k, (draft, secs) in enumerate(order):
        for i in range(7):
            units, left, used = fold_section(call, cd.CANON[i], sections[i], secs.get(i, []), draft, tries)
            sections[i] = units
            if used:  # 0 tries = nothing to merge (a section only one draft has)
                report["folds"].append({"draft": draft, "section": cd.CANON[i], "tries": used,
                                        "fallback": bool(left), "problems": left})
                print(f"[consolidate] +{draft} / {cd.CANON[i]}: {used} tries, "
                      f"{'FELL BACK' if left else 'ok'}, {len(left)} problems", flush=True)
    record["sections"] = [{"title": cd.CANON[i], "units": [dict(u, facts=cd.facts_in(u["text"], record["facts"]))
                                                           for u in sections[i]]} for i in range(7)]
    paragraphs = [f"**{i + 1}. {cd.CANON[i]}** " + " ".join(u["text"] for u in sections[i]) for i in range(7)]
    problems, uncovered = cd.check_rewrite(page_md, paragraphs)
    record["narrative"] = paragraphs
    record["sentence_ai"] = [[u["by"] for u in sections[i]] for i in range(7)]
    record["sentence_facts"] = [[cd.facts_in(u["text"], record["facts"]) for u in sections[i]] for i in range(7)]
    report.update(whole_text_problems=problems, uncovered=len(uncovered),
                  facts_in_sentences=len({f for row in record["sentence_facts"] for ids in row for f in ids}),
                  facts=len(record["facts"]), words=sum(len(p.split()) for p in paragraphs),
                  sentences=sum(len(sections[i]) for i in range(7)))
    return record, report


def gateway_call(model, token, seed=20261030):
    import multi_ai_trial as mt

    def call(system, prompt):
        body = {"capability": "llm.generate", "input": {"system": system, "prompt": prompt},
                "options": {"task": "general", "temperature": 0, "seed": seed,
                            "maxOutputTokens": mt.MAX_OUTPUT_TOKENS, "models": [model]}}
        for wait in (*RETRY_WAITS, None):
            try:
                data = mt.post_gateway(body, token, f"cons-{abs(hash(prompt))}-{time.time_ns()}")
                return mt.record_of({"id": "consolidate"}, model, data)["text"]
            except mt.QuotaExhausted as e:  # a resting model says when it is free again: wait that long (max 10 min)
                rest = mt.rest_seconds(str(e))
                if rest is None or rest > 600 or wait is None:
                    raise WriterUnavailable(str(e)[:200])
                time.sleep(rest + 5)
                continue
            except Exception as e:  # overloaded / timeout / 5xx / dropped connection: wait and ask again
                transient = isinstance(e, (OSError, http.client.HTTPException)) or \
                    re.search(r"\b(5\d\d|overloaded|timeout|rate_limited)\b", str(e))
                if not transient:  # anything else is a bug: show it
                    raise
                if wait is None:
                    raise WriterUnavailable(str(e)[:200])
                time.sleep(wait)
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
    fb = sum(f["fallback"] for f in report["folds"])
    print(f"{args.page}: {report['words']} words in {report['sentences']} sentences, {fb} of {len(report['folds'])} folds fell back, "
          f"{len(report['whole_text_problems'])} whole-text problems, {report['uncovered']} uncovered, "
          f"{report['facts_in_sentences']} of {report['facts']} facts found in sentences")
    return 1 if fb or report["whole_text_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
