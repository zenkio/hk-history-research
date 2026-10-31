#!/usr/bin/env python3
"""A 10-year-old's reading of a consolidated record (owner 2026-10-31).

Before a page goes public an AI reads it as a ten-year-old and lists the words and points it cannot follow
("what is 行館?", "who is Elliot?"). The questions are kept in `record["questions"]`, one per term and language,
so the answer can be researched later (the reader asks no outside source here). A term the record's `glossary`
already explains is not asked again. English and Chinese are read apart because a term can be easy in one language
and hard in the other. The AI only asks; it never answers or changes the text. Code checks the answer form and that
the term really stands in the sentence it names.

Usage (in the data checkout): kid_read_consolidated.py <record.json> [--model ID] [--report FILE]
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import consolidate_pipeline as cp

SYSTEM = ("You are a curious ten-year-old who reads a history text. You say honestly which words and points you "
          "do not understand. You never answer your own questions and never use knowledge to explain.")
LINE = re.compile(r"^\s*Q\s*\[(\d+)\]\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$")
MARK = re.compile(r"[⟦⟧]")
LANGS = {"en": "English", "zh": "Traditional Chinese (Hong Kong)"}


def prompt(lang, title, texts):
    lines = [f"Section: {title}", "", "TEXT (numbered sentences):"] + [f"[{i}] {t}" for i, t in enumerate(texts, 1)]
    lines += ["", f"You are ten years old and read this text in {LANGS[lang]}. List up to 8 words, names or points you "
              "cannot follow: a hard word, a person or place you do not know, a custom or idea nobody explains, "
              "or a claim that makes you wonder why. One per line, in exactly this form:",
              f"Q [n] | the term, copied exactly from sentence n | your question as a child, in {LANGS[lang]}",
              "If you understand everything, answer `NONE`. Output only those lines."]
    return "\n".join(lines)


def ask(call, lang, title, texts, tries=cp.MAX_TRIES):
    """[(sentence number, term, question)] whose term really stands in the sentence; None if never well formed."""
    for _ in range(tries):
        try:
            raw = call(SYSTEM, prompt(lang, title, texts))
        except cp.WriterUnavailable:
            continue
        if raw.strip().upper() == "NONE":
            return []
        found = [m.groups() for m in map(LINE.match, raw.splitlines()) if m]
        got = [(int(n), t.strip("「」\"' "), q) for n, t, q in found
               if 1 <= int(n) <= len(texts) and t.strip("「」\"' ") in texts[int(n) - 1]]
        if got:
            return got
    return None


def run(record, call, model="", tries=cp.MAX_TRIES):
    known = {t.lower() for t in record.get("glossary", {})}
    jobs = []
    for s, sec in enumerate(record["sections"]):
        for lang in LANGS:
            units = sec["units"]
            if lang == "zh" and not all(u.get("zh") for u in units):
                continue
            texts = [MARK.sub("", u["zh"]) if lang == "zh" else u["text"] for u in units]
            jobs.append((s, lang, texts))
    with ThreadPoolExecutor(cp.PARALLEL_SECTIONS) as pool:
        results = list(pool.map(lambda j: ask(call, j[1], record["sections"][j[0]]["title"], j[2], tries), jobs))
    questions, seen, unread = [], set(), 0
    for (s, lang, texts), got in zip(jobs, results):
        if got is None:
            unread += 1
            continue
        for n, term, question in got:
            key = (lang, term.lower())
            if key in seen or term.lower() in known:
                continue
            seen.add(key)
            questions.append({"id": f"kid-{len(questions) + 1}", "lang": lang, "applies_to": [lang], "term": term,
                              "question": question, "section": record["sections"][s]["title"],
                              "sentence": record["sections"][s]["units"][n - 1]["text"], "asked_by": "kid-reader",
                              "judged_by": model, "status": "open", "answer": None})
    record["questions"] = questions
    return record, {"questions": len(questions), "unread": unread,
                    "by_lang": {l: sum(q["lang"] == l for q in questions) for l in LANGS},
                    "terms": [(q["lang"], q["term"]) for q in questions]}


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
    print(f"{args.record}: {report['questions']} question(s), {report['unread']} section reading(s) unread")
    return 0 if not report["unread"] else 1


if __name__ == "__main__":
    sys.exit(main())
