#!/usr/bin/env python3
"""V2.2 consensus run: several models answer the same sentences, their answers are pooled, and claims
only one model made are checked by another (hk-history-data experiments/V2_2_MULTI_AI_CONSENSUS_DESIGN.md).

For every sentence, each listed model answers the single questions of steps B-E
(extraction_questions.extract_sentence). fact_consensus pools the answers into settled / single /
questioned claims with who backed each, then every single claim goes to a model that did not make it.
Rows of who found what are appended to a history file; with --history-in, the report also lists what
changed since the earlier runs. A model that runs out of quota or time stops contributing; the
others carry on. Sentences and answers are private research data: the outputs belong on the private
experiment branch, and the printed lines carry only model names and counts.
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import fact_consensus as fc
from extraction_questions import extract_sentence
from score_extraction_models import OutOfTime, ROLE, load_records, open_for_trial, trial_ask, finish


def run_consensus(asks, key, records, run_id, date, limit=None, stop_on=(), deadline=None, save=None):
    """asks: {model: ask}. Returns (sentences, history rows, {model: stopped reason})."""
    live, stopped = dict(asks), {}
    sentences, rows = [], []
    for row in key["sentences"][:limit]:
        if deadline is not None and time.time() >= deadline:
            for model in live:
                stopped[model] = "time budget spent"
            break
        answers = {}
        for model, ask in list(live.items()):
            try:
                answer = extract_sentence(ask, row["sentence"], records[row["source_id"]])
            except (OutOfTime,) + tuple(stop_on) as exc:
                stopped[model] = type(exc).__name__
                del live[model]
                continue
            answers[model] = finish(answer, row, records[row["source_id"]])
        if not answers:
            break
        pooled = fc.pool_sentence(answers)
        log = []
        fc.check_singles(pooled, row["sentence"], {m: a for m, a in live.items()}, log)
        pooled["log"] = log
        sentences.append({"source_id": row["source_id"], "sentence": row["sentence"], "pooled": pooled})
        rows += fc.history_rows(run_id, date, row["source_id"], pooled)
        if save:
            save(sentences, rows, stopped)
    return sentences, rows, stopped


def summary(sentences):
    """Counts only: claims by status, per claim type."""
    counts = {}
    for item in sentences:
        for claim in item["pooled"]["facts"] + item["pooled"]["tags"]:
            kind = "fact" if claim["claim_type"] == "fact" else "tag"
            counts.setdefault(kind, {fc.SETTLED: 0, fc.SINGLE: 0, fc.QUESTIONED: 0})[claim["status"]] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", type=Path, required=True, help="the sentences to read (the answer key's)")
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--models", required=True, help="comma-separated display names from models.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--history-in", type=Path, default=None, help="earlier history.jsonl, to report changes")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--minutes", type=float, default=None)
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool, QuotaExhausted, RequestRejected
    key = json.loads(args.key.read_text(encoding="utf-8"))
    records = load_records(args.packets)
    records.update(key.get("records", {}))
    missing = [r["source_id"] for r in key["sentences"] if r["source_id"] not in records]
    if missing:
        print(f"{len(missing)} sentences name source ids no packet has; stopping", file=sys.stderr)
        return 2
    pool = ModelPool()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    asks, status, calls = {}, {}, {}
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        if name not in pool.routing.get(ROLE, []):
            status[name] = f"not in routing role {ROLE}"
        elif pool.remaining(name, ROLE) == 0:
            status[name] = "unavailable in this run (no key, rejected key or no free match)"
        else:
            open_for_trial(pool, name)
            calls[name] = []
            asks[name] = trial_ask(pool, name, deadline, calls[name], [])
            status[name] = "used"
    for name, text in status.items():
        print(f"{name} | {text}", flush=True)
    if not asks:
        print("no model available", file=sys.stderr)
        return 1
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    previous = fc.read_history(args.history_in) if args.history_in else []

    def save(sentences, rows, stopped):
        report = {"models": {m: {"status": status[m], "stopped": stopped.get(m, ""),
                                 "api_id": pool.models[m].get("api_id") if m in asks else None,
                                 "calls": len(calls.get(m, []))} for m in status},
                  "claims": summary(sentences), "per_model": fc.model_report(rows),
                  "since_earlier_runs": fc.changes(previous, rows) if previous else None}
        out = args.output_dir
        (out / "consensus.json").write_text(json.dumps({
            "purpose": "v2.2 multi-AI consensus; experiment only, no live records changed",
            "run_id": run_id, "date": date, "sentences": sentences}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        (out / "history.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sentences, rows, stopped = run_consensus(asks, key, records, run_id, date, args.limit,
                                             stop_on=(QuotaExhausted, RequestRejected), deadline=deadline,
                                             save=save)
    save(sentences, rows, stopped)
    print(f"sentences {len(sentences)} | claims {summary(sentences)} | stopped {stopped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
