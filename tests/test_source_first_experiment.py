import copy
import hashlib
import json
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_first_experiment as source_first


def packet():
    return {
        "event_question": "What happened during the 1841 landing and what did the records establish?",
        "sources": [{
            "source_id": "hk-yearbook-2021",
            "title": "Hong Kong Yearbook 2021, Chapter 22",
            "institution": "Hong Kong Government",
            "source_date": "2021",
            "url": "https://www.yearbook.gov.hk/2021/en/pdf/E22.pdf",
            "source_type": "official_retrospective",
            "locator": "Chapter 22, printed p. 322, lines 122-126",
            "language": "en",
            "inspection_status": "inspected",
            "processing_status": "approved_for_internal_research",
            "processing_basis": "Internal research only; short excerpt for source-first analysis, with attribution retained; no public redistribution.",
            "public_reuse_status": "not_approved",
            "creator_perspective": "Hong Kong government retrospective account",
            "passage": "On 26 January, a naval landing party hoisted the British flag at Possession Point and the island was formally occupied.",
        }],
    }


def valid_result():
    return {
        "record_statements": [{
            "statement_id": "S1",
            "source_id": "hk-yearbook-2021",
            "statement": "The Yearbook retrospectively states that the island was formally occupied on 26 January.",
            "source_excerpt": "the island was formally occupied",
            "locator": "Chapter 22, printed p. 322, lines 122-126",
            "statement_kind": "retrospective_summary",
        }],
        "candidate_claims": [{
            "claim_id": "C1",
            # Only the passage's own words: it gives no year, and names neither "Hong Kong" nor the
            # Yearbook (screen_claims sets aside unstated years and names; attribution is added by code).
            "text": "The island was formally occupied on 26 January after the British flag was hoisted.",
            "claim_type": "date",
            "source_statement_ids": ["S1"],
            "status": "unverified",
        }],
        "perspectives": [{
            "perspective_id": "P1",
            "actor_or_institution": "Hong Kong government retrospective account",
            "documented_position": "The account describes a formal occupation on 26 January.",
            "source_statement_ids": ["S1"],
            "known_limits": "A retrospective account does not establish the Qing court's position.",
        }],
        "gaps": ["Locate a contemporaneous Chinese-side record."],
    }


def test_prompt_contains_source_records_but_not_draft_prose():
    prompt = source_first.build_source_first_prompt(packet())
    assert "INSPECTED SOURCE RECORDS" in prompt
    assert "Do not use outside knowledge" in prompt
    assert "draft_text" not in prompt


def test_source_packet_rejects_old_draft_input():
    value = packet()
    value["draft_text"] = "The old AI paragraph."
    try:
        source_first.validate_source_packet(value)
        assert False, "draft input must fail closed"
    except ValueError as exc:
        assert "must not contain old draft prose" in str(exc)


def test_source_packet_rejects_catalogue_only_and_unreviewed_rights():
    value = packet()
    value["sources"][0]["inspection_status"] = "catalogue_only"
    try:
        source_first.validate_source_packet(value)
        assert False, "catalogue metadata must not be treated as a passage"
    except ValueError as exc:
        assert "not marked inspected" in str(exc)
    value = packet()
    value["sources"][0]["processing_status"] = "review_required"
    try:
        source_first.validate_source_packet(value)
        assert False, "rights review must fail closed"
    except ValueError as exc:
        assert "not passed internal processing review" in str(exc)
    value = packet()
    value["sources"][0]["public_reuse_status"] = "approved"
    try:
        source_first.validate_source_packet(value)
        assert False, "processing approval must not imply public reuse"
    except ValueError as exc:
        assert "public reuse must remain explicitly not approved" in str(exc)
    value = packet()
    value["sources"][0]["processing_basis"] = "Unknown"
    try:
        source_first.validate_source_packet(value)
        assert False, "processing basis must be scoped to internal research"
    except ValueError as exc:
        assert "scoped internal-research processing basis" in str(exc)


def test_output_requires_exact_passage_excerpt_and_valid_links():
    report = source_first.validate_source_first_output(packet(), valid_result())
    assert report["status"] == "unverified"
    assert report["live_records_modified"] is False
    bad = valid_result()
    bad["record_statements"][0]["source_excerpt"] = "British forces surrendered the island"
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "invented excerpt must fail"
    except ValueError as exc:
        assert "not an exact supplied-source excerpt" in str(exc)


def test_output_cannot_mark_claim_verified_or_emit_narrative():
    bad = valid_result()
    bad["candidate_claims"][0]["status"] = "verified"
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "claims must remain unverified"
    except ValueError as exc:
        assert "must remain unverified" in str(exc)
    bad = valid_result()
    bad["narrative_preview"] = "The British occupied Hong Kong."
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "source-first extraction cannot write a narrative"
    except ValueError as exc:
        assert "cannot output a narrative" in str(exc)


def test_perspective_requires_source_statement_provenance():
    bad = valid_result()
    bad["perspectives"][0]["source_statement_ids"] = ["S999"]
    try:
        source_first.validate_source_first_output(packet(), bad)
        assert False, "unsupported perspective must fail"
    except ValueError as exc:
        assert "link to existing record statements" in str(exc)


# Revision 2: findings from the review of v2.1 run 38169605722 (statement kinds that ignored the
# source type, a hedged guess kept as a claim, outputs that could not be traced to their packet).

def contemporary_source(**changes):
    source = {
        "source_id": "paper-1908",
        "title": "A contemporary newspaper report",
        "institution": "A newspaper",
        "source_date": "1908-12-04",
        "url": "https://example.org/paper-1908",
        "source_type": "contemporary_newspaper_report",
        "locator": "Section 'Cause'",
        "language": "en",
        "inspection_status": "inspected",
        "processing_status": "approved_for_internal_research",
        "processing_basis": "Internal research only; short excerpt for source-first analysis.",
        "public_reuse_status": "not_approved",
        "passage": "Shops were closed for two days after the meeting, the report says.",
    }
    source.update(changes)
    return source


def statement(sid, source_id, excerpt, locator, kind):
    return {"statement_id": sid, "source_id": source_id, "statement": f"The record states: {excerpt}",
            "source_excerpt": excerpt, "locator": locator, "statement_kind": kind}


def expect_error(value, result, message):
    try:
        source_first.validate_source_first_output(value, result)
        assert False, f"expected failure: {message}"
    except ValueError as exc:
        assert message in str(exc)


def test_retrospective_source_cannot_yield_official_action_or_assertion():
    """Run 38157183242 labelled a later Yearbook summary as an official action."""
    for kind in ("official_action", "assertion"):
        bad = valid_result()
        bad["record_statements"][0]["statement_kind"] = kind
        expect_error(packet(), bad, f"from a retrospective source cannot be {kind}")


def test_contemporary_record_is_never_a_retrospective_summary():
    """Run 38169605722 labelled a 1908 newspaper report a retrospective summary."""
    value = packet()
    value["sources"].append(contemporary_source())
    result = valid_result()
    result["record_statements"].append(statement(
        "S2", "paper-1908", "Shops were closed for two days", "Section 'Cause'", "retrospective_summary"))
    expect_error(value, result, "from a contemporary record cannot be a retrospective_summary")
    result["record_statements"][1]["statement_kind"] = "opinion"
    source_first.validate_source_first_output(value, result)


def test_hedged_claim_is_set_aside_not_kept():
    """Run 38169605722 kept a claim ending '(presumably in ...)', a guess the record never made."""
    value = packet()
    result = valid_result()
    result["candidate_claims"].append({
        "claim_id": "C2", "text": "The landing party presumably met no resistance.",
        "claim_type": "action", "source_statement_ids": ["S1"], "status": "unverified"})
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1"]
    assert rejected[0]["claim_id"] == "C2"
    assert "speculative wording: presumably" in rejected[0]["rejection_reasons"]


def test_claim_year_must_come_from_linked_passage_or_record_date():
    value = packet()
    value["sources"][0]["passage"] += " The treaty was signed in 1842."
    result = valid_result()
    result["candidate_claims"] = [
        {"claim_id": "C1", "text": "The treaty was signed in 1842.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
        {"claim_id": "C2", "text": "The flag at Possession Point was hoisted before 2021.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
        {"claim_id": "C3", "text": "The island was formally occupied in 1843.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
    ]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1", "C2"]
    assert rejected[0]["rejection_reasons"] == ["year not in the linked records: 1843"]


def test_years_in_chinese_numerals_count_as_in_the_record():
    assert source_first.years_in("于一八四二年签订") == {"1842"}
    assert source_first.years_in("1841年至二〇〇〇年") == {"1841", "2000"}


class FakePool:
    """Asks parse() for each reply in turn, like ModelPool: a ValueError means ask again."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.models = {"OpenRouter Large": {"api_id": "vendor/large-model:free"}}
        self.calls = 0

    def generate_text(self, role, prompt, parse, only=None):
        assert role == "evidence" and "INSPECTED SOURCE RECORDS" in prompt
        for text in self.replies:
            self.calls += 1
            try:
                return parse(text), "OpenRouter Large", []
            except (ValueError, KeyError, TypeError):
                continue
        raise RuntimeError("no usable reply")


def test_invalid_reply_is_retried_and_run_is_traceable_to_packet_and_model():
    value = packet()
    zh = contemporary_source(source_id="zh-record", language="zh", source_type="official_policy_retrospective",
                             passage="该条约于一八四二年签订，此后由双方政府分别批准并生效。", locator="第1段")
    value["sources"].append(zh)
    good = valid_result()
    good["record_statements"].append(statement("S2", "zh-record", "该条约于一八四二年签订", "第1段", "retrospective_summary"))
    good["candidate_claims"].append({"claim_id": "C2", "text": "A treaty was signed in 1842.", "claim_type": "date",
                                     "source_statement_ids": ["S2"], "status": "unverified"})
    bad = json.loads(json.dumps(good))
    bad["record_statements"][0]["source_excerpt"] = "an invented excerpt"
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    pool = FakePool([json.dumps(bad), json.dumps(good, ensure_ascii=False)])

    out = source_first.run_source_first(value, pool, "topic.json", raw)

    assert pool.calls == 2
    m = out["manifest"]
    assert m["model_api_id"] == "vendor/large-model:free"
    assert m["packet_file"] == "topic.json"
    assert m["packet_git_blob_sha"] == hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
    assert len(m["prompt_sha256"]) == 64 and m["prompt_revision"] == source_first.PROMPT_REVISION
    assert m["candidate_claim_count"] == 2 and m["rejected_claim_count"] == 0
    zh_statement = out["result"]["record_statements"][1]
    assert zh_statement["translation_status"] == "model_translation_unverified"
    assert "translation_status" not in out["result"]["record_statements"][0]
    assert out["result"]["candidate_claims"][1]["attribution"] == [{
        "statement_id": "S2", "source_id": "zh-record", "institution": "A newspaper",
        "statement_kind": "retrospective_summary"}]


# Revision 3: the blind second review of run 38177919398 found names, offices and dates filled in
# from record titles and the event question rather than the excerpt.

def claim(cid, text):
    return {"claim_id": cid, "text": text, "claim_type": "other", "source_statement_ids": ["S1"], "status": "unverified"}


def test_names_absent_from_the_excerpt_are_set_aside():
    value = packet()
    value["sources"][0]["passage"] = "He was shot in his classroom by agents sent from the capital in 1901."
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "He was shot in his classroom"
    result["candidate_claims"] = [
        claim("C1", "He was shot in his classroom in 1901."),
        claim("C2", "The teacher Lee Wing was shot in his classroom."),   # name from the title, not the excerpt
        claim("C3", "An anti-Foreign boycott followed the shooting."),    # label from the event question
        claim("C4", "The shooting happened in the colony's capital."),
    ]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1", "C4"]
    assert rejected[0]["rejection_reasons"] == ["name not in the linked records: Lee, Wing"]
    assert rejected[1]["rejection_reasons"] == ["name not in the linked records: anti-Foreign"]


def test_record_context_may_name_the_speaker_and_date():
    value = packet()
    value["sources"][0]["passage"] = "I am opposed to any proposal to set up such a fund in this territory."
    value["sources"][0]["record_context"] = {"speaker": "Mr Alan WONG, member of the Legislative Council",
                                             "record_date": "13 May 1987"}
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "I am opposed to any proposal"
    result["candidate_claims"] = [claim("C1", "Alan Wong of the Legislative Council opposed the fund on 13 May 1987."),
                                  claim("C2", "Alan Wong of LegCo opposed the fund.")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1"]
    assert rejected[0]["rejection_reasons"] == ["name not in the linked records: LegCo"]
    assert '"record_context"' in source_first.build_source_first_prompt(value)


def test_record_context_must_be_text():
    value = packet()
    value["sources"][0]["record_context"] = {"speaker": ""}
    try:
        source_first.validate_source_packet(value)
        assert False, "empty record_context must fail"
    except ValueError as exc:
        assert "record_context must map names to non-empty text" in str(exc)


def test_perspective_position_is_screened_like_a_claim():
    result = valid_result()
    result["perspectives"].append({
        "perspective_id": "P2", "actor_or_institution": "Hong Kong Government (Yearbook)",
        "documented_position": "The occupation took place near Hollywood Road.",
        "source_statement_ids": ["S1"], "known_limits": "Retrospective."})
    kept, rejected = source_first.screen_perspectives(packet(), result)
    assert [p["perspective_id"] for p in kept] == ["P1"]
    assert rejected[0]["rejection_reasons"] == ["name not in the linked records: Hollywood, Road"]


def test_names_are_not_checked_against_translated_records():
    value = packet()
    value["sources"][0].update(language="zh", passage="该条约于一八四二年签订，此后由双方政府分别批准并生效。")
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "该条约于一八四二年签订"
    result["candidate_claims"] = [claim("C1", "The Treaty was signed in 1842."), claim("C2", "The Treaty was signed in 1843.")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1"]
    assert rejected[0]["rejection_reasons"] == ["year not in the linked records: 1843"]


def test_opening_verb_of_a_position_is_not_a_name():
    assert source_first.names_in("Reports the denial to the Governor.") == {"Governor"}
    assert source_first.names_in("Frames the case as the cause.") == set()
    assert source_first.names_in("Clydesdale opposed the fund.") == {"Clydesdale"}


def test_single_quoted_names_and_opening_adverbs_are_read_correctly():
    """Run 38179505829 set aside "the Viceroy denied ... a 'National Disgrace Society'" because the
    closing quote stuck to "Society", and a position opening "Retrospectively records ..."."""
    value = packet()
    value["sources"][0]["passage"] = 'the Viceroy denies the existence of a "National Disgrace Society" in Canton.'
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "the Viceroy denies the existence"
    result["candidate_claims"] = [claim("C1", "The Viceroy denied the existence of a 'National Disgrace Society' in Canton.")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1"] and rejected == []
    assert source_first.names_in("Retrospectively records the Ordinance.") == {"Ordinance"}
