#!/usr/bin/env python3
"""Status of each multi-AI page and a runner that does only the next missing step (owner 2026-10-31).

A page is made in steps: fold (drafts into one text), tidy (merge near-duplicates), translate (Traditional
Chinese), review (flag conflicting sentences), kidread (questions a general reader would ask). Each step keeps in
`data/consolidated_status/<page>.json` its state, when and by which model it ran, the fingerprint of the input it
used (`input`) and of the sentences it left (`after`). A step is current while the `after` of the step before it
equals its `input`; a new draft changes the fold's input, so everything after it becomes stale. A step that ran but
left gaps (a section not merged, a sentence not translated) is `partial` and is repeated, up to MAX_ATTEMPTS, then
accepted as it is, so a page never loops. Only the steps that are stale or missing run, one page after another,
within a budget of steps; the status is saved after every step.

Usage (in the data checkout): page_status.py <page> [<page> ...] [--model ID] [--max-steps N] [--show] [--adopt fold,tidy,...] [--retry translate,...]
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import consolidate_pipeline as cp
import run_control as rc
import kid_read_consolidated as kr
import quality_gate as qg
import ai_verify as av
import review_consolidated as rv
import tidy_consolidated as td
import translate_consolidated as tc

STEPS = ["fold", "tidy", "translate", "review", "kidread"]
MAX_ATTEMPTS = 2
GATE_ROUNDS = 2  # repair rounds the quality gate may start for one page
PAGES = Path("content/05_Multi_AI")
RECORDS = Path("data/consolidated_facts")
STATUS = Path("data/consolidated_status")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def texts_hash(record):
    return digest([[u["text"] for u in s["units"]] for s in record.get("sections", [])])


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def expected_input(step, status, page_md):
    """The fingerprint this step must have used to be current; None while the step before it has not finished."""
    if step == "fold":
        return digest(page_md)
    before = status.get(STEPS[STEPS.index(step) - 1], {})
    return before.get("after") if before.get("state") in ("done", "accepted") else None


def next_step(status, page_md):
    """The first step that is missing or stale, or None when the page is complete."""
    for step in STEPS:
        want = expected_input(step, status, page_md)
        if want is None:
            return None  # an earlier step is still open (cannot happen if we walk in order)
        now = status.get(step, {})
        if now.get("state") in ("done", "accepted") and now.get("input") == want:
            continue
        if now.get("input") == want and now.get("state") in ("partial", "failed") and now.get("attempts", 0) >= MAX_ATTEMPTS:
            status[step] = dict(now, state="accepted")  # gaps stay, the page moves on
            continue
        return step
    return None


def gaps(step, record, report):
    """Gaps a step left, from its report and the record (empty = clean)."""
    if step == "fold":
        return [f"{f['draft']} / {f['section']}" for f in report.get("folds", []) if f["fallback"]] + report.get("whole_text_problems", [])
    if step == "tidy":
        return [s["section"] for s in report["sections"] if s["fallback"]] + \
            [f"{s['section']} (repeats left: {s['repeats']})" for s in report["sections"] if s.get("repeats")]
    if step == "translate":
        return [f"{s['title']}" for s in record["sections"] if not all(u.get("zh") for u in s["units"])] + \
            [f"headings: {p}" for p in report.get("title_problems", [])[:3]]
    if step == "review":
        return [] if report.get("reviewed") else [f"{report.get('unreviewed')} sentences not reviewed"]
    return [] if not report.get("unread") else [f"{report['unread']} readings unread"]


def execute(step, page_md, record, call, model, repair=False):
    if step == "fold":
        return cp.run(page_md, record, call)
    if step == "tidy":
        return td.run(record, call, only_problems=repair)  # a repeat run only redoes the sections that still have a problem
    if step == "translate":
        title = next((l[6:].strip().strip("\"'") for l in page_md.splitlines()[:12] if l.startswith("title:")), "")
        if title and record.get("title") != title:
            record["title"], _ = title, record.pop("title_zh", None)
        return tc.run(record, call)
    if step == "review":
        return rv.run(record, call, model)
    return kr.run(record, call, model, only_problems=repair)


def forget(status, steps):
    """Marks steps to run again; the next run of each is a repair that redoes only what is wrong."""
    for step in steps:
        status[step] = {"state": "forgotten", "attempts": 0, "gaps": [], "input": None, "after": None,
                        "model": status.get(step, {}).get("model", "")}


def run_page(page, call, model="", max_steps=12, root=Path("."), ctl=None):
    """Runs up to max_steps open steps of one page; returns the names of the steps it ran."""
    page_md = (root / PAGES / f"{page}.md").read_text(encoding="utf-8")
    rec_path, st_path = root / RECORDS / f"{page}.json", root / STATUS / f"{page}.json"
    record = load(rec_path, {"facts": [], "sections": []})
    status = load(st_path, {})
    ran = []
    while len(ran) < max_steps:
        step = next_step(status, page_md)
        if ctl is not None and step is not None and (why := ctl.reason_to_stop()):
            print(f"[status] {page}: not starting {step}: {why}", flush=True)
            break
        if step is None:  # every step is current: the quality gate looks for defects and starts a repair round
            if tc.normalize_record(record):  # free, deterministic text fixes first (e.g. treaty names in 《 》, not underlined)
                save(rec_path, record)
            findings = qg.check(record)
            ai = None
            if not findings and call is not None and (ctl is None or not ctl.reason_to_stop()):  # the program checks are clean: the AI proofreader reads what rules cannot judge
                findings, ai = av.verify(record, ctl.wrap(call, page, "gate") if ctl else call, model)
                av.apply(record, findings)
                save(rec_path, record)
            gate = status.get("gate", {})
            rounds = gate.get("rounds", 0)
            status["gate"] = {"rounds": rounds, "counts": qg.summary(findings), "findings": findings[:25], "ai": ai,
                              "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            # a step already accepted with gaps was given up on: its defects wait in the issue list, not another round
            fixable = [s for s in qg.steps_to_repair(findings) if status.get(s, {}).get("state") != "accepted"]
            if findings and fixable and rounds < GATE_ROUNDS:
                status["gate"]["rounds"] = rounds + 1
                forget(status, fixable)
                print(f"[status] {page}: quality gate round {rounds + 1}: {qg.summary(findings)}", flush=True)
                continue
            if not findings:
                status["gate"]["rounds"] = 0  # clean: a later new defect gets its rounds again
            break
        overloaded = []

        base = ctl.wrap(call, page, step) if ctl is not None else call

        def counted(system, user, _call=base):  # remembers that the gateway model failed during this step
            try:
                return _call(system, user)
            except cp.WriterUnavailable:
                overloaded.append(1)
                raise
        try:
            record, report = execute(step, page_md, record, counted if call is not None else None, model,
                                     repair=step in status)
        except rc.Stopped as e:  # paused / budget spent / signal: leave the step open, the next run resumes it
            print(f"[status] {page}: {step} left open: {e}", flush=True)
            break
        except cp.WriterUnavailable as e:  # the gateway model stays overloaded: wait, do not count an attempt
            prev = status.get(step, {})
            status[step] = {"state": "waiting", "attempts": prev.get("attempts", 0), "gaps": [str(e)[:120]],
                            "model": model, "input": expected_input(step, status, page_md), "after": None,
                            "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            save(st_path, status)
            print(f"[status] {page}: {step} waiting, the writer model is unavailable", flush=True)
            break
        left = gaps(step, record, report)
        prev = status.get(step, {})
        attempts = prev.get("attempts", 0) + 1 if prev.get("input") == expected_input(step, status, page_md) else 1
        if left and overloaded:  # the model was down, not the text bad: this try does not use up the attempts
            attempts = prev.get("attempts", 0) if prev.get("input") == expected_input(step, status, page_md) else 0
        status[step] = {"state": "partial" if left else "done", "attempts": attempts, "gaps": left[:10], "model": model,
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "input": expected_input(step, status, page_md), "after": texts_hash(record)}
        save(rec_path, record)  # a checkpoint after every step
        save(st_path, status)
        ran.append(step)
        print(f"[status] {page}: {step} -> {status[step]['state']} (attempt {attempts}, {len(left)} gaps)", flush=True)
        if left and overloaded:  # the gateway is struggling: stop here, the next run goes on
            break
    save(st_path, status)
    return ran


def adopt(page, steps, root=Path(".")):
    """Marks steps that were run before the status files existed as done, with the fingerprints they have now."""
    page_md = (root / PAGES / f"{page}.md").read_text(encoding="utf-8")
    record = load(root / RECORDS / f"{page}.json", {"sections": []})
    status = load(root / STATUS / f"{page}.json", {})
    for step in steps:
        status[step] = {"state": "done", "attempts": 0, "gaps": [], "model": "adopted", "at": "before status files",
                        "input": expected_input(step, status, page_md), "after": texts_hash(record)}
    save(root / STATUS / f"{page}.json", status)
    return status


def retry(page, steps, root=Path(".")):
    """Forgets the state of the given steps (attempts used up, gaps accepted) so the next run does them again."""
    st_path = root / STATUS / f"{page}.json"
    status = load(st_path, {})
    for step in steps:  # kept as a marker: the next run of the step is a repair that redoes only what is wrong
        status[step] = {"state": "forgotten", "attempts": 0, "gaps": [], "input": None, "after": None,
                        "model": status.get(step, {}).get("model", "")}
    save(st_path, status)
    return status


def show(page, root=Path(".")):
    page_md = (root / PAGES / f"{page}.md").read_text(encoding="utf-8")
    status = load(root / STATUS / f"{page}.json", {})
    nxt = next_step(status, page_md)
    return {"page": page, "next": nxt, **{s: status.get(s, {}).get("state", "todo") for s in STEPS}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--model", default=cp.DEFAULT_MODEL)
    ap.add_argument("--max-steps", type=int, default=12, help="steps to run per page in this call")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--adopt", help="comma-separated steps already done before status files existed, e.g. fold,tidy")
    ap.add_argument("--retry", help="comma-separated steps to forget so they run again, e.g. translate")
    args = ap.parse_args(argv)
    if args.retry:
        for p in args.pages:
            retry(p, args.retry.split(","))
    if args.adopt:
        for p in args.pages:
            adopt(p, args.adopt.split(","))
        return 0
    if args.show:
        for p in args.pages:
            print(json.dumps(show(p), ensure_ascii=False))
        return 0
    call = cp.gateway_call(args.model, os.environ["AI_GATEWAY_TOKEN"])
    ctl = rc.Control(expected=args.model)
    for p in args.pages:
        run_page(p, call, args.model, args.max_steps, ctl=ctl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
