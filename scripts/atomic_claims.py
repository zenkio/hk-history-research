"""Experimental, provenance-preserving extraction of atomic claims from draft history.

This module is deliberately not wired into the scheduled pipeline yet. It establishes a
testable contract: generated claims must include an excerpt grounded in supplied draft
material, and can be serialized into the existing versioned research-record schema.
"""
import re

from research_record_store import claim_id_for

MAX_CLAIMS = 40
PROMPT_VERSION = 2
CLAIM_TYPES = {
    "date", "place", "person", "cause", "action", "outcome", "quantity",
    "institution", "context", "interpretation", "other",
}
IMPORTANCE = {"core", "supporting"}
SUPPORTING_ONLY_TYPES = {"cause", "context", "interpretation", "other"}
CORE_CONTEXT_PATTERN = re.compile(
    r"\b(?:aim(?:s|ed)? to|intend(?:s|ed)? to|intended|view(?:s|ed)?|interpret(?:s|ed)?|"
    r"argu(?:e|es|ed)|believ(?:e|es|ed)|consider(?:s|ed)|fear(?:s|ed)|highlight(?:s|ed)|"
    r"demonstrat(?:e|es|ed)|illustrat(?:e|s|ed)|reflect(?:s|ed)|suggest(?:s|ed)|"
    r"symboli[sz](?:e|es|ed)|mark(?:s|ed)?|indicat(?:e|es|ed)|reveal(?:s|ed)|"
    r"identif(?:y|ies|ied)|faced pressure|debate(?:d)?|watershed|effectively|increasingly|"
    r"capable of coordinated|modernization|modernisation|shift(?:ed)? responsibility)\b",
    re.IGNORECASE,
)
NEGATION_OR_DENIAL = re.compile(
    r"\b(?:not|never|no|neither|without|none|nothing|cannot|can't|didn't|doesn't|"
    r"wasn't|weren't|isn't|aren't|hasn't|haven't|hadn't|failed|rejected|refused|"
    r"denied|prohibited|forbidden|impossible)\b",
    re.IGNORECASE,
)


def _number_tokens(value):
    """Return normalised numeric fragments so claims cannot invent dates or quantities."""
    return {token.replace(",", "") for token in re.findall(r"\d[\d,]*", str(value or ""))}


def _faithful_to_excerpt(claim_text, excerpt):
    """Conservative guards against adding precise numbers or reversing a proposition."""
    if not _number_tokens(claim_text).issubset(_number_tokens(excerpt)):
        return False
    return bool(NEGATION_OR_DENIAL.search(claim_text)) == bool(NEGATION_OR_DENIAL.search(excerpt))

def _normalise_importance(claim_text, claim_type, importance):
    """Keep core priority for event-defining facts, not interpretation or context."""
    if importance not in IMPORTANCE:
        importance = "supporting"
    if claim_type in SUPPORTING_ONLY_TYPES or CORE_CONTEXT_PATTERN.search(claim_text):
        return "supporting"
    return importance


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

Importance rules:
- Mark a claim core only if it is necessary to identify the event: its date/year, place, primary actor, defining action, or immediate direct outcome.
- Mark background, context, causes, motives, stakeholder opinions, interpretations, and later consequences as supporting.
- Never mark cause, context, interpretation, or other claim types as core. If uncertain, choose supporting.

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
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalised_contains(haystack, needle):
    return _normalise_space(needle).casefold() in _normalise_space(haystack).casefold()


def validate_atomic_claims(response, source_material, max_claims=MAX_CLAIMS):
    """Validate model output and require every claim to cite its own source excerpt.

    Returns normalized claim dictionaries. Raises ValueError for malformed or wholly
    unusable output so callers can fail closed rather than silently accepting inventions.
    """
    if not isinstance(response, dict) or not isinstance(response.get("claims"), list):
        raise ValueError("Atomic claim extraction must return a JSON object with a claims list")

    if len(response["claims"]) > max_claims:
        raise ValueError(
            f"Atomic claim extraction returned {len(response['claims'])} claims; "
            f"maximum is {max_claims}. Refusing to truncate potentially important claims."
        )

    validated = []
    seen = set()
    for item in response["claims"]:
        if not isinstance(item, dict):
            continue
        text = _normalise_space(item.get("text"))
        excerpt = _normalise_space(item.get("source_excerpt"))
        claim_type = str(item.get("claim_type") or "other").strip().lower()
        importance = str(item.get("importance") or "supporting").strip().lower()
        if not text or not excerpt or not _normalised_contains(source_material, excerpt):
            continue
        if not _faithful_to_excerpt(text, excerpt):
            continue
        if claim_type not in CLAIM_TYPES:
            claim_type = "other"
        importance = _normalise_importance(text, claim_type, importance)
        key = _normalise_space(text).casefold()
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
    source_material = "\n".join([str(draft_text or ""), *[str(item) for item in existing]])
    prompt = ATOMIC_CLAIM_PROMPT.format(
        title=str(title or ""),
        date=str(date or ""),
        draft_text=str(draft_text or "")[:18000],
        existing_claims="\\n".join(f"- {item}" for item in existing)[:6000] or "(none)",
    )
    response, model, _ = pool.generate_json("evidence", prompt)
    claims = validate_atomic_claims(response, source_material)
    return {"claims": claims, "model": model, "prompt_version": PROMPT_VERSION}
