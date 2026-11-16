#!/usr/bin/env python3
"""Make the page of a proposed topic (owner 2026-11-16: the pipeline picks topics itself, covers every event first,
then enriches). `plan_queue` only writes a work order; this step turns the next proposals into pages.

For the next topics (status "approved" in `order`, then "proposed") each draft model is asked the same prompt as the
multi-AI trial, pinned and with no fallback (a fallback model would be a different draft). The page holds the drafts
exactly as produced in the callout format `consolidate_drafts` reads; the usual queue steps (fold, tidy, translate,
review, kidread) then run on it. Nemotron 3 Ultra's draft is required (the fold builds on it): if it is unavailable the
topic waits for the next run. Other draft models are optional and skipped on any error. Free models only; the page is
an AI draft, unverified, like every multi-AI page.

Used by consolidate_queue.py --plan, before the queue works. Needs AI_GATEWAY_TOKEN.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import consolidate_pipeline as cp
import multi_ai_trial as mt
import page_status as ps

QUEUE = Path("data/consolidated_queue.json")
PER_RUN = 3  # new pages made in one queue run (drafting costs one call per model; the steps after it cost far more)
REQUIRED = ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra")
OPTIONAL = [("gemini-3.5-flash", "Gemini 3.5 Flash")]
SEED = mt.DEFAULT_SEED


def next_topics(queue, root, limit=PER_RUN):
    """Proposals still without a page: approved ones by `order`, then proposed ones in the order they were made."""
    # "page-exists" with no file is a page lost with a run that did not save it (2026-11-16): draft it again
    todo = [p for p in queue.get("proposals", []) if p.get("status") in ("approved", "proposed", "page-exists")
            and not (root / ps.PAGES / f"{p['slug']}.md").exists()]
    todo.sort(key=lambda p: (p["status"] == "proposed", p.get("order", 10**6)))
    return todo[:limit]


def callout(label, model, text):
    body = "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip().splitlines())
    return (f"> [!info]- {label}: AI draft, unverified\n"
            f"> _Model `{model}`; asked for through the AI gateway, temperature 0, seed {SEED}; "
            f"{len(text.split())} words_\n>\n{body}\n")


def page_text(topic, drafts):
    """The page: the front matter, the usual warning and the drafts as the models wrote them."""
    year, title = topic["year"], topic["title"].replace('"', "'")
    names = "; ".join(label for label, _, _ in drafts)
    reason = topic.get("reason", "").replace('"', "'")
    lines = ["---", f'title: "{title}"', f"date: {year}-01-01", f"year: {year}",
             "date_precision: year", f'era: "{reason[:80]}"',
             f'tags: ["ai-draft", "multi-ai", "unverified", "{year}"]',
             f'summary: "{title} ({year}): what happened, the background and what followed. Unverified draft."',
             f'description: "{title} ({year}): what happened, the background and what followed. Unverified draft."',
             "confidence: ai-draft", "origin: ai", "verification_status: unverified",
             f'draft_model: "{names}"', f"ingested: {datetime.now(timezone.utc):%Y-%m-%d}", "---", "",
             "> [!warning] AI draft — research hypothesis",
             "> AI-generated summary from a discovered source. It has not been independently verified against "
             "inspectable historical evidence; treat it as a research lead, not established history.",
             '<a class="status-badge status-draft" href="/05_multi_ai/method">Draft · not yet checked against sources</a>',
             "", "**Where this sits on the timeline:** "
             f"{reason or title}. Part of the [[05_Multi_AI/index|path from China to British rule and back]].",
             "", "<!-- consolidated-facts -->", "", "## The drafts", "",
             "Click a heading to open a draft. Texts are kept exactly as the model produced them.", ""]
    return "\n".join(lines) + "\n" + "\n".join(callout(label, model, text) for label, model, text in drafts)


def draft_topic(topic, token, gateway=None):
    """(label, model, text) for each model that answered; Nemotron's draft is required."""
    event = {"id": topic["slug"], "title": topic["title"], "year": topic["year"]}
    drafts = []
    for model, label in [REQUIRED, *OPTIONAL]:
        call = (gateway or cp.gateway_call)(model, token, seed=SEED, fallbacks=[])
        try:
            text = call("You write factual drafts for a history timeline. Say when you are unsure.", mt.prompt_for(event))
        except cp.WriterUnavailable:
            if model == REQUIRED[0]:
                raise
            print(f"[draft] {label} unavailable for this topic: skipped", flush=True)
            continue
        except Exception as e:  # an optional model the gateway cannot serve (e.g. 422): the page goes on without it
            if model == REQUIRED[0]:
                raise
            print(f"[draft] {label} failed ({cp._why(e)}): skipped", flush=True)
            continue
        if len(text.split()) >= 150:  # a cut-off or empty answer is not a draft
            drafts.append((label, model, text))
        elif model == REQUIRED[0]:
            raise cp.WriterUnavailable("the required draft came back too short")
    return drafts


def draft_pending(root=Path("."), token=None, limit=PER_RUN, gateway=None):
    """Make the pages of the next topics; returns the slugs made. A topic whose required draft fails waits."""
    token = token or os.environ.get("AI_GATEWAY_TOKEN", "")
    queue = ps.load(root / QUEUE, {})
    made = []
    for topic in next_topics(queue, root, limit):
        try:
            drafts = draft_topic(topic, token, gateway)
        except cp.WriterUnavailable as e:
            print(f"[draft] {topic['slug']}: the required draft is unavailable ({str(e)[:80]}); waits for the next run", flush=True)
            break
        if not drafts or drafts[0][1] != REQUIRED[0]:
            break
        path = root / ps.PAGES / f"{topic['slug']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page_text(topic, drafts), encoding="utf-8")
        topic["status"] = "page-exists"
        if queue.get("pages") is not None and topic["slug"] not in queue["pages"]:
            queue["pages"].append(topic["slug"])
        made.append(topic["slug"])
        ps.save(root / QUEUE, queue)  # saved after every page: a later crash keeps it
        print(f"[draft] page {topic['slug']} made from {len(drafts)} drafts", flush=True)
    return made
