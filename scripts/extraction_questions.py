#!/usr/bin/env python3
"""V2.2 steps B-E: one small question per model call, checked by code.

Design (hk-history-data experiments/V2_2_WEAK_MODEL_EXTRACTION_DESIGN.md). Each question shows one
sentence and asks the model either to copy words from it into labelled lines (facts, tags) or to
answer with one number from a numbered list (kind, whose view, stance). Answers are plain labelled
lines, not JSON: weak models break JSON far more often than they break "when: 1901".

Code checks every answer: a copied span must be an exact part of the sentence and a number must be
on the list. A bad answer is asked once more with the exact problems listed; what is still bad is
dropped and logged, never repaired by code.

`ask` is any function prompt -> reply text, so tests pass a fake and the scoring script passes a
model from the pool.
"""
import re

from fact_extraction import KINDS, SLOTS, STANCES, TAG_KINDS, span_errors

MAX_FACTS = 3
# Record-note fields that name whose words a record gives (speaker of a debate, author of a letter).
VOICE_FIELDS = ("speaker", "author", "publisher", "reported_position_of")
SOMEONE_ELSE = "someone else named in the sentence"

KIND_LABELS = {
    "event": "something that happened or was done",
    "plan_or_target": "a plan, target or intention for the future",
    "opinion": "a judgement or opinion (good, bad, important, the cause of)",
    "allegation": "an accusation that someone did something wrong",
    "denial": "someone saying something is not true or did not happen",
    "reported_words": "words or a view the record says someone else said",
}
STANCE_LABELS = {
    "supports": "speaks for it (says it is good or should happen)",
    "opposes": "speaks against it (says it should not happen)",
    "criticises": "blames or condemns someone",
    "neutral": "only reports it, without taking a side",
}

FACTS_PROMPT = """Copy facts from one sentence.
Copy words exactly as they are written in the sentence. Never add, change, shorten or explain words.
Leave a line empty after the colon when the sentence does not say it.

For each fact write these 7 lines:
FACT
subject: who or what the fact is about
action: what happened or was done (the verb and its object; leave out "not")
agent: who did it, only when the sentence names someone other than the subject
when: the date or time the sentence gives for this fact
where: the place the sentence gives for this fact
not_happened: yes if the sentence says it did not happen, otherwise no

Write at most 3 facts. If the sentence states no fact, write only: NONE

Example
Sentence: On 3 March 1850, the harbour office was opened at Pier Head by the Harbour Master.
FACT
subject: the harbour office
action: was opened
agent: the Harbour Master
when: 3 March 1850
where: Pier Head
not_happened: no

Example
Sentence: The council did not approve the new bridge, and the mayor resigned in 1902.
FACT
subject: The council
action: approve the new bridge
agent:
when:
where:
not_happened: yes
FACT
subject: the mayor
action: resigned
agent:
when: 1902
where:
not_happened: no

Now the real sentence.
Sentence: {sentence}
"""

TAGS_PROMPT = """List the names in one sentence, copied exactly as they are written in it.
people: persons or titles of persons (for example a governor)
groups: organisations, governments, armies, companies, societies
places: countries, cities, districts, streets, buildings
things: laws, treaties, ships, schemes, named cases or events
Separate several names with " ; ". Leave a line empty after the colon when there are none.
Copy only names, not whole phrases. Never add a name that is not in the sentence.

Example
Sentence: On 3 March 1850, the harbour office was opened at Pier Head by the Harbour Master under the Harbour Ordinance.
people: Harbour Master
groups: harbour office
places: Pier Head
things: Harbour Ordinance

Now the real sentence.
Sentence: {sentence}
"""

CHOICE_PROMPT = """{question}
Sentence: {sentence}
{about}
{options}
Answer with the number only."""

VIEW_PROMPT = """Whose view or words does this sentence give?
It comes from a record by {institution}.
Sentence: {sentence}
{options}
Answer with the number only. If you choose {other}, write the number, a colon, and the name copied exactly from the sentence (for example "{other}: the Harbour Master")."""


def _numbered(labels):
    return "\n".join(f"{i}. {label}" for i, label in enumerate(labels, 1))


def _unquote(value):
    """Drop quotes the model put around a whole answer; keep quotes that are part of the span."""
    value = value.strip()
    if len(value) > 1 and value[0] in '"“' and value[-1] in '"”' and value.count('"') + value.count('“') <= 2:
        return value[1:-1].strip()
    return value


def _lines(text):
    return [line.strip().strip("*").strip() for line in str(text or "").splitlines()]


def parse_facts(text):
    """FACT blocks of "slot: value" lines -> list of fact dicts. Unknown lines are ignored."""
    facts, current = [], None
    for line in _lines(text):
        if line.upper().rstrip(":") == "FACT":
            current = {slot: "" for slot in SLOTS}
            current["negated"] = False
            facts.append(current)
            continue
        if current is None or ":" not in line:
            continue
        label, value = (part.strip() for part in line.split(":", 1))
        label = label.lower()
        value = _unquote(value)
        if label in SLOTS:
            current[label] = value
        elif label == "not_happened":
            current["negated"] = value.lower().startswith("y")
    return facts


def fact_errors(fact, sentence):
    errors = span_errors(fact, sentence)
    if not fact.get("action"):
        errors.append("action is empty")
    return errors


def parse_tags(text):
    tags = {kind: [] for kind in TAG_KINDS}
    for line in _lines(text):
        label, _, value = line.partition(":")
        if label.strip().lower() in tags and value.strip():
            tags[label.strip().lower()] = [_unquote(t) for t in value.split(";") if t.strip()]
    return tags


def parse_choice(text, count):
    """The first number in the reply, if it is on the list (1..count); else None."""
    found = re.search(r"\d+", str(text or ""))
    number = int(found.group()) if found else 0
    return number if 1 <= number <= count else None


def _retry_prompt(prompt, errors):
    problems = "\n".join(f"- {e}" for e in errors)
    return (f"{prompt}\nYour previous answer had these problems:\n{problems}\n"
            "Answer again. Copy words exactly from the sentence, or leave the line empty.")


def ask_facts(ask, sentence, log):
    """Step B. Facts whose spans are still wrong after one retry are dropped and logged."""
    prompt = FACTS_PROMPT.format(sentence=sentence)
    facts = parse_facts(ask(prompt))[:MAX_FACTS]
    errors = [e for f in facts for e in fact_errors(f, sentence)]
    if errors:
        log.append({"step": "facts", "retry": errors})
        facts = parse_facts(ask(_retry_prompt(prompt, errors)))[:MAX_FACTS]
    kept = []
    for fact in facts:
        bad = fact_errors(fact, sentence)
        if bad:
            log.append({"step": "facts", "dropped": fact, "errors": bad})
        else:
            kept.append(fact)
    return kept


def ask_tags(ask, sentence, log):
    """Step E. Tags not copied from the sentence after one retry are dropped and logged."""
    prompt = TAGS_PROMPT.format(sentence=sentence)
    tags = parse_tags(ask(prompt))
    errors = span_errors({"tags": tags}, sentence)
    if errors:
        log.append({"step": "tags", "retry": errors})
        tags = parse_tags(ask(_retry_prompt(prompt, errors)))
    for kind in TAG_KINDS:
        bad = [t for t in tags[kind] if t not in sentence]
        if bad:
            log.append({"step": "tags", "dropped": bad})
        tags[kind] = [t for t in tags[kind] if t in sentence]
    return tags


def _ask_choice(ask, prompt, labels, step, log):
    answer = parse_choice(ask(prompt), len(labels))
    if answer is None:
        log.append({"step": step, "retry": [f"answer was not a number from 1 to {len(labels)}"]})
        answer = parse_choice(ask(_retry_prompt(prompt, [f"answer with one number from 1 to {len(labels)}"])),
                              len(labels))
    if answer is None:
        log.append({"step": step, "dropped": "no number on the list"})
    return answer


def ask_kind(ask, sentence, fact, log):
    """Step C: one choice from KINDS for one fact."""
    about = "Fact: " + " ".join(fact.get(s, "") for s in ("subject", "action") if fact.get(s))
    labels = [KIND_LABELS[k] for k in KINDS]
    prompt = CHOICE_PROMPT.format(question="What kind of statement is this fact, as the sentence gives it?",
                                  sentence=sentence, about=about, options=_numbered(labels))
    answer = _ask_choice(ask, prompt, labels, "kind", log)
    return KINDS[answer - 1] if answer else ""


def voices(record):
    """Step D's list of whose view a sentence may give: the record's institution, then the people
    the record notes name. A note like "Mr X (attendance list: ...), member of ..." becomes "Mr X"."""
    found = [record.get("institution", "")]
    notes = record.get("record_context") or {}
    for field in VOICE_FIELDS:
        value = re.split(r" \(|, member of ", str(notes.get(field) or ""))[0].strip()
        if value and value not in found:
            found.append(value)
    return [v for v in found if v]


def ask_view(ask, sentence, record, log):
    """Step D, whose view: a voice from the record, or a name copied from the sentence."""
    options = voices(record) + [SOMEONE_ELSE]
    prompt = VIEW_PROMPT.format(institution=record.get("institution", ""), sentence=sentence,
                                options=_numbered(options), other=len(options))
    reply = ask(prompt)
    answer = parse_choice(reply, len(options))
    name = _unquote(str(reply).partition(":")[2].strip().rstrip(".")) if answer == len(options) else ""
    if answer is None or (answer == len(options) and (not name or name not in sentence)):
        problem = (f"answer with one number from 1 to {len(options)}" if answer is None
                   else f'the name after "{len(options)}:" must be copied exactly from the sentence')
        log.append({"step": "view_of", "retry": [problem]})
        reply = ask(_retry_prompt(prompt, [problem]))
        answer = parse_choice(reply, len(options))
        name = _unquote(str(reply).partition(":")[2].strip().rstrip(".")) if answer == len(options) else ""
        if answer == len(options) and (not name or name not in sentence):
            answer = None
    if answer is None:
        log.append({"step": "view_of", "dropped": "no usable answer"})
        return ""
    return name if answer == len(options) else options[answer - 1]


def ask_stance(ask, sentence, view_of, log):
    """Step D, stance: one choice from STANCES for the sentence's main point."""
    labels = [STANCE_LABELS[s] for s in STANCES]
    prompt = CHOICE_PROMPT.format(
        question="What does the sentence do with what it is about?",
        sentence=sentence, about=f"Whose view: {view_of}" if view_of else "", options=_numbered(labels))
    answer = _ask_choice(ask, prompt, labels, "stance", log)
    return STANCES[answer - 1] if answer else ""


def extract_sentence(ask, sentence, record):
    """Steps B-E for one sentence: {"facts": [... with kind], "angle": {...}, "tags": {...}, "log": [...]}."""
    log = []
    facts = ask_facts(ask, sentence, log)
    for fact in facts:
        fact["kind"] = ask_kind(ask, sentence, fact, log)
    view_of = ask_view(ask, sentence, record, log)
    return {"facts": facts,
            "angle": {"view_of": view_of, "stance": ask_stance(ask, sentence, view_of, log)},
            "tags": ask_tags(ask, sentence, log),
            "log": log}
