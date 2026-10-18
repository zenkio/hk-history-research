#!/usr/bin/env python3
"""V2.2 consensus: pool the answers of several AIs and keep who backed each claim.

Owner direction 2026-10-18 (hk-history-data experiments/V2_2_MULTI_AI_CONSENSUS_DESIGN.md): AI is not a
program, so a fixed pass mark against one answer key is the wrong test. Several AIs answer the same
single questions; this module pools their facts, tags and angle into claims, and each claim says
which models found it, which did not, and one status:

- settled: two or more models found it, or one found it and another checked it and agreed;
- single: one model found it and nobody has confirmed it;
- questioned: models differ on a detail, or a checking model disagreed (both answers are kept).

The status is about agreement between AIs on what a sentence says. It says nothing about whether the
history is true; verification against independent records is a separate step.
"""
import json
from collections import Counter

import fact_extraction as fx
from extraction_questions import CHOICE_PROMPT, _ask_choice, _numbered

SETTLED, SINGLE, QUESTIONED = "settled", "single", "questioned"
DETAIL_SLOTS = ("subject", "agent", "when", "where")
CHECK_LABELS = ("Yes, the sentence says this", "No, the sentence does not say this", "Not sure")
CHECK_ANSWERS = ("agree", "disagree", "unsure")
TAG_NOUN = {"people": "a person or title", "groups": "a group or organisation",
            "places": "a place", "things": "a law, treaty, ship, scheme or named case"}


def _key(text):
    return fx.normalise_span(text)


def _same(a, b):
    return fx._same_span(a, b) or fx._near_span(a, b)


def _status(backers, conflict):
    if len(backers) >= 2:
        return QUESTIONED if conflict else SETTLED
    return SINGLE


def pool_facts(answers):
    """answers: {model: extract_sentence output}. Facts with the same action (equal, or one inside
    the other) are one claim; a model backs a claim once. Where backers give different non-empty
    values for a slot, the claim is questioned and `variants` lists each value with its models."""
    claims = []
    for model, answer in answers.items():
        for fact in answer.get("facts", []):
            claim = next((c for c in claims if model not in c["backed_by"]
                          and _same(c["action"], fact.get("action"))), None)
            if claim is None:
                claim = {"action": fact.get("action", ""), "backed_by": [], "values": [], "kinds": []}
                claims.append(claim)
            claim["backed_by"].append(model)
            claim["values"].append((model, fact))
            claim["kinds"].append(fact.get("kind") or "")
    out = []
    models = list(answers)
    for claim in claims:
        pooled = {"claim_type": "fact", "action": claim["action"], "backed_by": claim["backed_by"],
                  "not_found_by": [m for m in models if m not in claim["backed_by"]],
                  "negated": any(f.get("negated") for _, f in claim["values"]),
                  "kind": Counter(k for k in claim["kinds"] if k).most_common(1)[0][0] if any(claim["kinds"]) else ""}
        variants = {}
        for slot in DETAIL_SLOTS:
            seen = []  # [value, [models]]
            for model, fact in claim["values"]:
                value = (fact.get(slot) or "").strip()
                if not value:
                    continue
                for entry in seen:
                    if _same(entry[0], value):
                        entry[1].append(model)
                        break
                else:
                    seen.append([value, [model]])
            seen.sort(key=lambda e: -len(e[1]))
            pooled[slot] = seen[0][0] if seen else ""
            if len({_key(e[0]) for e in seen}) > 1 and not _all_nested(seen):
                variants[slot] = {e[0]: e[1] for e in seen}
        pooled["variants"] = variants
        pooled["checked_by"] = []
        pooled["status"] = _status(pooled["backed_by"], bool(variants))
        out.append(pooled)
    return out


def _all_nested(seen):
    """Values where each is inside another ("March 1880" / "3 March 1880") differ only in detail."""
    return all(any(_same(a[0], b[0]) for b in seen if b is not a) for a in seen)


def pool_tags(answers):
    """Tags of one kind that are equal or nested are one claim."""
    out = []
    models = list(answers)
    for kind in fx.TAG_KINDS:
        claims = []
        for model, answer in answers.items():
            for text in answer.get("tags", {}).get(kind, []):
                claim = next((c for c in claims if model not in c["backed_by"] and _same(c["text"], text)), None)
                if claim is None:
                    claim = {"text": text, "backed_by": []}
                    claims.append(claim)
                claim["backed_by"].append(model)
        for claim in claims:
            out.append({"claim_type": f"tag:{kind}", "text": claim["text"], "backed_by": claim["backed_by"],
                        "not_found_by": [m for m in models if m not in claim["backed_by"]],
                        "checked_by": [], "variants": {}, "status": _status(claim["backed_by"], False)})
    return out


def pool_angle(answers):
    """Whose view and stance: one claim each, with every value and its models. Models that all give
    the same value settle it; different values question it."""
    out = {}
    for field in ("view_of", "stance"):
        values = {}
        for model, answer in answers.items():
            value = (answer.get("angle", {}).get(field) or "").strip()
            if value:
                values.setdefault(value, []).append(model)
        backers = [m for models in values.values() for m in models]
        status = SINGLE if len(backers) < 2 else (SETTLED if len(values) == 1 else QUESTIONED)
        out[field] = {"values": values, "status": status}
    return out


def pool_sentence(answers):
    """Everything the models said about one sentence, pooled."""
    return {"facts": pool_facts(answers), "tags": pool_tags(answers), "angle": pool_angle(answers),
            "models": list(answers)}


def claim_text(claim):
    """The claim as a checking model sees it: the words copied from the sentence, no model names."""
    if claim["claim_type"] == "fact":
        parts = [f"{slot}: {claim[slot]}" for slot in ("subject", "action", "agent", "when", "where") if claim.get(slot)]
        if claim.get("negated"):
            parts.append("the sentence says this did NOT happen")
        return "Claim: " + "; ".join(parts)
    noun = TAG_NOUN[claim["claim_type"].split(":", 1)[1]]
    return f"Claim: \"{claim['text']}\" names {noun}."


def cross_check(ask, sentence, claim, log):
    """Another model sees only the sentence and the claim and picks agree, disagree or unsure."""
    question = ("Does the sentence say this? For a name, does the sentence contain it as the kind of "
                "thing stated?")
    prompt = CHOICE_PROMPT.format(question=question, sentence=sentence, about=claim_text(claim),
                                  options=_numbered(CHECK_LABELS))
    answer = _ask_choice(ask, prompt, CHECK_LABELS, "cross_check", log)
    return CHECK_ANSWERS[answer - 1] if answer else "unsure"


def check_singles(pooled, sentence, asks, log):
    """Put every single claim to a model that did not make it (taken in turn, so no model checks
    everything). Agree settles it, disagree questions it, unsure leaves it single."""
    claims = [c for c in pooled["facts"] + pooled["tags"] if c["status"] == SINGLE]
    for turn, claim in enumerate(claims):
        checkers = [m for m in asks if m not in claim["backed_by"]]
        if not checkers:
            log.append({"step": "cross_check", "skipped": "no other model"})
            continue
        model = checkers[turn % len(checkers)]
        try:
            answer = cross_check(asks[model], sentence, claim, log)
        except Exception as exc:  # a checker that fails leaves the claim single
            log.append({"step": "cross_check", "model": model, "error": type(exc).__name__})
            continue
        claim["checked_by"].append({"model": model, "answer": answer})
        if answer == "agree":
            claim["status"] = SETTLED
        elif answer == "disagree":
            claim["status"] = QUESTIONED
    return pooled


def claim_key(claim):
    return _key(claim["action"]) if claim["claim_type"] == "fact" else _key(claim["text"])


def history_rows(run_id, date, source_id, pooled):
    """One row per model and claim: did the model find it, and what became of the claim. Appended
    day after day, these show whether a model's answers change."""
    rows = []
    for claim in pooled["facts"] + pooled["tags"]:
        checks = {c["model"]: c["answer"] for c in claim["checked_by"]}
        for model in pooled["models"]:
            rows.append({"date": date, "run_id": run_id, "model": model, "source_id": source_id,
                         "claim_type": claim["claim_type"], "claim": claim_key(claim),
                         "found": model in claim["backed_by"], "checked": checks.get(model, ""),
                         "status": claim["status"]})
    return rows


def append_history(path, rows):
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_history(path):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def model_report(rows):
    """Per model over these rows: claims it found, how many ended settled, how many it found alone
    and nobody confirmed, how many settled claims it missed, and how many checks it disagreed with."""
    report = {}
    for row in rows:
        entry = report.setdefault(row["model"], {"found": 0, "found_and_settled": 0, "found_alone": 0,
                                                 "missed_settled": 0, "checks_agree": 0, "checks_disagree": 0})
        if row["found"]:
            entry["found"] += 1
            entry["found_and_settled"] += row["status"] == SETTLED
            entry["found_alone"] += row["status"] in (SINGLE, QUESTIONED)
        elif row["status"] == SETTLED:
            entry["missed_settled"] += 1
        entry["checks_agree"] += row["checked"] == "agree"
        entry["checks_disagree"] += row["checked"] == "disagree"
    return report


def changes(previous, current):
    """What moved between two sets of rows: claims whose status changed, and model answers that
    flipped (found before and not now, or the reverse)."""
    def index(rows, value):
        return {(r["source_id"], r["claim_type"], r["claim"], r.get("model")): r[value] for r in rows}
    old_status = {(r["source_id"], r["claim_type"], r["claim"]): r["status"] for r in previous}
    new_status = {(r["source_id"], r["claim_type"], r["claim"]): r["status"] for r in current}
    status = [{"source_id": k[0], "claim": k[2], "was": old_status[k], "now": new_status[k]}
              for k in new_status if k in old_status and old_status[k] != new_status[k]]
    old_found, new_found = index(previous, "found"), index(current, "found")
    flips = [{"model": k[3], "source_id": k[0], "claim": k[2], "was_found": old_found[k], "now_found": new_found[k]}
             for k in new_found if k in old_found and old_found[k] != new_found[k]]
    return {"status_changes": status, "answer_flips": flips}
