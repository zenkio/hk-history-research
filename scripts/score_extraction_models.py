#!/usr/bin/env python3
"""V2.2 step 4: score each free model on the answer key, step by step, and say which steps it may do.

Every model in --models is forced in turn (pool role `fact_extraction_trial`, only=[model]) to answer
the single questions of steps B-E (scripts/extraction_questions.py) for every sentence of the answer
key. Code then adds the year, era, statement and gaps (steps F-H) and scores the answers field by
field (fact_extraction.score). A model may do a step only if it reaches the bar of the design: 95%
exact for copied spans (B, E), 90% for choices (C, D), and no invented span kept.

The answer key, the sentences and the answers are private research data: the output file belongs on
the private experiment branch, and the printed lines carry only model names and numbers.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import fact_extraction as fx
from extraction_questions import extract_sentence

ROLE = "fact_extraction_trial"
SPAN_BAR, CHOICE_BAR = 0.95, 0.90
# Who, what and by whom are judged by overlap: the stored statement quotes the record word for
# word, so where a copied phrase ends does not change what is stored (run 38539796609: Nemotron
# Ultra's misses there were all phrase ends). Dates and places stay exact: they place a fact in an
# era and link it to other records. Tags are judged by overlap for the same reason.
STEPS = {
    "B_facts": (("facts_found", "near_subject", "near_action", "near_agent", "when", "where", "negated"), SPAN_BAR),
    "C_kind": (("kind",), CHOICE_BAR),
    "D_angle": (("view_of", "stance"), CHOICE_BAR),
    "E_tags": (("near_tags",), SPAN_BAR),
}
# A free model whose provider is busy (429s) is rested and asked again, at most this many times
# per model (run 38525325652: Gemma on OpenRouter gave up after its first call).
TRIAL_RESTS, REST_SECONDS = 3, 300
# The experiment's own budget: the per-entry OpenRouter limit (50) splits the account's day between
# pipeline roles; the pipeline is in maintenance mode, and the account-wide limit still applies.
TRIAL_RPD = 1000


def load_records(packet_dir):
    """source_id -> source record, from the packet files only (MANIFEST.json describes the set)."""
    records = {}
    for path in sorted(Path(packet_dir).glob("*.json")):
        if path.name == "MANIFEST.json":
            continue
        packet = json.loads(path.read_text(encoding="utf-8"))
        for record in packet.get("sources", []) if isinstance(packet, dict) else []:
            records[record["source_id"]] = record
    return records


def rates(totals):
    return {field: round(right / total, 3) if total else None
            for field, value in totals.items() if isinstance(value, list) for right, total in [value]}


def verdict(totals):
    """Which steps the model may do: every field of the step at or above its bar, nothing invented."""
    rate = rates(totals)
    passed = {}
    for step, (fields, bar) in STEPS.items():
        ok = all(rate.get(f) is not None and rate[f] >= bar for f in fields)
        if step in ("B_facts", "E_tags"):
            ok = ok and totals.get("invented_spans", 0) == 0
        passed[step] = ok
    return passed


def finish(answer, row, record):
    """Steps F-H on a model's answer: year and era per fact, the stored statement, the gaps."""
    topic_era = row["era"][0] if row.get("era") else None  # the pilot packets name no era of their own
    notes_subject = str((record.get("record_context") or {}).get("paragraph_subject") or "").split(" (")[0]
    for fact in answer["facts"]:
        if fact.get("subject", "").casefold() in fx.VAGUE_SUBJECTS | {""} and notes_subject:
            fact["subject_from_notes"] = notes_subject
        fact["year"] = fx.year_of(fact.get("when"), record)
        fact["era"] = fx.eras_of(fact["year"], topic_era)
        fact["statement"] = fx.write_statement(row["sentence"], fact, record)
        fact["gaps"] = fx.gaps_for(dict(fact, kind=[fact.get("kind") or "event"]), fact["year"])
    return answer


def era_score(answers, key):
    """[right, total]: the era of each sentence's first fact against the key's eras."""
    right = total = 0
    for row in key["sentences"]:
        facts = answers.get(row["source_id"], {}).get("facts", [])
        total += 1
        right += bool(facts and set(facts[0]["era"]) & set(row["era"]))
    return [right, total]


class OutOfTime(Exception):
    """The run's time budget is spent; the sentences done so far are scored."""


def score_model(ask, key, records, limit=None, stop_on=(), deadline=None):
    """Run steps B-E with one model on every key sentence; returns the model's result entry. An
    exception in stop_on (the model's budget ran out) or the deadline (time.time()) ends the run;
    the sentences done are scored."""
    answers, done, stopped = {}, 0, ""
    for row in key["sentences"][:limit]:
        if deadline is not None and time.time() >= deadline:
            stopped = f"stopped after {done} sentences: {OutOfTime.__name__}"
            break
        record = records[row["source_id"]]
        try:
            answer = extract_sentence(ask, row["sentence"], record)
        except (OutOfTime,) + tuple(stop_on) as exc:
            stopped = f"stopped after {done} sentences: {type(exc).__name__}"
            break
        answers[row["source_id"]] = finish(answer, row, record)
        done += 1
    scored_key = {"sentences": key["sentences"][:done]}
    totals = fx.score(answers, scored_key)
    totals["era"] = era_score(answers, scored_key)
    return {"sentences_done": done, "stopped": stopped, "scores": totals, "rates": rates(totals),
            "steps_passed": verdict(totals), "answers": answers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--models", required=True, help="comma-separated display names from models.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="score only the first N sentences")
    parser.add_argument("--minutes", type=float, default=None,
                        help="stop asking after this many minutes (keep it under the job's timeout)")
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool, QuotaExhausted
    key = json.loads(args.key.read_text(encoding="utf-8"))
    records = load_records(args.packets)
    missing = [r["source_id"] for r in key["sentences"] if r["source_id"] not in records]
    if missing:
        print(f"answer key names {len(missing)} source ids no packet has; stopping", file=sys.stderr)
        return 2
    pool = ModelPool()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    results = []
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        entry = {"model": name}
        if name not in pool.routing.get(ROLE, []):
            entry["error"] = f"not in routing role {ROLE}"
        elif pool.remaining(name, ROLE) == 0:
            entry["error"] = "unavailable in this run (no key, rejected key or no free match)"
        else:
            if pool.models[name].get("provider") == "openrouter":
                pool.models[name]["rpd"] = max(pool.models[name]["rpd"], TRIAL_RPD)
            calls = []

            rests = []

            def ask(prompt, name=name, calls=calls, rests=rests):
                while True:
                    calls.append(1)
                    try:
                        return pool.generate_text(ROLE, prompt, str, only=[name])[0]
                    except QuotaExhausted:
                        if len(rests) >= TRIAL_RESTS or pool.remaining(name, ROLE) == 0:
                            raise
                        if deadline is not None and time.time() + REST_SECONDS >= deadline:
                            raise OutOfTime() from None
                        rests.append(1)
                        print(f"{name} | busy; resting {REST_SECONDS}s ({len(rests)}/{TRIAL_RESTS})")
                        time.sleep(REST_SECONDS)
                        pool.cooldown.pop(name, None)

            entry.update(score_model(ask, key, records, args.limit, stop_on=(QuotaExhausted,),
                                     deadline=deadline))
            entry["calls"] = len(calls)
            entry["api_id"] = pool.models[name].get("api_id")
        results.append(entry)
        passed = entry.get("steps_passed")
        print(f"{name} | " + (", ".join(f"{s} {'pass' if ok else 'fail'}" for s, ok in passed.items())
                             if passed else entry.get("error", "")), flush=True)
        # Saved after every model: run 38531845034 hit the job timeout and kept nothing.
        save(args.output, key, args.limit, results)
    return 0


def save(path, key, limit, results):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "purpose": "v2.2 model scoring on the answer key; experiment only, no live records changed",
        "answer_key_sentences": len(key["sentences"][:limit]),
        "bars": {"spans": SPAN_BAR, "choices": CHOICE_BAR, "invented_spans": 0},
        "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    sys.exit(main())
