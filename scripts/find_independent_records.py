#!/usr/bin/env python3
"""V2.2 verification, step 1: find records from other institutions about facts only one source states.

For each fact of an extract_records output that is not yet corroborated or is challenged, and whose
kind is one other records can confirm (an event, plan, allegation or denial, not an opinion or
reported words),
code builds a search from the fact's tags (or the record notes' subject, or else the topic's tags), searches the archive adapters already used by the pipeline
(evidence.gather), and keeps candidates from another source family whose text shares the fact's year
or two of its tags. One model question per candidate picks the numbered sentence that is about this
event, or none. The chosen sentence (cut to 25 words) becomes a candidate record.

Candidate records are written to their own file, never into the packets: they are not inspected, not
approved, and not for public reuse. A reviewer approves them before extraction and linking use them.
Output is private research data: it belongs on a private experiment branch.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import extract_records as er
import fact_extraction as fx
from extraction_questions import _numbered, parse_choice

SEARCH_KINDS = {"event", "plan_or_target", "allegation", "denial"}
# A challenged fact is searched too: a third record may settle the disagreement.
SEARCH_STATUSES = {"not yet corroborated", "challenged by another source"}
MAX_WORDS = 25
MAX_SENTENCES = 8
CANDIDATES_PER_FACT = 6
RECORDS_PER_TOPIC = 5
# Words that name no event: the adapters add "Hong Kong" to every query themselves.
NOT_SEARCH_TERMS = {"hong kong", "hong kong island", "british", "china", "chinese", "government"}
INSTITUTIONS = {"UK National Archives Discovery": "The National Archives (UK)",
                "Hong Kong Government Records Service": "Hong Kong Government Records Service"}

SENTENCE_PROMPT = """A record states: {statement}
Which sentence below is about the same event? It may agree or disagree with the record.
{options}
Answer with the number only."""


def searchable(fact):
    return fact.get("status") in SEARCH_STATUSES and fact.get("kind") in SEARCH_KINDS


def terms_of(fact, fallback=()):
    """The fact's tags, most specific first (people, groups, things, places), without the words that
    every Hong Kong record shares. A sentence that names no one ("shot dead in his residence") uses
    the subject the record notes give, and then the topic's terms (fallback)."""
    tags = fact.get("tags") or {}
    named = tags.get("people", []) + tags.get("groups", [])
    notes = [fact["subject_from_notes"]] if fact.get("subject_from_notes") and not named else []
    seen, terms = set(), []
    for group in (notes, named, tags.get("things", []), tags.get("places", [])):
        for term in group:
            term = term.split(" (")[0].strip()  # "Ordinance (MPFO)": the bracket is an abbreviation
            term = re.sub(r"['’]s$", "", term)  # run 38660927145 searched for "government's"
            key = term.casefold()
            if key not in seen and key not in NOT_SEARCH_TERMS:
                seen.add(key)
                terms.append(term)
    # Topic terms only when the sentence names nothing: padding a query with them narrows it.
    return terms or [t for t in dict.fromkeys(fallback) if t.casefold() not in NOT_SEARCH_TERMS]


def query_for(fact, fallback=()):
    return " ".join(f'"{t}"' if " " in t else t for t in terms_of(fact, fallback)[:2])


def covers(record_year, year):
    """Whether a candidate's date ("1908", "1849-1851", "1 Jan 1900 - 31 Dec 1909") covers the year."""
    years = [int(y) for y in re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", str(record_year or ""))]
    return bool(year and years and min(years) <= int(year) <= max(years))


def matching_sentences(text, fact, fallback=(), record_year=""):
    """Numbered-question material: the candidate's sentences that share the fact's year or at least
    two of its terms (no model call). When the candidate's own date covers the fact's year (an
    archive file's covering dates), one shared term is enough: catalogue descriptions rarely repeat
    the year (run 38660927145 asked about none of the Tatsu Maru candidates)."""
    terms = [t.casefold() for t in terms_of(fact, fallback)]
    year = str(fact.get("year") or "")
    needed = 1 if len(terms) == 1 or covers(record_year, fact.get("year")) else 2
    kept = []
    for sentence in fx.split_sentences(text or ""):
        folded = sentence.casefold()
        shared = sum(term in folded for term in terms)
        if (year and year in sentence) or shared >= needed:
            kept.append(sentence)
    return kept[:MAX_SENTENCES]


def excerpt(sentence, fact, fallback=()):
    """The sentence if it is short enough, else MAX_WORDS words starting near the first shared
    term or year (the record keeps its locator, so the whole sentence can be read there)."""
    words = sentence.split()
    if len(words) <= MAX_WORDS:
        return sentence
    marks = [t.casefold() for t in terms_of(fact, fallback)] + ([str(fact["year"])] if fact.get("year") else [])
    first = next((i for i, w in enumerate(words) if any(m.split()[0] in w.casefold() for m in marks)), 0)
    start = max(0, min(first - 5, len(words) - MAX_WORDS))
    return " ".join(words[start:start + MAX_WORDS])


def institution_of(candidate):
    """Who stands behind the candidate: the archive for catalogue records, else the work's authors."""
    if candidate.get("source") in INSTITUTIONS:
        return INSTITUTIONS[candidate["source"]]
    cite = str(candidate.get("cite") or "").strip()
    return re.split(r"\s*\(|\*", cite)[0].strip(" ,.") or str(candidate.get("source", ""))


def ask_sentence(ask, fact, sentences):
    """The number of the sentence about this event, or None ("none of these" or no clear answer)."""
    options = sentences + ["None of these is about the same event"]
    choice = parse_choice(ask(SENTENCE_PROMPT.format(statement=fact["statement"], options=_numbered(options))),
                          len(options))
    return choice if choice and choice <= len(sentences) else None


def candidate_record(candidate, sentence, fact, fallback=()):
    text = candidate.get("passage") or candidate.get("note") or ""
    url = candidate.get("url") or candidate.get("catalogue_reference") or ""
    return {
        "source_id": "v-" + hashlib.sha1(f"{url}|{sentence}".encode()).hexdigest()[:10],
        "for_fact": fact["id"], "passage": excerpt(sentence, fact, fallback),
        "institution": institution_of(candidate), "source_type": candidate.get("kind", ""),
        "source_date": str(candidate.get("year") or ""), "url": url,
        "locator": candidate.get("locator", ""), "cite": candidate.get("cite", ""),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "retrieved_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "inspection_status": "not_inspected", "processing_status": "awaiting_review",
        "public_reuse_not_approved": True,
    }


def find_for_topic(ask, topic, gather):
    """Candidate records for one topic's searchable facts; a log line per fact (no text)."""
    records, log, searched = [], [], {}
    families = {f["family"] for f in topic["facts"]}
    topic_terms = [t for f in topic["facts"] for t in terms_of(f)]
    for fact in [f for f in topic["facts"] if searchable(f)]:
        if len(records) >= RECORDS_PER_TOPIC:
            log.append({"fact": fact["id"], "skipped": "topic limit reached"})
            continue
        query = query_for(fact, topic_terms)
        if not query:
            log.append({"fact": fact["id"], "skipped": "no tags to search"})
            continue
        if query not in searched:  # facts of one sentence share their tags: search once
            searched[query] = gather(query)
        found, failed = searched[query]
        entry = {"fact": fact["id"], "query": query, "found": len(found), "failed_sources": failed,
                 "other_family": 0, "asked": 0, "kept": 0, "candidates": []}
        for candidate in found:
            if entry["asked"] >= CANDIDATES_PER_FACT or len(records) >= RECORDS_PER_TOPIC:
                break
            # What was found and why it went no further (private log): run 38660927145 kept only
            # counts, so its empty results could not be diagnosed.
            seen = {"source": candidate.get("source", ""), "year": str(candidate.get("year") or ""),
                    "title": str(candidate.get("title") or "")[:100]}
            entry["candidates"].append(seen)
            if er.source_family({"institution": institution_of(candidate)}) in families:
                seen["outcome"] = "same source family"
                continue
            entry["other_family"] += 1
            sentences = matching_sentences(candidate.get("passage") or candidate.get("note"), fact, topic_terms,
                                           candidate.get("year"))
            if not sentences:
                seen["outcome"] = "no sentence shares the year or terms"
                continue
            entry["asked"] += 1
            choice = ask_sentence(ask, fact, sentences)
            seen["outcome"] = "kept" if choice else "model: none of these"
            if choice:
                records.append(candidate_record(candidate, sentences[choice - 1], fact, topic_terms))
                entry["kept"] += 1
        log.append(entry)
    return records, log


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--records", type=Path, required=True, help="an extract_records.py output")
    parser.add_argument("--model", required=True, help="a display name from the fact_extraction_trial role")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    import evidence
    from gemini_pool import ModelPool
    from score_extraction_models import TRIAL_RPD
    extracted = json.loads(args.records.read_text(encoding="utf-8"))
    pool = ModelPool()
    if args.model not in pool.routing.get(er.ROLE, []) or pool.remaining(args.model, er.ROLE) == 0:
        print(f"{args.model} is not usable in this run", file=sys.stderr)
        return 2
    if pool.models[args.model].get("provider") == "openrouter":
        pool.models[args.model]["rpd"] = max(pool.models[args.model]["rpd"], TRIAL_RPD)
    calls = []

    def ask(prompt):
        calls.append(1)
        return pool.generate_text(er.ROLE, prompt, str, only=[args.model])[0]

    started, topics, stopped = time.time(), [], ""
    try:
        for topic in extracted.get("topics", []):
            records, log = find_for_topic(ask, topic, evidence.gather)
            topics.append({"packet": topic["packet"], "candidate_records": records, "search_log": log})
            print(f"{topic['packet']} | searched {sum('query' in e for e in log)} | "
                  f"found {sum(e.get('found', 0) for e in log)} | kept {len(records)}", flush=True)
    except Exception as exc:  # keep the finished topics; the log says why it stopped
        stopped = f"stopped after {len(topics)} topics: {type(exc).__name__}"
        print(stopped, file=sys.stderr)
    args.output.write_text(json.dumps({
        "purpose": "v2.2 verification candidates; not inspected, not approved, experiment only",
        "model": args.model, "calls": len(calls), "minutes": round((time.time() - started) / 60, 1),
        "stopped": stopped, "topics": topics, "live_records_modified": False, "publication_approved": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
