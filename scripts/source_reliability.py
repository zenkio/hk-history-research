"""Source reliability for V2.2 verification (owner rule 2026-10-20).

A fact from a reliable source is accepted without a second source; independent support raises its
confidence; only a reliable source may challenge; when sources give different versions, the version
from the highest-scoring source leads (a close call is shown as disputed, never decided by a point).

The scores themselves are research data and live in the private data repository (a JSON table read
with load_table); this module holds only the rules. Every margin is a share of the table's full marks,
so a table scored out of 500 behaves the same as one out of 100. Tier names are labels for ranges:
tuning means moving a number in TIERS or the margins below.
"""
import json
from pathlib import Path

# (name, lowest share of full marks), best first.
TIERS = (("primary_record", 0.90), ("authoritative", 0.75), ("reliable", 0.60), ("cautious", 0.40), ("weak", 0.0))
ACCEPT_FLOOR = 0.60       # a fact from a source below this is a lead, not yet a fact
CHALLENGE_FLOOR = 0.60    # a source below this never challenges
CHALLENGE_MARGIN = 0.10   # nor one this far below the source of the fact
CLOSE_CALL = 0.05         # top versions closer than this (the scoring error of the reviewers) are disputed
CHALLENGE_WEIGHT = 0.5    # a standing challenge from a source at level 1.0 halves the confidence

LEADING, DISPUTED = "leading", "disputed"


def load_table(path):
    """{"full_marks": 100, "sources": {source_id: {"score": 92, "by_kind": {"contested": 50}}}}"""
    table = json.loads(Path(path).read_text(encoding="utf-8"))
    if not table.get("full_marks", 0) > 0:
        raise ValueError("source reliability table needs full_marks above 0")
    return table


def level(table, source_id, kind=None):
    """The source's score as a share of full marks for this kind of claim, None when the table has no score."""
    entry = table["sources"].get(source_id)
    if entry is None:
        return None
    score = (entry.get("by_kind") or {}).get(kind, entry.get("score"))
    return None if score is None else max(0.0, min(1.0, score / table["full_marks"]))


def tier_of(share):
    if share is None:
        return "unrated"
    return next(name for name, low in TIERS if share >= low)


def accepted(share):
    return share is not None and share >= ACCEPT_FLOOR


def may_challenge(challenger, origin):
    """A source challenges only if it is itself reliable and not clearly weaker than the origin source."""
    if challenger is None or origin is None:
        return False
    return challenger >= CHALLENGE_FLOOR and challenger >= origin - CHALLENGE_MARGIN


def support_confidence(levels):
    """Noisy-or over the independent source families that state the fact: more support only raises it."""
    left = 1.0
    for share in levels:
        left *= 1.0 - (share or 0.0)
    return 1.0 - left


def resolve(versions):
    """Decide between versions of one fact.

    versions: [{"value": comparable key, "source_id": str, "family": str, "level": share or None}]
    Returns {"status": leading|disputed, "leading": value, "confidence": share, "accepted": bool,
             "challenges": [...], "noted_disputes": [...], "versions": {value: best level}}
    """
    by_value = {}
    for v in versions:
        by_value.setdefault(v["value"], []).append(v)

    def best(items):
        return max((i["level"] or 0.0) for i in items)

    ranked = sorted(by_value, key=lambda value: best(by_value[value]), reverse=True)
    lead = ranked[0]
    lead_level = best(by_value[lead])
    families = {}
    for item in by_value[lead]:           # the same family counts once, at its best level
        families[item["family"]] = max(families.get(item["family"], 0.0), item["level"] or 0.0)
    confidence = support_confidence(families.values())
    status = LEADING
    if len(ranked) > 1 and lead_level - best(by_value[ranked[1]]) < CLOSE_CALL:
        status = DISPUTED
    challenges, noted = [], []
    strongest = 0.0
    for value in ranked[1:]:
        for item in by_value[value]:
            record = {"value": value, "source_id": item["source_id"], "level": item["level"]}
            if may_challenge(item["level"], lead_level):
                challenges.append(record)
                strongest = max(strongest, item["level"])
            else:
                noted.append(record)
    confidence *= 1.0 - CHALLENGE_WEIGHT * strongest
    return {"status": status, "leading": lead, "confidence": round(confidence, 4),
            "accepted": accepted(lead_level) and status == LEADING, "challenges": challenges,
            "noted_disputes": noted, "versions": {value: best(by_value[value]) for value in ranked}}
