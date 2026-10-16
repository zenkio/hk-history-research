#!/usr/bin/env python3
"""V2.2 end to end: extract facts from approved source packets with one model, then link them.

For each approved, inspected source of each packet: split its passage into sentences (step A), ask
the single questions of steps B-E (scripts/extraction_questions.py), and let code add the year, era,
stored statement and gaps (steps F-H). Then link facts of the same topic (design §4): each pair of
facts from different sources whose eras overlap gets one multiple-choice question, asked twice with
the two statements swapped. A link is kept only when both answers agree.

Every fact starts as a claim of its source, "not yet corroborated". A link from a different source
family (another institution) can support or challenge it; a link within the same family is kept but
does not count as corroboration.

Output is private research data (sentences, statements): it belongs on a private experiment branch.
"""
import argparse
import itertools
import json
import re
import sys
import time
from pathlib import Path

import fact_extraction as fx
from extraction_questions import _numbered, extract_sentence, parse_choice

ROLE = "fact_extraction_trial"
APPROVED = "approved_for_internal_research"
# Source types whose claims are official (a government, legislature or its archive).
OFFICIAL_WORDS = ("official", "legislative", "archival")

LINK_CHOICES = (
    # Run 38639138642 marked "in 1901" against "on 10 January 1901" as a conflict.
    ("same_fact", "They state the same fact (one may be more precise, such as a full date where the other gives the year)"),
    ("different_detail", "They describe the same event but contradict each other on a detail (a different date, place, person or action)"),
    ("different_event", "They are about different steps or events of the same story"),
    ("unrelated", "They are unrelated"),
)
# Design §4: the same fact supports; a different detail of the same event challenges.
LINK_KINDS = {"same_fact": "supports", "different_detail": "challenges"}

LINK_PROMPT = """Two statements come from records gathered about this question: {question}
Statement A: {a}
Statement B: {b}
How do the two statements relate?
{options}
Answer with the number only."""


def topic_era(question):
    """The era of the first year a packet's research question names ("... the 1987 debate ...")."""
    found = fx.YEAR_RE.search(str(question or ""))
    eras = fx.eras_of(int(found.group(1))) if found else []
    return eras[0] if eras else None


def claim_label(record):
    kind = str(record.get("source_type", ""))
    return "official claim" if any(word in kind for word in OFFICIAL_WORDS) else "claim"


def source_family(record):
    """Records from the same institution are one source family ("Hong Kong Government" and
    "Hong Kong Government, news.gov.hk" are one). A semicolon also ends the name: run 38972366561
    put two China Mail reports in different families ("China Mail (...); scan digitised ...")."""
    return re.split(r"[,;]", str(record.get("institution", "")))[0].strip().casefold()


def eligible(record):
    return record.get("processing_status") == APPROVED and record.get("inspection_status") == "inspected"


def extract_topic(ask, packet):
    """Steps A-H for every eligible source of one packet; returns the topic's fact records."""
    era = topic_era(packet.get("event_question"))
    facts, skipped = [], []
    for record in packet.get("sources", []):
        if not eligible(record):
            skipped.append(record.get("source_id"))
            continue
        text = record.get("passage_en") or record.get("passage", "")
        notes = str((record.get("record_context") or {}).get("paragraph_subject") or "").split(" (")[0]
        for s_index, sentence in enumerate(fx.split_sentences(text), 1):
            answer = extract_sentence(ask, sentence, record)
            for f_index, fact in enumerate(answer["facts"], 1):
                if fact.get("subject", "").casefold() in fx.VAGUE_SUBJECTS | {""} and notes:
                    fact["subject_from_notes"] = notes
                year = fx.year_of(fact.get("when"), record)
                facts.append(dict(
                    fact, id=f"{record['source_id']}#s{s_index}f{f_index}", source_id=record["source_id"],
                    institution=record.get("institution", ""), family=source_family(record),
                    label=claim_label(record), sentence=sentence, year=year, era=fx.eras_of(year, era),
                    angle=answer["angle"], tags=answer["tags"], log=answer["log"],
                    statement=fx.write_statement(sentence, fact, record)))
    if era is None:
        # Run 38639138642: the Yeung question names no year, so undated facts got no era and the
        # classroom / residence conflict was never asked. The topic's earliest dated fact sets it.
        years = [f["year"] for f in facts if f["year"] is not None]
        era = (fx.eras_of(min(years)) or [None])[0] if years else None
        for fact in facts:
            if not fact["era"] and era:
                fact["era"] = [era]
    return facts, skipped


def candidate_pairs(facts):
    """Pairs of facts from different sources whose eras overlap (no model call)."""
    return [(a, b) for a, b in itertools.combinations(facts, 2)
            if a["source_id"] != b["source_id"] and set(a["era"]) & set(b["era"])]


def ask_link(ask, question, a, b):
    """One relation for a pair, asked twice with the statements swapped; None when the two answers
    disagree or are not on the list."""
    answers = []
    for first, second in ((a, b), (b, a)):
        prompt = LINK_PROMPT.format(question=question, a=first["statement"], b=second["statement"],
                                    options=_numbered([label for _, label in LINK_CHOICES]))
        choice = parse_choice(ask(prompt), len(LINK_CHOICES))
        answers.append(LINK_CHOICES[choice - 1][0] if choice else None)
    return (answers[0] if answers[0] and answers[0] == answers[1] else None), answers


def link_topic(ask, question, facts):
    links, unsure = [], []
    for a, b in candidate_pairs(facts):
        relation, answers = ask_link(ask, question, a, b)
        if relation is None:
            unsure.append({"a": a["id"], "b": b["id"], "answers": answers})
        elif relation in LINK_KINDS:
            links.append({"a": a["id"], "b": b["id"], "relation": relation, "kind": LINK_KINDS[relation],
                          "same_source_family": a["family"] == b["family"]})
    return links, unsure


def settle(facts, links):
    """Each fact's status and gaps after linking. Only links from another source family count."""
    for fact in facts:
        mine = [l for l in links if fact["id"] in (l["a"], l["b"]) and not l["same_source_family"]]
        supported = any(l["kind"] == "supports" for l in mine)
        challenged = any(l["kind"] == "challenges" for l in mine)
        fact["status"] = {(False, False): "not yet corroborated", (True, False): "supported by another source",
                          (False, True): "challenged by another source",
                          (True, True): "supported and challenged"}[(supported, challenged)]
        gap_fact = dict(fact, kind=[fact.get("kind") or "event"])
        fact["gaps"] = fx.gaps_for(gap_fact, fact["year"], single_source=not supported)
        if fact["gaps"] and fact["gaps"][-1].startswith("Only one source"):
            fact["gaps"][-1] = f"Only one source so far ({fact['label']}, not yet corroborated)."


def run(ask, packets, topics=None):
    """Extract and link every packet; topics fills as each one finishes, so a caller keeps the
    finished topics if a later one fails."""
    topics = [] if topics is None else topics
    for name, packet in packets:
        facts, skipped = extract_topic(ask, packet)
        links, unsure = link_topic(ask, packet.get("event_question", ""), facts)
        settle(facts, links)
        topics.append({"packet": name, "facts": facts, "links": links, "unsure_links": unsure,
                       "skipped_sources": skipped})
    return topics


def load_packets(packet_dir):
    """(file name, packet) for each packet file; MANIFEST.json describes the set and is not one."""
    return [(p.name, json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(Path(packet_dir).glob("*.json")) if p.name != "MANIFEST.json"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--model", required=True, help="a display name from the fact_extraction_trial role")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool
    from score_extraction_models import TRIAL_RPD
    pool = ModelPool()
    if args.model not in pool.routing.get(ROLE, []) or pool.remaining(args.model, ROLE) == 0:
        print(f"{args.model} is not usable in this run", file=sys.stderr)
        return 2
    if pool.models[args.model].get("provider") == "openrouter":
        pool.models[args.model]["rpd"] = max(pool.models[args.model]["rpd"], TRIAL_RPD)
    calls = []

    def ask(prompt):
        calls.append(1)
        return pool.generate_text(ROLE, prompt, str, only=[args.model])[0]

    started, topics, stopped = time.time(), [], ""
    try:
        run(ask, load_packets(args.packets), topics)
    except Exception as exc:  # keep the finished topics; the log says why it stopped
        stopped = f"stopped after {len(topics)} topics: {type(exc).__name__}"
        print(stopped, file=sys.stderr)
    args.output.write_text(json.dumps({
        "purpose": "v2.2 end-to-end extraction and linking; experiment only, no live records changed",
        "model": args.model, "api_id": pool.models[args.model].get("api_id"), "calls": len(calls),
        "minutes": round((time.time() - started) / 60, 1), "stopped": stopped, "topics": topics,
        "live_records_modified": False, "publication_approved": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for topic in topics:
        print(f"{topic['packet']} | facts {len(topic['facts'])} | links {len(topic['links'])} | "
              f"unsure {len(topic['unsure_links'])} | skipped {len(topic['skipped_sources'])}", flush=True)
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
