"""Experimental, provenance-preserving extraction of atomic claims from draft history.

This module is deliberately not wired into the scheduled pipeline yet. It establishes a
testable contract: generated claims must include an excerpt grounded in supplied draft
material, and can be serialized into the existing versioned research-record schema.
"""
import re

from research_record_store import claim_id_for

MAX_CLAIMS = 40
CLAIM_TYPES = {
    "date", "place", "person", "cause", "action", "outcome", "quantity",
    "institution", "context", "interpretation", "other",
}
IMPORTANCE = {"core", "supporting"}
RECORD_CLAIM_TYPES = {
    "date": "date",
    "place": "place",
    "person": "people",
    "cause": "cause",
    "action": "action",
    "outcome": "outcome",
    "quantity": "scale",
    "institution": "context",
    "context": "context",
    "interpretation": "other",
    "other": "other",
}

ATOMIC_CLAIM_PROMPT = """Extract independently testable historical claims from this Hong Kong history draft.

A claim must express one factual or interpretive proposition that can be researched independently.
Split compound statements when their parts could be true/false separately or need different evidence.
Keep exact dates, places, people, causes, actions, outcomes, quantities and interpretations precise.
Do not add facts from your own knowledge. Do not turn speculation into fact; preserve uncertainty in the wording.
Avoid duplicate claims. Include claims already listed as "claims to verify" if they are useful, but merge exact duplicates.

For every claim return:
- text: one concise, standalone claim, without adding information absent from the source
- source_excerpt: an exact excerpt copied from the supplied source text that gives rise to the claim
- claim_type: one of date, place, person, cause, action, outcome, quantity, institution, context, interpretation, other
- importance: core or supporting

Return JSON only: {{"claims":[{{"text":"...","source_excerpt":"...","claim_type":"action","importance":"core"}}]}}

Title: {title}
Date: {date}

Draft prose:
{draft_text}

Existing claims to verify:
{existing_claims}
"""


def _normalise_space(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip()


def _normalised_contains(haystack, needle):
    return _normalise_space(needle).casefold() in _normalise_space(haystack).casefold()


def validate_atomic_claims(response, source_material, max_claims=MAX_CLAIMS):
    """Validate model output and require every claim to cite its own source excerpt.

    Returns normalized claim dictionaries. Raises ValueError for malformed or wholly
    unusable output so callers can fail closed rather than silently accepting inventions.
    """
    if not isinstance(response, dict) or not isinstance(response.get("claims"), list):
        raise ValueError("Atomic claim extraction must return a JSON object with a claims list")

    validated = []
    seen = set()
    for item in response["claims"][:max_claims]:
        if not isinstance(item, dict):
            continue
        text = _normalise_space(item.get("text"))
        excerpt = _normalise_space(item.get("source_excerpt"))
        claim_type = str(item.get("claim_type") or "other").strip().lower()
        importance = str(item.get("importance") or "supporting").strip().lower()
        if not text or not excerpt or not _normalised_contains(source_material, excerpt):
            continue
        if claim_type not in CLAIM_TYPES:
            claim_type = "other"
        if importance not in IMPORTANCE:
            importance = "supporting"
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        validated.append({
            "text": text,
            "source_excerpt": excerpt,
            "claim_type": claim_type,
            "importance": importance,
            "extraction": "ai_with_source_excerpt",
        })

    if not validated:
        raise ValueError("Atomic claim extraction produced no claims grounded in the supplied draft")
    return validated


def build_claim_records(claims, *, event_id, source_page, model, prompt_version, created_at):
    """Serialize extracted claims as existing schema-v1 records without asserting truth.

    IDs are deterministic for the same page and claim text. Re-running extraction therefore
    does not create random IDs; version/supersession policy remains the caller's responsibility.
    """
    if not re.fullmatch(r"event:[a-z0-9][a-z0-9._-]*", str(event_id or "")):
        raise ValueError("event_id must be a schema-valid event: identifier")
    if not str(source_page or "").strip():
        raise ValueError("source_page is required")
    if not str(created_at or "").strip():
        raise ValueError("created_at is required")

    records = []
    for claim in claims:
        text = _normalise_space(claim.get("text"))
        excerpt = _normalise_space(claim.get("source_excerpt"))
        if not text or not excerpt:
            raise ValueError("Each claim record requires text and source_excerpt provenance")
        record_id = claim_id_for(event_id, text)
        records.append({
            "record_type": "claim",
            "schema_version": 1,
            "id": record_id,
            "event_id": event_id,
            "text": text,
            "claim_type": RECORD_CLAIM_TYPES.get(claim.get("claim_type"), "other"),
            "status": "unverified",
            "importance": claim.get("importance") if claim.get("importance") in IMPORTANCE else "supporting",
            "created_from": "ai_draft",
            "created_at": created_at,
            "updated_at": created_at,
            "provenance": {
                "source_page": source_page,
                "source_excerpt": excerpt,
                "extraction": claim.get("extraction", "ai_with_source_excerpt"),
                "model": model,
                "prompt_version": prompt_version,
            },
            "is_current": True,
            "superseded_at": None,
        })
    return records


def extract_atomic_claims(pool, *, title, date, draft_text, existing_claims=()):
    """Ask the configured AI pool to extract claims, then validate source provenance."""
    existing = list(existing_claims or ())
    source_material = "\\n".join([str(draft_text or ""), *[str(item) for item in existing]])
    prompt = ATOMIC_CLAIM_PROMPT.format(
        title=str(title or ""),
        date=str(date or ""),
        draft_text=str(draft_text or "")[:18000],
        existing_claims="\\n".join(f"- {item}" for item in existing)[:6000] or "(none)",
    )
    response, model, _ = pool.generate_json("evidence", prompt)
    claims = validate_atomic_claims(response, source_material)
    return {"claims": claims, "model": model, "prompt_version": 1}
