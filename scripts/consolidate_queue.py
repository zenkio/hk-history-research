#!/usr/bin/env python3
"""Runs the multi-AI page pipeline from a list of pages by itself (owner 2026-11-03): pick up the pages that still
need a step, do only that step, heal what can heal, and surface what cannot.

The list is `data/consolidated_queue.json` in the data checkout: {"pages": ["peking-1860", ...], "minutes": 150,
"max_steps": 12}. An empty "pages" means every page of content/05_Multi_AI. Per page `page_status.run_page` does
only the missing steps. Self-healing, all bounded so a run never loops or burns the quota:
- the gateway model overloaded (step `waiting`): the page is simply tried again next run; two pages in a row
  waiting stops the run (circuit breaker) instead of hammering a down model;
- a step accepted with gaps is forgotten and run once more on a later run (HEAL_LIMIT);
- a crash in one page is caught and logged; the other pages go on; after CRASH_LIMIT crashes the page is
  quarantined until someone clears it.
Anything that is not healed lands in `data/consolidated_status/_issues.json` (kind, page, step, count, first/last
seen, short detail, never page text) for a person or Claude to pick up. Log lines carry names and counts only.

Usage (in the data checkout): consolidate_queue.py [--model ID] [--minutes N] [--max-steps N] [--show] [--clear PAGE]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import consolidate_pipeline as cp
import page_status as ps

QUEUE = Path("data/consolidated_queue.json")
ISSUES = ps.STATUS / "_issues.json"
HEAL_LIMIT = 1
CRASH_LIMIT = 3
WAIT_STOP = 2  # pages in a row left waiting before the run stops


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def record_issue(issues, kind, page, step, detail):
    e = issues.setdefault(f"{page}|{step}|{kind}", {"kind": kind, "page": page, "step": step, "count": 0,
                                                    "heals": 0, "first": now()})
    e.update(count=e["count"] + 1, last=now(), detail=str(detail)[:200], open=True)
    return e


def close_issues(issues, page, keep):
    """Closes the page's issues that are no longer true (keep = keys still true)."""
    for key, e in issues.items():
        if e["page"] == page and key not in keep and e.get("kind") != "crash":
            e["open"] = False


def pages_of(root, queue):
    names = queue.get("pages") or sorted(p.stem for p in (root / ps.PAGES).glob("*.md") if p.stem != "index")
    return [n for n in names if (root / ps.PAGES / f"{n}.md").exists()]


def heal(root, page, issues):
    """Forgets a step that was accepted with gaps, once, so it runs again."""
    status = ps.load(root / ps.STATUS / f"{page}.json", {})
    for step in ps.STEPS:
        s = status.get(step, {})
        e = issues.get(f"{page}|{step}|gaps")
        if s.get("state") == "accepted" and s.get("gaps") and e and e.get("heals", 0) < HEAL_LIMIT:
            e["heals"] += 1
            ps.retry(page, [step], root)
            print(f"[queue] {page}: healing {step} (once)", flush=True)
            return


def run_queue(call, model="", root=Path("."), minutes=150, max_steps=12, clock=time.time):
    queue = ps.load(root / QUEUE, {})
    issues = ps.load(root / ISSUES, {})
    started, waiting_in_row, done = clock(), 0, []
    for page in pages_of(root, queue):
        if clock() - started > minutes * 60:
            print("[queue] time budget used, the rest waits for the next run", flush=True)
            break
        crash = issues.get(f"{page}|run|crash")
        if crash and crash.get("open") and crash["count"] >= CRASH_LIMIT:
            continue  # quarantined
        page_md = (root / ps.PAGES / f"{page}.md").read_text(encoding="utf-8")
        heal(root, page, issues)
        if ps.next_step(ps.load(root / ps.STATUS / f"{page}.json", {}), page_md) is None:
            continue
        try:
            ran = ps.run_page(page, call, model, max_steps, root)
        except Exception as e:  # one bad page must not stop the others
            record_issue(issues, "crash", page, "run", f"{type(e).__name__}: {e}")
            print(f"[queue] {page}: crashed ({type(e).__name__})", flush=True)
            ps.save(root / ISSUES, issues)
            continue
        done.append((page, ran))
        status = ps.load(root / ps.STATUS / f"{page}.json", {})
        keep = set()
        for step in ps.STEPS:
            s = status.get(step, {})
            if s.get("state") == "waiting":
                keep.add(f"{page}|{step}|waiting")
                record_issue(issues, "waiting", page, step, "; ".join(s.get("gaps", [])))
            elif s.get("state") == "accepted" and s.get("gaps"):
                key = f"{page}|{step}|gaps"
                keep.add(key)
                if key not in issues:
                    record_issue(issues, "gaps", page, step, f"{len(s['gaps'])} gaps: " + "; ".join(s["gaps"][:3]))
                else:
                    issues[key].update(open=True, last=now())
        for check, n in (status.get("gate", {}).get("counts") or {}).items():  # defects the gate could not repair
            keep.add(f"{page}|{check}|quality")
            record_issue(issues, "quality", page, check, f"{n} finding(s) left after the repair rounds")
        close_issues(issues, page, keep)
        ps.save(root / ISSUES, issues)
        waiting_in_row = waiting_in_row + 1 if any(f"{page}|{s}|waiting" in keep for s in ps.STEPS) else 0
        if waiting_in_row >= WAIT_STOP:
            record_issue(issues, "gateway", "*", "run", f"{WAIT_STOP} pages in a row stayed waiting; run stopped")
            print("[queue] the writer model stays unavailable: run stopped (circuit breaker)", flush=True)
            break
    ps.save(root / ISSUES, issues)
    return done, issues


def summary(issues):
    open_ = [e for e in issues.values() if e.get("open")]
    return {k: sum(1 for e in open_ if e["kind"] == k) for k in ("crash", "waiting", "gaps", "gateway", "quality")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--minutes", type=int)
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--plan", action="store_true", help="afterwards, if the queue is nearly empty, let the AI propose missing topics")
    ap.add_argument("--clear", help="forget the crash record of a page so it runs again")
    args = ap.parse_args(argv)
    root = Path(".")
    if args.clear:
        issues = ps.load(root / ISSUES, {})
        for k in [k for k, e in issues.items() if e["page"] == args.clear and e["kind"] == "crash"]:
            issues.pop(k)
        ps.save(root / ISSUES, issues)
        return 0
    queue = ps.load(root / QUEUE, {})
    if args.show:
        print(json.dumps({"summary": summary(ps.load(root / ISSUES, {})),
                          "pages": [ps.show(p, root) for p in pages_of(root, queue)]}, ensure_ascii=False))
        return 0
    call = cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"])
    done, issues = run_queue(call, args.model, root, args.minutes or queue.get("minutes", 150),
                             args.max_steps or queue.get("max_steps", 12))
    print(f"[queue] pages worked: {len(done)}; open issues: {json.dumps(summary(issues))}", flush=True)
    if args.plan:
        import plan_queue
        plan_queue.plan(call, args.model, root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
