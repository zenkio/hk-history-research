#!/usr/bin/env python3
"""Quality gate for a consolidated record (owner 2026-11-03: the pipeline must find and fix its own defects).

Free, deterministic detectors (no AI call) run after the last step of a page. Each finding names the step that can
repair it, the section and the place, so the status runner redoes only that part (tidy for one section, translate for
the sentences concerned, reader questions for one section and language). A page gets GATE_ROUNDS repair rounds; a
finding that is still there after them goes to the issue list for a person or Claude. Every defect the owner finds by
reading becomes a detector here with a test (see docs of the status runner), so the same defect is never found by hand
twice. Findings carry no page text beyond 60 characters.

Detectors: repeat (the same point twice), fragment (sentence cut or not finished), too_long, leaked (AI/draft/model
words), missing_zh, cantonese, english_in_zh, title_zh (page or section heading not translated or colloquial),
stale_question (question whose sentence is gone, colloquial Cantonese, or term not in its sentence).
"""
import consolidate_pipeline as cp
import tidy_consolidated as td
import translate_consolidated as tc

END_ZH = ("。", "！", "？", "」", "）", "”", ".", "』")


def short(text):
    return text[:60]


def check(record):
    """[{check, step, section, where, detail}] for the whole record; empty = clean."""
    found = []

    def add(check, step, section, where, detail=""):
        found.append({"check": check, "step": step, "section": section, "where": where, "detail": short(detail)})
    for sec in record.get("sections", []):
        name, units = sec["title"], sec["units"]
        for i, j in td.near_duplicates([u["text"] for u in units]):
            add("repeat", "tidy", name, i, units[i]["text"])
        for i, u in enumerate(units):
            text = u["text"].strip()
            why = td.bad_sentence(text)
            if why:
                add(why, "tidy", name, i, text)
            zh = u.get("zh")
            if not zh:
                add("missing_zh", "translate", name, i, text)
                continue
            if cp.cantonese(zh):
                add("cantonese", "translate", name, i, zh)
            if tc.MONTH.search(zh) or tc.ENGLISH_WORD.search(tc.MARK.sub("", zh)):
                add("english_in_zh", "translate", name, i, zh)
            if not zh.strip().endswith(END_ZH):
                add("fragment", "translate", name, i, zh)
        if not sec.get("title_zh") or cp.cantonese(sec.get("title_zh", "")):
            add("title_zh", "translate", name, "section title", name)
    if record.get("title") and (not record.get("title_zh") or cp.cantonese(record["title_zh"])):
        add("title_zh", "translate", "(page)", "page title", record["title"])
    texts = {sec["title"]: [u["text"] for u in sec["units"]] for sec in record.get("sections", [])}
    for q in record.get("questions", []):
        gone = q["sentence"] not in texts.get(q["section"], [])
        if gone or (q["lang"] == "zh" and cp.cantonese(q["question"])) or \
                (q["lang"] == "en" and q["term"] not in q["sentence"]):
            add("stale_question", "kidread", q["section"], q["id"], q["question"])
    return found


def summary(findings):
    out = {}
    for f in findings:
        out[f["check"]] = out.get(f["check"], 0) + 1
    return out


def steps_to_repair(findings):
    return sorted({f["step"] for f in findings}, key=["tidy", "translate", "kidread"].index)
