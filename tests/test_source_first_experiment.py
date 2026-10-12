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
    value["sources"][0]["passage"] += " The Treaty of Nanking was signed in 1842."
    result = valid_result()
    result["candidate_claims"] = [
        {"claim_id": "C1", "text": "The Treaty of Nanking was signed in 1842.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
        {"claim_id": "C2", "text": "The British flag at Possession Point was hoisted before 2021.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
        {"claim_id": "C3", "text": "The British formally occupied the island in 1843.", "claim_type": "date",
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
        self.roles, self.prompts = [], []

    def generate_text(self, role, prompt, parse, only=None):
        assert role in source_first.MODEL_ROLES and "INSPECTED SOURCE RECORDS" in prompt
        self.roles.append(role)
        self.prompts.append(prompt)
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
                             passage="该条约于一八四二年签订，此后由双方政府分别批准并生效。", locator="第1段",
                             passage_en="The Treaty of Nanking was signed in 1842 and then ratified by both governments.",
                             passage_en_by="Packet curator, literal translation")
    value["sources"].append(zh)
    good = valid_result()
    good["record_statements"].append(statement("S2", "zh-record", "该条约于一八四二年签订", "第1段", "retrospective_summary"))
    good["candidate_claims"].append({"claim_id": "C2", "text": "The Treaty of Nanking was signed in 1842.", "claim_type": "date",
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
    value["sources"][0]["passage"] = "Chan Ming was shot in his classroom by agents sent from the capital in 1901."
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "Chan Ming was shot in his classroom"
    result["candidate_claims"] = [
        claim("C1", "Chan Ming was shot in his classroom in 1901."),
        claim("C2", "The teacher Lee Wing was shot in his classroom."),   # name from the title, not the excerpt
        claim("C3", "An anti-Foreign boycott followed the shooting."),    # label from the event question
        claim("C4", "Chan Ming was shot in the colony's capital."),
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


def test_names_in_translated_records_are_checked_against_the_packet_translation():
    """Run 38185409550 added "Britain" to a claim from a Chinese passage that names no agent;
    names were not checked against non-English records at all."""
    value = packet()
    value["sources"][0].update(language="zh", passage="强迫该国政府于一八四二年签订条约，此后由双方政府分别批准并生效。",
                               passage_en="forced the government to sign the Treaty in 1842; both governments then ratified it.",
                               passage_en_by="Packet curator, literal translation")
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "强迫该国政府于一八四二年签订条约"
    result["candidate_claims"] = [claim("C1", "The Treaty was signed in 1842."),
                                  claim("C2", "The Treaty was signed in 1843."),
                                  claim("C3", "Britain forced the government to sign the Treaty in 1842.")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1"]
    assert rejected[0]["rejection_reasons"] == ["year not in the linked records: 1843"]
    assert rejected[1]["rejection_reasons"] == ["name not in the linked records: Britain"]
    assert '"passage_en"' in source_first.build_source_first_prompt(value)


def test_non_english_source_needs_a_packet_translation():
    value = packet()
    value["sources"][0].update(language="zh", passage="该条约于一八四二年签订，此后由双方政府分别批准并生效。")
    try:
        source_first.validate_source_packet(value)
        assert False, "a non-English source without passage_en must fail"
    except ValueError as exc:
        assert "passage_en and passage_en_by are required" in str(exc)


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


# Packet revision 4 (data PR #66) added access_log: records tried but not inspected (E13).
def access_entry(**extra):
    return {"record_family": "Colonial letters, volume 9", "url": "https://archive.example/vol9",
            "attempted": "2026-10-11", "result": "access_failure", "error": "fetch error", **extra}


def test_access_log_is_shown_to_the_model_as_not_evidence():
    value = packet()
    value["access_log"] = [access_entry()]
    prompt = source_first.build_source_first_prompt(value)
    assert "RECORDS TRIED BUT NOT INSPECTED (not evidence" in prompt
    assert "Colonial letters, volume 9" in prompt
    assert "RECORDS TRIED BUT NOT INSPECTED" not in source_first.build_source_first_prompt(packet())


def test_access_log_entries_must_be_complete_and_use_known_results():
    for bad in ([{"url": "https://archive.example/vol9"}], [access_entry(result="maybe")], "not a list"):
        value = packet()
        value["access_log"] = bad
        try:
            source_first.validate_source_packet(value)
        except ValueError:
            continue
        raise AssertionError(f"accepted access_log {bad!r}")


def test_comparison_role_is_used_and_recorded():
    pool = FakePool([json.dumps(valid_result())])
    out = source_first.run_source_first(packet(), pool, role="source_first_compare")
    assert pool.roles == ["source_first_compare"]
    assert out["manifest"]["model_role"] == "source_first_compare"
    try:
        source_first.run_source_first(packet(), FakePool([]), role="draft")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown role was accepted")


def test_comparison_model_is_another_family_and_only_for_the_experiment():
    cfg = json.loads((ROOT / "scripts" / "models.json").read_text(encoding="utf-8"))
    entry = next(m for m in cfg["models"] if m["display"] == "OpenRouter Compare")
    assert entry["provider"] == "openrouter"
    assert not any("nemotron" in pick for pick in entry["pick"]) and "nemotron" in entry["avoid"]
    names = [m["display"] for m in cfg["models"]]
    # Resolved after Large and Medium, so it cannot take the model they picked.
    assert names.index("OpenRouter Compare") > names.index("OpenRouter Medium") > names.index("OpenRouter Large")
    users = [role for role, models in cfg["routing"].items()
             if not role.startswith("_") and "OpenRouter Compare" in models]
    assert users == ["source_first_compare"]
    for role in source_first.MODEL_ROLES:
        assert role in cfg["routing"]


def test_workflow_offers_both_roles_and_saves_snapshots():
    import yaml
    text = (ROOT / ".github" / "workflows" / "v2-1-source-first.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    on = flow.get("on", flow.get(True))
    role = on["workflow_dispatch"]["inputs"]["model_role"]
    assert role["default"] == "evidence" and tuple(role["options"]) == source_first.MODEL_ROLES
    assert '--role "$MODEL_ROLE"' in text
    assert 'scripts/source_snapshot.py "${packets[@]}"' in text and "snapshots.json" in text


# Prompt revision 5: the blind review of run 38181951012 found gaps calling whole sources silent
# ("No inspected record describes the rioting" of an article titled "Rioting & Looting").
def test_gaps_and_limits_calling_a_source_silent_are_set_aside():
    result = valid_result()
    result["gaps"] = ["No inspected record describes the rioting.",
                      "No supplied excerpt describes the rioting.",
                      "Harbour records for 1841 were not accessible (see access log)."]
    result["perspectives"][0]["known_limits"] = (
        "The Yearbook does not specify which side refused. The supplied excerpt does not name the officer.")
    source_first.screen_silence(result)
    assert result["gaps"] == ["No supplied excerpt describes the rioting.",
                              "Harbour records for 1841 were not accessible (see access log)."]
    assert result["perspectives"][0]["known_limits"] == "The supplied excerpt does not name the officer."
    assert [g["text"] for g in result["rejected_gaps"]] == [
        "No inspected record describes the rioting.",
        "P1 known_limits: The Yearbook does not specify which side refused."]


def test_run_records_rejected_gaps():
    result = valid_result()
    result["gaps"] = ["The record is silent on the date."]
    out = source_first.run_source_first(packet(), FakePool([json.dumps(result)]))
    assert out["result"]["gaps"] == [] and out["manifest"]["rejected_gap_count"] == 1


# Prompt revision 6: the blind review of run 38183413733 failed E6 on claims such as
# "The murder took place in the evening of 10 January" that name no subject.
def test_claim_without_a_named_subject_is_set_aside():
    result = valid_result()
    result["candidate_claims"] = [
        {"claim_id": "C1", "text": "The occupation took place on 26 January.", "claim_type": "date",
         "source_statement_ids": ["S1"], "status": "unverified"},
        {"claim_id": "C2", "text": "The island was formally occupied after the British flag was hoisted.",
         "claim_type": "action", "source_statement_ids": ["S1"], "status": "unverified"}]
    kept, rejected = source_first.screen_claims(packet(), result)
    assert [c["claim_id"] for c in kept] == ["C2"]
    assert any("no named subject" in r for r in rejected[0]["rejection_reasons"])


def test_comparison_model_prefers_gemma_4_31b():
    # Run 38184409660: the only free non-Nemotron models were gated, previews or small;
    # Gemma 4 31B is free on OpenRouter and of another family.
    cfg = json.loads((ROOT / "scripts" / "models.json").read_text(encoding="utf-8"))
    entry = next(m for m in cfg["models"] if m["display"] == "OpenRouter Compare")
    assert entry["pick"][0] == "gemma-4-31b" and entry["pick"][-1] == "*"


# Revision 7: run 38185409550 gave a reported person a perspective in his own voice and stated a
# speaker's evaluation as an outcome without naming him.

def reported_packet():
    value = packet()
    value["sources"][0].update(
        institution="Consulate General, Canton (letter filed in Colonial Office series)",
        source_type="contemporary_consular_letter", source_date="1908-11-14",
        passage="The Viceroy denies the existence of the society in Canton, as we were told on the 12th.",
        record_context={"author": "Consulate General at Canton, letter"})
    return value


def reported_result(kind="reported_speech"):
    result = valid_result()
    result["record_statements"][0].update(source_excerpt="The Viceroy denies the existence of the society",
                                          statement_kind=kind)
    return result


def test_perspective_actor_must_be_the_records_author_or_speaker():
    result = reported_result()
    result["perspectives"] = [
        {"perspective_id": "P1", "actor_or_institution": "the Viceroy (of Canton)",
         "documented_position": "Denies the existence of the society.", "source_statement_ids": ["S1"], "known_limits": "Reported."},
        {"perspective_id": "P2", "actor_or_institution": "Consulate General, Canton",
         "documented_position": "Reports that the Viceroy denies the existence of the society.",
         "source_statement_ids": ["S1"], "known_limits": "Reported."}]
    kept, rejected = source_first.screen_perspectives(reported_packet(), result)
    assert [p["perspective_id"] for p in kept] == ["P2"]
    assert rejected[0]["rejection_reasons"] == [
        "actor is not the author, speaker or publisher of a linked record: Viceroy"]


def test_perspective_actor_may_be_an_acronym_of_the_institution():
    value = packet()
    value["sources"][0]["institution"] = "Ministry of Foreign Affairs of the People's Republic of China"
    result = valid_result()
    result["perspectives"][0]["actor_or_institution"] = "PRC Ministry of Foreign Affairs"
    kept, rejected = source_first.screen_perspectives(value, result)
    assert len(kept) == 1 and not rejected


def test_claim_from_reported_words_must_name_their_source():
    result = reported_result()
    result["candidate_claims"] = [
        claim("C1", "The Viceroy denied the existence of the society in Canton."),
        claim("C2", "The Consulate General reported that the Viceroy denied the existence of the society.")]
    kept, rejected = source_first.screen_claims(reported_packet(), result)
    assert [c["claim_id"] for c in kept] == ["C2"]
    # "Canton" is in the passage too, so it does not name the letter's author.
    assert rejected[0]["rejection_reasons"] == ["does not name whose words it reports (hk-yearbook-2021)"]


def test_claim_from_a_speakers_words_must_name_the_speaker_whatever_the_kind():
    value = packet()
    value["sources"][0].update(passage="The start of the scheme thus marks an important milestone for the workforce.",
                               record_context={"speaker": "Tony Lam, Permanent Secretary"})
    result = valid_result()
    result["record_statements"][0]["source_excerpt"] = "The start of the scheme thus marks an important milestone"
    result["candidate_claims"] = [claim("C1", "The start of the Scheme marked an important milestone."),
                                  claim("C2", "Tony Lam called the start of the Scheme an important milestone.")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C2"]
    assert rejected[0]["rejection_reasons"] == ["does not name whose words it reports (hk-yearbook-2021)"]


def test_claim_from_a_plain_summary_needs_no_attribution():
    kept, rejected = source_first.screen_claims(packet(), valid_result())
    assert len(kept) == 1 and not rejected


def test_speakers_date_needs_no_attribution_but_a_publishers_cause_does():
    """Run 38186782932 kept a newspaper's 'remote cause of the rioting' as fact (kind assertion)
    and set aside a speech's plain start date for not naming the speaker."""
    value = packet()
    value["sources"][0].update(passage="The Scheme started on 1 December 2000; the boycott was the cause of the rioting.",
                               record_context={"publisher": "Evening Star (newspaper)"})
    result = valid_result()
    result["record_statements"][0].update(source_excerpt="The Scheme started on 1 December 2000", statement_kind="assertion")
    result["candidate_claims"] = [
        dict(claim("C1", "The Scheme started on 1 December 2000."), claim_type="date"),
        dict(claim("C2", "The boycott was the cause of the Rioting."), claim_type="cause"),
        dict(claim("C3", "The Evening Star gave the boycott as the cause of the Rioting."), claim_type="cause")]
    kept, rejected = source_first.screen_claims(value, result)
    assert [c["claim_id"] for c in kept] == ["C1", "C3"]
    assert rejected[0]["rejection_reasons"] == ["does not name whose words it reports (hk-yearbook-2021)"]
