#!/usr/bin/env python3
"""V2.2 fact extraction: the parts code does, so weak free models only copy spans or pick from lists.

Design (hk-history-data experiments/V2_2_WEAK_MODEL_EXTRACTION_DESIGN.md): a model is asked one small
question about one sentence. It copies words from the sentence into slots (subject, action, agent,
when, where, tags) or picks from a short list (kind, stance). This module splits passages into
sentences (step A), checks that every copied span is really in its sentence, works out the year and
era (step F), writes the stored statement (step G) and the gaps (step H), and scores model answers
against the answer key field by field.
"""
import re

from seed_history import ERAS

SLOTS = ("subject", "action", "agent", "when", "where")
TAG_KINDS = ("people", "groups", "places", "things")
KINDS = ("event", "plan_or_target", "opinion", "allegation", "denial", "reported_words")
STANCES = ("supports", "opposes", "criticises", "neutral")
# A record whose own date is the event's date (its date may stand in for a missing "when").
DATED_BY_RECORD = ("contemporary", "primary")
LEADING = re.compile(r"^(the|a|an|in|on|by|at)\s+", re.I)
# Subjects that need the name from the record notes ("He was assassinated", "The murder took place").
VAGUE_SUBJECTS = {"he", "she", "they", "it", "the murder", "the victim"}
ABBREVIATION = re.compile(r"\b(Mr|Mrs|Ms|Dr|No|St|Sir|Gov|Capt)\.")
YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def split_sentences(passage):
    """Step A: sentences of a passage. A full stop ends a sentence only before a capital letter, so
    "Mr. CHAN" and "No. 52" stay whole."""
    text = re.sub(r"\s+", " ", str(passage or "")).strip()
    guarded = ABBREVIATION.sub(lambda m: m.group(1) + "\0", text)
    parts = re.split(r"(?<=[.!?。])\s+(?=[A-Z\"“(])", guarded)
    return [p.replace("\0", ".") for p in parts if p]


def normalise_span(span):
    """Lower-case, single spaces, no leading article or preposition: the form spans are compared in."""
    text = re.sub(r"\s+", " ", str(span or "")).strip().casefold()
    while True:
        stripped = LEADING.sub("", text)
        if stripped == text:
            return text.strip(" ,.;:")
        text = stripped


def span_errors(answer, sentence):
    """Why a model's answer is not usable: a slot or tag that is not an exact part of the sentence.
    An empty slot is allowed (the sentence does not say it)."""
    errors = []
    for slot in SLOTS:
        value = str(answer.get(slot) or "")
        if value and value not in sentence:
            errors.append(f'{slot} "{value}" is not copied from the sentence')
    for kind in TAG_KINDS:
        for tag in answer.get("tags", {}).get(kind, []) if isinstance(answer.get("tags"), dict) else []:
            if str(tag) not in sentence:
                errors.append(f'{kind} tag "{tag}" is not copied from the sentence')
    return errors


def year_of(when, record):
    """Step F: the event's year from the "when" slot; else from the record's own date, but only for a
    contemporary or primary record (a 2021 yearbook's date is not the 1841 event's)."""
    found = YEAR_RE.search(str(when or ""))
    if found:
        return int(found.group(1))
    if any(word in str(record.get("source_type", "")) for word in DATED_BY_RECORD):
        found = YEAR_RE.search(str(record.get("source_date", "")))
        if found:
            return int(found.group(1))
    return None


def _era_bounds(span):
    years = [int(y) for y in re.findall(r"\d{3,4}", span)]
    if "BCE" in span and len(years) == 1:
        return (-10**6, -years[0])
    if "BCE" in span:
        return (-years[0], years[1])
    if "present" in span:
        return (years[0], 10**6)
    return (years[0], years[1])


def eras_of(year, topic_era=None):
    """Step F: era ids for a year; a boundary year (1842) belongs to both eras. With no year, the era
    of the topic the record was gathered for."""
    if year is None:
        return [topic_era] if topic_era else []
    return [slug for slug, _, span in ERAS if _era_bounds(span)[0] <= year <= _era_bounds(span)[1]]


def write_statement(sentence, fact, record):
    """Step G: the stored statement, written by code: the record's own words in quotes, attributed to
    the record, with the slots as labels. Code never rebuilds prose from slots (that gave "The
    government to put the MPF System in place by 1998"); the history paragraph is written later
    from these statements."""
    labels = []
    who = fact.get("subject") or ""
    if fact.get("subject_from_notes") and (not who or who.casefold() in VAGUE_SUBJECTS):
        labels.append(f'about: {fact["subject_from_notes"]} (from the record notes)')
    if fact.get("agent"):
        labels.append(f'by: {fact["agent"]}')
    if fact.get("when"):
        labels.append(f'when: {fact["when"]}')
    if fact.get("where"):
        labels.append(f'where: {fact["where"]}')
    if fact.get("negated"):
        labels.append("stated as not having happened")
    note = f' [{"; ".join(labels)}]' if labels else ""
    return f'According to {record["institution"]}: "{sentence}"{note}'


def gaps_for(fact, year, single_source=True):
    """Step H: gaps written by code from what the slots leave empty."""
    gaps = []
    if not fact.get("subject") and not fact.get("subject_from_notes"):
        gaps.append("The excerpt does not name who or what this is about.")
    if year is None:
        # Run 39083483800: "On 26 January" was given the gap "no date"; it has a date but no year.
        gaps.append("The excerpt states no year." if fact.get("when") else "The excerpt states no date.")
    if not fact.get("where") and fact.get("kind", ["event"])[0] == "event":
        gaps.append("The excerpt states no place.")
    if single_source:
        gaps.append("Only one source so far (official claim, not yet corroborated).")
    return gaps


def _same_span(got, expected):
    return normalise_span(got) == normalise_span(expected)


def _near_span(got, expected):
    """Equal, or one span inside the other; both empty counts, one empty does not."""
    a, b = normalise_span(got), normalise_span(expected)
    return a == b or bool(a and b and (a in b or b in a))


def score(answers, key):
    """Score model answers against the answer key, field by field.

    answers: {source_id: {"facts": [...], "angle": {...}, "tags": {...}}}. Each expected fact is
    matched to an unused answer fact with the same action (normalised), else one whose action
    contains the expected one or lies inside it ("was opened" / "opened"), else counted as missed.
    Returns {field: [correct, total]} plus "invented_spans" (spans not in the sentence) and, for
    each slot and for tags, "near_<field>": [exact or one span inside the other, total], which
    shows how many misses are only a different span boundary. Slots, negated and kind are counted
    over the facts found only; a missed fact counts under facts_found.
    """
    totals = {k: [0, 0] for k in SLOTS + ("negated", "kind", "facts_found", "view_of", "stance", "tags")
              + tuple(f"near_{slot}" for slot in SLOTS) + ("near_tags",)}
    invented = 0
    for row in key["sentences"]:
        got = answers.get(row["source_id"], {})
        for fact in got.get("facts", []):
            invented += len(span_errors(fact, row["sentence"]))
        invented += len(span_errors({"tags": got.get("tags", {})}, row["sentence"]))
        unused = list(got.get("facts", []))
        for want in row["facts"]:
            totals["facts_found"][1] += 1
            match = (next((f for f in unused if _same_span(f.get("action"), want["action"])), None)
                     or next((f for f in unused if _near_span(f.get("action"), want["action"])), None))
            if not match:
                continue
            unused.remove(match)
            totals["facts_found"][0] += 1
            # Slots and kind are judged on the facts the model found; a missed fact counts once,
            # under facts_found (run 38525325652 failed C on Nemotron, whose kinds were all right,
            # because each missed fact also counted as a wrong kind).
            for slot in SLOTS:
                totals[slot][1] += 1
                totals[f"near_{slot}"][1] += 1
            totals["negated"][1] += 1
            totals["kind"][1] += 1
            for slot in SLOTS:
                totals[slot][0] += _same_span(match.get(slot), want[slot])
                totals[f"near_{slot}"][0] += _near_span(match.get(slot), want[slot])
            totals["negated"][0] += bool(match.get("negated")) == want["negated"]
            totals["kind"][0] += match.get("kind") in want["kind"]
        angle = got.get("angle", {})
        totals["view_of"][1] += 1
        totals["view_of"][0] += _same_span(angle.get("view_of"), row["angle"]["view_of"])
        totals["stance"][1] += 1
        totals["stance"][0] += angle.get("stance") in row["angle"]["stance"]
        for kind in TAG_KINDS:
            want = {normalise_span(t) for t in row["tags"][kind]}
            have = {normalise_span(t) for t in got.get("tags", {}).get(kind, [])}
            totals["tags"][1] += len(want | have)
            totals["tags"][0] += len(want & have)
            # near: a tag that only adds or drops words ("Tatsu Maru case" / "Tatsu Maru") still links.
            near = sum(any(_near_span(h, w) for h in have) for w in want)
            totals["near_tags"][1] += len(want) + sum(not any(_near_span(h, w) for w in want) for h in have)
            totals["near_tags"][0] += near
    totals["invented_spans"] = invented
    return totals
