#!/usr/bin/env python3
"""AI proofreading for the quality gate (owner 2026-11-03: programs alone miss problems; the verify may use AI too).

The program checks (quality_gate.py) find what rules can find. Some defects only a reader sees: the same point told in
different words, a Chinese sentence that says something else than the English, Chinese that is not written standard
Chinese in a way no word list catches, a sentence nobody can follow. After the program checks are clean, an AI
(pinned through the gateway) reads each section, English with its Chinese beside it, and reports problems only from
a fixed list, one line each: `F [n] | category | reason` or `F [n,m] | same_point | reason`. Code validates every line
(numbers inside the section, known category, two numbers for a repeat) and turns it into a finding for the step that can
repair it. The AI proofreader only points; it never rewrites the text. A section whose text did not change since a clean
reading is not read again (`record["ai_verified"]`), and every verdict is stored with model and date, so how often the
proofreader is right can be measured later. AI agreement is not evidence about history: it checks writing, not facts.
"""
import hashlib
import re
from datetime import datetime, timezone

import consolidate_pipeline as cp

CATEGORIES = {"same_point": "tidy", "confusing": "tidy", "unfaithful": "translate", "not_written_chinese": "translate"}
MAX_PER_SECTION = 6
LINE = re.compile(r"^\s*F\s*\[([\d,\s]+)\]\s*\|\s*([a-z_]+)\s*\|\s*(.+?)\s*$")
SYSTEM = ("You proofread a bilingual history text (English and Traditional Chinese for Hong Kong readers). You only "
          "point at problems; you never rewrite and never judge whether the history is true.")


def prompt(title, units, with_zh):
    lines = [f"Section: {title}", "", "SENTENCES (English" + (" || Traditional Chinese" if with_zh else "") + "):"]
    for i, u in enumerate(units, 1):
        lines.append(f"[{i}] {u['text']}" + (f" || {u['zh']}" if with_zh and u.get("zh") else ""))
    lines += ["", "Report problems of these kinds only, one line each, in exactly this form:",
              "`F [n,m] | same_point | reason` : sentences n and m tell the same point in different words.",
              "`F [n] | confusing | reason` : sentence n cannot be followed or contradicts its neighbours.",
              "`F [n] | unfaithful | reason` : the Chinese of n says something different from its English "
              "(a different fact, number, name or meaning, or something added or dropped).",
              "`F [n] | not_written_chinese | reason` : the Chinese of n is colloquial Cantonese, mixes languages "
              "or reads unnaturally; it should be standard written Chinese.",
              f"At most {MAX_PER_SECTION} lines. Report only clear problems, not style preferences. "
              "If there is nothing to report, answer `NONE`. Output only those lines."]
    return "\n".join(lines)


def parse(raw, n_units):
    """[(indexes (0-based), category, reason)] from the AI's answer; lines that do not validate are dropped."""
    out = []
    for line in raw.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        idx = [int(x) for x in re.findall(r"\d+", m.group(1))]
        cat = m.group(2)
        if cat not in CATEGORIES or not idx or any(not 1 <= i <= n_units for i in idx):
            continue
        if (cat == "same_point") != (len(idx) == 2) or (cat == "same_point" and idx[0] == idx[1]):
            continue
        out.append(([i - 1 for i in idx[:2]], cat, m.group(3)[:80]))
    return out[:MAX_PER_SECTION]


def fingerprint(units):
    return hashlib.sha256("\n".join(u["text"] + "|" + (u.get("zh") or "") for u in units).encode()).hexdigest()[:12]


def verify(record, call, model=""):
    """(findings, stats). Findings are in the quality gate's format, with check `ai:<category>`."""
    done = record.setdefault("ai_verified", {})
    findings, read, unavailable = [], 0, False
    for sec in record["sections"]:
        units, fp = sec["units"], fingerprint(sec["units"])
        if done.get(sec["title"]) == fp:
            continue  # unchanged since a clean reading
        try:
            raw = call(SYSTEM, prompt(sec["title"], units, all(u.get("zh") for u in units)))
        except cp.WriterUnavailable:
            unavailable = True
            continue
        read += 1
        got = [] if raw.strip().upper() == "NONE" else parse(raw, len(units))
        if not got:
            done[sec["title"]] = fp
        for idx, cat, reason in got:
            findings.append({"check": f"ai:{cat}", "step": CATEGORIES[cat], "section": sec["title"], "where": idx[0],
                             "pair": idx, "detail": reason[:60]})
    stats = {"model": model, "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "sections_read": read,
             "flagged": len(findings), "unavailable": unavailable}
    return findings, stats


def apply(record, findings):
    """Prepares the repair of AI findings: a flagged translation is dropped (translate redoes only that sentence), a
    flagged repeat or confusing sentence is handed to tidy for that section (`review_flags`)."""
    flags = record.setdefault("review_flags", {})
    for f in findings:
        if not f["check"].startswith("ai:"):
            continue
        sec = next(s for s in record["sections"] if s["title"] == f["section"])
        if f["step"] == "translate":
            sec["units"][f["where"]].pop("zh", None)
        else:
            flags.setdefault(f["section"], []).append(f["pair"] if f["check"] == "ai:same_point" else [f["where"]])
