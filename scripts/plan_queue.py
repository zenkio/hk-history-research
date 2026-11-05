#!/usr/bin/env python3
"""AI planning step for the page queue (owner 2026-11-03): decide what should be added from what we have and
have not, so the queue does not depend on a hand-made list.

It collects what exists (the multi-AI pages with title and year, the eras and page counts of the timeline, the
owner's focus topics and what is already proposed) and asks one gateway model which topics are missing. Code checks
every proposal (slug form, year range, not already a page or proposal, a hard cap per run and in total) and
appends the survivors to `data/consolidated_queue.json` under "proposals" with status "proposed". A proposal whose
page now exists is moved into "pages" so the queue runner works on it. Proposals are only a work order: they
write no page and change nothing public. One free call per planning run, and planning happens only when the queue
is nearly empty (LOW_WATER pages with open steps), so it never competes with page work for the daily quota.
The prompt keeps the owner's rules: the order of work in the focus topics, no living private people and no
ongoing criminal cases, no claims, only topic titles.

Usage (in the data checkout): plan_queue.py [--model ID] [--show]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import consolidate_pipeline as cp
import page_status as ps

QUEUE = Path("data/consolidated_queue.json")
FOCUS = Path("research/FOCUS_TOPICS.md")
TIMELINE = Path("content/01_Timeline")
MAX_NEW = 5  # proposals taken from one planning call
MAX_OPEN = 10  # proposals waiting at any time
LOW_WATER = 1  # plan only when at most this many pages still have an open step
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}$")
LINE = re.compile(r"^\s*P\s*\|\s*([a-z0-9-]+)\s*\|\s*(.+?)\s*\|\s*(\d{4})\s*\|\s*(.+?)\s*$")
SYSTEM = ("You plan the work order for a Hong Kong history timeline. You name topics (events, treaties, "
          "movements) that are missing; you write no history and make no factual claims.")


def title_of(path):
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        if line.startswith("title:"):
            return line[6:].strip().strip("\"'")
    return path.stem


def inventory(root):
    pages = [f"{p.stem}: {title_of(p)}" for p in sorted((root / ps.PAGES).glob("*.md"))
             if p.stem not in ("index", "method")]
    eras = []
    if (root / TIMELINE).is_dir():
        for d in sorted(x for x in (root / TIMELINE).iterdir() if x.is_dir()):
            eras.append(f"{d.name}: {sum(1 for _ in d.glob('*.md'))} pages")
    focus = ""
    if (root / FOCUS).exists():
        focus = (root / FOCUS).read_text(encoding="utf-8")[:3500]
    return pages, eras, focus


def prompt(pages, eras, focus, proposals):
    return "\n".join([
        "Multi-AI topic pages we already have (slug: title):", *(pages or ["(none)"]), "",
        "Timeline eras we have (folder: number of pages):", *(eras or ["(none)"]), "",
        "Topics already proposed (slug: title):", *([f"{p['slug']}: {p['title']}" for p in proposals] or ["(none)"]), "",
        "The owner's focus topics and order of work:", focus or "(none)", "",
        f"Name up to {MAX_NEW} topics that are missing and should be added next, following the owner's order of "
        "work (core story first: territory changes 1839-1997, then the Cultural Revolution and 1967, 1989, and "
        "districts last). Each topic is one dated event or treaty a reader could look up. Do not repeat anything "
        "above. No ongoing criminal cases and no living private people. Write no history, only the topic.",
        "Output exactly one line per topic: `P | slug | title | year | reason` where slug is lower-case words "
        "joined by hyphens ending in the year (e.g. `convention-of-chuenpi-1841`), year is four digits, reason is "
        "one short sentence on why it is missing. No other text."])


def check(raw, existing_slugs, existing_titles):
    """Valid new proposals from the model's answer and the lines it got wrong."""
    good, bad = [], []
    for line in raw.splitlines():
        if not line.strip().startswith("P"):
            continue
        m = LINE.match(line)
        if not m:
            bad.append("unreadable line")
            continue
        slug, title, year, reason = m.groups()
        if not SLUG.match(slug) or not slug.endswith(year) or not 1800 <= int(year) <= 2025:
            bad.append(f"{slug}: bad slug or year")
        elif slug in existing_slugs or title.lower() in existing_titles:
            bad.append(f"{slug}: already there")
        else:
            good.append({"slug": slug, "title": title, "year": int(year), "reason": reason[:200]})
            existing_slugs.add(slug)
            existing_titles.add(title.lower())
    return good[:MAX_NEW], bad


def open_pages(root, queue):
    names = queue.get("pages") or [p.stem for p in (root / ps.PAGES).glob("*.md") if p.stem not in ("index", "method")]
    n = 0
    for name in names:
        f = root / ps.PAGES / f"{name}.md"
        if f.exists() and ps.next_step(ps.load(root / ps.STATUS / f"{name}.json", {}), f.read_text(encoding="utf-8")):
            n += 1
    return n


def promote(root, queue):
    """Proposals whose page now exists go into the queue's pages."""
    for p in queue.get("proposals", []):
        if p["status"] == "proposed" and (root / ps.PAGES / f"{p['slug']}.md").exists():
            p["status"] = "page-exists"
            queue.setdefault("pages", [])
            if queue["pages"] and p["slug"] not in queue["pages"]:
                queue["pages"].append(p["slug"])
    return queue


def plan(call, model, root=Path(".")):
    queue = promote(root, ps.load(root / QUEUE, {}))
    proposals = queue.setdefault("proposals", [])
    waiting = sum(1 for p in proposals if p["status"] == "proposed")
    if open_pages(root, queue) > LOW_WATER or waiting >= MAX_OPEN:
        ps.save(root / QUEUE, queue)
        print(f"[plan] enough work queued ({open_pages(root, queue)} pages open, {waiting} proposals): no new call", flush=True)
        return []
    pages, eras, focus = inventory(root)
    slugs = {p.split(":")[0] for p in pages} | {p["slug"] for p in proposals}
    titles = {p["title"].lower() for p in proposals} | {p.split(": ", 1)[-1].lower() for p in pages}
    try:
        raw = call(SYSTEM, prompt(pages, eras, focus, proposals))
    except cp.WriterUnavailable:
        print("[plan] the writer model is unavailable: planning waits for the next run", flush=True)
        return []
    good, bad = check(raw, slugs, titles)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for g in good[:MAX_OPEN - waiting]:
        proposals.append(dict(g, status="proposed", proposed_by=model, at=at))
    ps.save(root / QUEUE, queue)
    print(f"[plan] {len(good)} topics proposed, {len(bad)} lines refused", flush=True)
    return good


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)
    if args.show:
        print(json.dumps(ps.load(QUEUE, {}).get("proposals", []), ensure_ascii=False, indent=1))
        return 0
    plan(cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"]), args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
