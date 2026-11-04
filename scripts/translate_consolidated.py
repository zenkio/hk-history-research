#!/usr/bin/env python3
"""Add a Traditional Chinese (Hong Kong) version to a consolidated record, sentence by sentence (owner 2026-10-30).

The English consolidated text stays the master. Per section an AI (pinned through the gateway) translates the
numbered sentences, one line each, so `unit["zh"]` lines up with `unit["text"]` and the backers recorded for the
English sentence hold for the translation. Code checks every answer: same number of lines, Chinese characters in
each, every number of the English sentence present, no lower-case English words left over.
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
ENGLISH_WORD = re.compile(r"\b[a-z]{3,}\b")  # a lower-case English word left untranslated
MONTH = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", re.I)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
END_ZH = ("。", "！", "？", "」", "）", "”", ".", "』")
MARK = re.compile(r"⟦([^⟦⟧]+)⟧")  # proper-name mark (專名號): the renderer draws these names underlined
LINE = re.compile(r"^\s*\[(\d+)\]\s*(.+?)\s*$")


def prompt(title, texts, feedback=None):
    lines = [f"Section: {title}", "", "Translate each numbered sentence into Traditional Chinese (Hong Kong usage, "
             "standard Chinese names for people, places and treaties).", "Output exactly one line per sentence: "
             "`[n] translation`, with the same numbers, in the same order. No other text.", "Wrap every proper name in "
             "⟦ ⟧ as the Chinese proper-name mark (專名號): names of people, places, countries, dynasties and "
             "organisations, e.g. ⟦林則徐⟧, ⟦虎門⟧, ⟦大清⟧. Never mark the name of a treaty, declaration or other document: write it "
             "in 《 》 instead, e.g. 《南京條約》. Not common words.", "Keep every figure and "
             "date as in the English. Do not merge or split sentences.", cp.WRITTEN_CHINESE, ""]
    lines += [f"[{i}] {t}" for i, t in enumerate(texts, 1)]
    if feedback:
        lines += ["", "Your previous answer had these problems; fix them:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def numbers(text):
    return [n.replace(",", "") for n in NUMBER.findall(text)]


DOC_WORDS = r"(?:條約|條例|協定|協議|宣言|聲明|公約|章程|法案|諭令?|詔書?|通商章程)"
DOC_MARK = re.compile(r"⟦([^⟦⟧]*" + DOC_WORDS + r")⟧")


def fix_marks(zh):
    """Names of documents (treaties, declarations) take the title mark 《 》, not the name underline (owner 2026-11-04:
    ⟦北京條約⟧ is wrong); a mark inside 《 》 is dropped. Deterministic, so no AI call is needed for it."""
    zh = re.sub(r"《([^》]*)》", lambda m: "《" + MARK.sub(r"\1", m.group(1)) + "》", zh)
    return DOC_MARK.sub(r"《\1》", zh)


def normalize_record(record):
    """fix_marks on every Chinese text of the record; returns how many texts changed."""
    changed = 0
    def fix(holder, key):
        nonlocal changed
        old = holder.get(key)
        if old and (new := fix_marks(old)) != old:
            holder[key], changed = new, changed + 1
    fix(record, "title_zh")
    for sec in record["sections"]:
        fix(sec, "title_zh")
        for u in sec["units"]:
            fix(u, "zh")
    return changed


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
        if MARK.sub("", zh).count("⟦") or MARK.sub("", zh).count("⟧"):
            problems.append(f"[{i}] has an unmatched or nested ⟦ ⟧")
        if not CJK.search(zh):
            problems.append(f"[{i}] is not Chinese")
        slang = cp.cantonese(zh)
        if slang:
            problems.append(f"[{i}] uses colloquial Cantonese ({', '.join(slang[:3])}): write standard written Chinese")
        left = ENGLISH_WORD.findall(zh) + MONTH.findall(zh)  # "1 July 1997" must read 1997年7月1日
        if left:
            problems.append(f"[{i}] left English words untranslated: {', '.join(left[:3])}")
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
        try:
            raw = call(SYSTEM, prompt(title, texts, feedback))
        except cp.WriterUnavailable:  # the gateway model is overloaded: this section is left for the next run
            problems = ["writer unavailable"]
            continue
        out, problems = check(raw, texts)
        if not problems:
            return [fix_marks(x) for x in out], [], attempt
        feedback = problems
    return [], problems, tries


def translate_titles(call, record, tries=MAX_TRIES):
    """Traditional Chinese for the page title (`record["title"]`) and every section title (owner 2026-11-03:
    headings are translated too). Stored as record["title_zh"] and section["title_zh"]. [] = done, else the problems."""
    names = ([record["title"]] if record.get("title") else []) + [s["title"] for s in record["sections"]]
    have = ([record.get("title_zh")] if record.get("title") else []) + [s.get("title_zh") for s in record["sections"]]
    if not names or all(h and not cp.cantonese(h) for h in have):
        return []
    problems = []
    for _ in range(tries):
        try:
            raw = call(SYSTEM, prompt("Headings of one page", names, problems or None))
        except cp.WriterUnavailable:
            problems = ["writer unavailable"]
            continue
        out, problems = check(raw, names)
        if not problems:
            out = [fix_marks(x) for x in out]
            if record.get("title"):
                record["title_zh"], out = out[0], out[1:]
            for sec, zh in zip(record["sections"], out):
                sec["title_zh"] = zh
            return []
    return problems


def run(record, call, tries=MAX_TRIES, only_missing=True):
    """Translates the sections that still have an untranslated sentence (owner 2026-10-31: do only what is missing)."""
    report = {"sections": []}
    for sec in record["sections"]:  # a Chinese sentence from before the English-month check is translated again
        for u in sec["units"]:
            zh = u.get("zh")
            if zh and (MONTH.search(zh) or cp.cantonese(zh) or ENGLISH_WORD.search(MARK.sub("", zh))
                       or not zh.strip().endswith(END_ZH)):
                u.pop("zh")
    sections = [s for s in record["sections"] if not only_missing or not all(u.get("zh") for u in s["units"])]
    started = time.time()
    wanted = [[u for u in s["units"] if not only_missing or not u.get("zh")] for s in sections]  # only the sentences that lack Chinese
    with ThreadPoolExecutor(cp.PARALLEL_SECTIONS) as pool:
        results = list(pool.map(lambda sw: translate_section(call, sw[0]["title"], [u["text"] for u in sw[1]], tries),
                                zip(sections, wanted)))
    for sec, units, (zh, left, used) in zip(sections, wanted, results):
        for unit, line in zip(units, zh):
            unit["zh"] = line
        report["sections"].append({"section": sec["title"], "tries": used, "translated": bool(zh), "problems": left,
                                   "sentences": len(units)})
        print(f"[translate] {sec['title']}: {len(units)} sentences, {used} tries, {'ok' if zh else 'NOT TRANSLATED'}, "
              f"{len(left)} problems", flush=True)
    report["title_problems"] = translate_titles(call, record, tries)
    print(f"[translate] headings: {'ok' if not report['title_problems'] else 'NOT TRANSLATED'}", flush=True)
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
