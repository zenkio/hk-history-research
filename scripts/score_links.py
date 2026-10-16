#!/usr/bin/env python3
"""V2.2 linking score: each model links the answer key's own facts and is scored on the link key.

Linking is scored apart from extraction: the facts are the answer key's (so an extraction miss
cannot hide a linking error), their statements are written by code (fact_extraction.write_statement)
and the pairs are those extract_records would ask about (different sources, overlapping eras). Each
model answers the link question for every pair (asked twice, swapped; extract_records.link_topic).

The link key labels every pair supports, challenges or none, with defensible alternatives in
also_ok. A pair the model was unsure of counts as none. The bar: no wrong link (a link the key does
not accept) and at least 90% of pairs right.

The keys, statements and answers are private research data: the output belongs on the private
experiment branch, and the printed lines carry only model names and numbers.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import extract_records as er
import fact_extraction as fx
from score_extraction_models import ROLE, OutOfTime, open_for_trial, trial_ask

RIGHT_BAR = 0.90


def key_facts(key, packets):
    """packet name -> the answer key's facts for that packet's sources, shaped like extract_records
    facts (id source_id#n, family, era from the key, statement written by code)."""
    rows = {row["source_id"]: row for row in key["sentences"]}
    topics = {}
    for name, packet in packets:
        facts = []
        for record in packet.get("sources", []):
            row = rows.get(record.get("source_id"))
            if not row:
                continue
            for n, fact in enumerate(row["facts"], 1):
                facts.append(dict(fact, id=f"{row['source_id']}#{n}", source_id=row["source_id"],
                                  family=er.source_family(record), era=list(row["era"]),
                                  statement=fx.write_statement(row["sentence"], fact, record)))
        if facts:
            topics[name] = (packet.get("event_question", ""), facts)
    return topics


def _pair(a, b):
    return frozenset((a, b))


def score_links(link_key, links, unsure):
    """Compare a model's links with the key. Returns counts and the pairs it got wrong."""
    got = {_pair(l["a"], l["b"]): l["kind"] for l in links}
    unsure_pairs = {_pair(u["a"], u["b"]) for u in unsure}
    totals = {"pairs": 0, "right": 0, "wrong_links": 0, "missed_links": 0, "unsure": 0}
    wrong = []
    for item in link_key["pairs"]:
        pair = _pair(item["a"], item["b"])
        answer = got.get(pair, "none")
        accepted = {item["expected"], *item.get("also_ok", [])}
        totals["pairs"] += 1
        totals["unsure"] += pair in unsure_pairs
        if answer in accepted:
            totals["right"] += 1
            continue
        totals["wrong_links" if answer != "none" else "missed_links"] += 1
        wrong.append({"a": item["a"], "b": item["b"], "expected": item["expected"], "got": answer})
    return totals, wrong


def passed(totals):
    return bool(totals["pairs"]) and totals["wrong_links"] == 0 and totals["right"] / totals["pairs"] >= RIGHT_BAR


def score_model(ask, topics, link_key, stop_on=(), deadline=None):
    """Link every topic's key facts with one model; the topics finished are scored if it stops."""
    links, unsure, done, stopped = [], [], [], ""
    for name, (question, facts) in topics.items():
        if deadline is not None and time.time() >= deadline:
            stopped = f"stopped after {len(done)} topics: {OutOfTime.__name__}"
            break
        try:
            topic_links, topic_unsure = er.link_topic(ask, question, facts)
        except (OutOfTime,) + tuple(stop_on) as exc:
            stopped = f"stopped after {len(done)} topics: {type(exc).__name__}"
            break
        links += topic_links
        unsure += topic_unsure
        done.append(name)
    finished = {f["id"] for name in done for f in topics[name][1]}
    scored_key = {"pairs": [p for p in link_key["pairs"] if p["a"] in finished and p["b"] in finished]}
    totals, wrong = score_links(scored_key, links, unsure)
    return {"topics_done": done, "stopped": stopped, "scores": totals, "passed": passed(totals),
            "wrong": wrong, "links": links, "unsure_links": unsure}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", type=Path, required=True, help="the extraction answer key (facts)")
    parser.add_argument("--link-key", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--models", required=True, help="comma-separated display names from models.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=None,
                        help="stop asking after this many minutes (keep it under the job's timeout)")
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool, QuotaExhausted
    key = json.loads(args.key.read_text(encoding="utf-8"))
    link_key = json.loads(args.link_key.read_text(encoding="utf-8"))
    topics = key_facts(key, er.load_packets(args.packets))
    pairs = {_pair(a["id"], b["id"]) for _, facts in topics.values() for a, b in er.candidate_pairs(facts)}
    keyed = {_pair(p["a"], p["b"]) for p in link_key["pairs"]}
    if pairs != keyed:
        print(f"link key and candidate pairs differ ({len(pairs - keyed)} unkeyed, "
              f"{len(keyed - pairs)} never asked); stopping", file=sys.stderr)
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
            open_for_trial(pool, name)
            calls, rests = [], []
            entry.update(score_model(trial_ask(pool, name, deadline, calls, rests), topics, link_key,
                                     stop_on=(QuotaExhausted,), deadline=deadline))
            entry["calls"] = len(calls)
            entry["api_id"] = pool.models[name].get("api_id")
        results.append(entry)
        s = entry.get("scores")
        print(f"{name} | " + (f"right {s['right']}/{s['pairs']}, wrong links {s['wrong_links']}, "
                              f"missed {s['missed_links']}, unsure {s['unsure']}, "
                              f"{'pass' if entry['passed'] else 'fail'}" if s else entry.get("error", "")),
              flush=True)
        tmp = args.output.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "purpose": "v2.2 linking scored on the link key; experiment only, no live records changed",
            "bars": {"right": RIGHT_BAR, "wrong_links": 0}, "pairs": len(link_key["pairs"]),
            "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
