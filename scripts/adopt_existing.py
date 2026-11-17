#!/usr/bin/env python3
"""Bring the earlier AI pages into the multi-AI pages (owner 2026-11-17: treat the existing pages as one more AI's
version of the same topic, so the many pages already written can be enriched by the pipeline).

The old timeline pages (content/01_Timeline/**, tag `ai-draft`) are written in another shape (Background, What happened,
Significance, Perspectives). For each multi-AI page this step finds the earlier pages about the same event (same year,
at least two distinctive words of the title in common), asks the writer model ONCE per earlier page to restate it under
the seven headings of the multi-AI drafts without adding anything, and appends the restatement to the page as one more
callout. The label is the model the old page names in its `draft_model` (never a guess: if it names none, "Earlier page").
The page text changes, so the queue's fold step folds the new draft into the current version as for any draft.

Used by consolidate_queue.py --plan. Needs AI_GATEWAY_TOKEN. Free models only.
"""
import os
import re
from pathlib import Path

import consolidate_pipeline as cp
import draft_page as dp
import multi_ai_trial as mt
import page_status as ps

TIMELINE = Path("content/01_Timeline")
PER_RUN = 6  # earlier pages restated in one run (one call each)
MARK = "<!-- adopted: "
GENERIC = {"the", "of", "and", "in", "to", "a", "an", "on", "for", "hong", "kong", "first", "establishment", "formal",
           "opening", "signing", "founding", "formation", "construction", "introduction", "ai", "draft"}

SYSTEM = "You restate history pages faithfully. You never add a fact that the page does not contain."


def words(slug):
    return {w for w in re.split(r"[^a-z]+", slug.lower()) if len(w) > 2 and w not in GENERIC}


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    fm = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():] if m else text


def related(slug, year, root=Path(".")):
    """Earlier pages about the same event: same year and two distinctive title words (or one if the topic has one)."""
    want = words(re.sub(r"-?\d{4}$", "", slug))
    need = min(2, len(want))
    out = []
    for path in sorted((root / TIMELINE).rglob("*.md")):
        if path.name == "index.md":
            continue
        fm, _ = front_matter(path.read_text(encoding="utf-8"))
        if str(fm.get("year", "")) != str(year) or "ai-draft" not in fm.get("tags", ""):
            continue
        if need and len(want & words(re.sub(r"^\d{4}-", "", path.stem))) >= need:
            out.append(path)
    return out


def prompt(topic_title, body):
    return (f"Topic: {topic_title}\n\nBelow is an earlier page about this topic. Restate what it says under these "
            "headings, using only what the page says. Leave out a heading the page has nothing for. Keep every figure, "
            "date and name. Do not add background from your own knowledge.\n"
            "1. What happened: when, where, who, in short.\n2. Background: why it happened.\n"
            "3. Hong Kong at this time.\n4. China at this time.\n5. Britain at this time.\n6. Consequences.\n"
            "7. Uncertain or disputed points.\n\n--- page ---\n" + body.strip())


def label_of(fm, taken):
    base = fm.get("draft_model", "").split(";")[0].strip() or "Earlier page"
    label, n = base, 1
    while label in taken:  # callout labels must be unique: the fold records who backs each sentence by label
        n += 1
        label = f"{base} #{n}"
    return label, base


def adopt_page(slug, call, root=Path("."), limit=PER_RUN):
    """Appends the restated earlier pages to the multi-AI page `slug`; returns how many were added."""
    path = root / ps.PAGES / f"{slug}.md"
    text = path.read_text(encoding="utf-8")
    fm, _ = front_matter(text)
    year = fm.get("year")
    title = fm.get("title", slug)
    added = 0
    for old in related(slug, year, root):
        mark = f"{MARK}{old.relative_to(root).as_posix()} -->"
        if mark in text or added >= limit:
            continue
        ofm, body = front_matter(old.read_text(encoding="utf-8"))
        taken = set(re.findall(r"^> \[!info\]- (.+?)(?::| \(|$)", text, re.M))
        label, base = label_of(ofm, taken)
        answer = call(SYSTEM, prompt(title, body))
        if len(answer.split()) < 80:  # an empty or cut-off restatement is not a draft
            continue
        text = text.rstrip("\n") + "\n\n" + dp.callout(label, base, answer).replace(
            "asked for through the AI gateway, temperature 0, seed %s" % dp.SEED,
            f"restated from the earlier page {old.stem} ({ofm.get('draft_model', 'model not named')})") + f"\n{mark}\n"
        added += 1
    if added:
        path.write_text(text, encoding="utf-8")
    return added


def adopt_pending(root=Path("."), token=None, model=dp.REQUIRED[0], limit=PER_RUN, gateway=None):
    """Every page of the queue that has earlier pages not yet brought in; returns {slug: pages added}."""
    token = token or os.environ.get("AI_GATEWAY_TOKEN", "")
    call = (gateway or cp.gateway_call)(model, token, seed=dp.SEED, fallbacks=[])
    queue = ps.load(root / dp.QUEUE, {})
    done, budget = {}, limit
    for slug in queue.get("pages", []):
        if budget <= 0 or not (root / ps.PAGES / f"{slug}.md").exists():
            continue
        try:
            n = adopt_page(slug, call, root, budget)
        except cp.WriterUnavailable as e:
            print(f"[adopt] {slug}: the writer is unavailable ({str(e)[:80]}); the rest waits for the next run", flush=True)
            break
        if n:
            done[slug] = n
            budget -= n
            print(f"[adopt] {slug}: {n} earlier page(s) brought in as drafts", flush=True)
    return done
