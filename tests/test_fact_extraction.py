import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fact_extraction as fx

# V2.2 code steps. All sentences here are synthetic.
SENTENCE = "On 3 March 1850, the harbour office was opened at Pier Head by the Harbour Master."
RECORD = {"institution": "Example Harbour Department", "source_type": "contemporary_official_report",
          "source_date": "1850-03-04"}


def test_split_sentences_keeps_abbreviations_whole():
    text = "Mr. Tam opened the pier. It closed in 1851.  No. 5 berth stayed open."
    assert fx.split_sentences(text) == ["Mr. Tam opened the pier.", "It closed in 1851.", "No. 5 berth stayed open."]
    assert fx.split_sentences("a fragment without a stop") == ["a fragment without a stop"]


def test_span_errors_flags_words_not_copied_from_the_sentence():
    good = {"subject": "the harbour office", "action": "was opened", "agent": "the Harbour Master",
            "when": "3 March 1850", "where": "Pier Head", "tags": {"places": ["Pier Head"]}}
    assert fx.span_errors(good, SENTENCE) == []
    bad = dict(good, when="4 March 1850", tags={"people": ["Captain Lee"]})
    assert fx.span_errors(bad, SENTENCE) == ['when "4 March 1850" is not copied from the sentence',
                                             'people tag "Captain Lee" is not copied from the sentence']


def test_year_uses_record_date_only_for_contemporary_records():
    assert fx.year_of("3 March 1850", {}) == 1850
    assert fx.year_of("", RECORD) == 1850
    retrospective = {"source_type": "official_retrospective", "source_date": "2021"}
    assert fx.year_of("", retrospective) is None


def test_eras_include_both_sides_of_a_boundary_year_and_fall_back_to_the_topic():
    assert fx.eras_of(1850) == ["06-early-colony"]
    assert fx.eras_of(1842) == ["05-opium-war", "06-early-colony"]
    assert fx.eras_of(None, "06-early-colony") == ["06-early-colony"]
    assert fx.eras_of(2024) == ["16-national-security-era"]


def test_statement_quotes_the_record_and_labels_the_slots():
    fact = {"subject": "the harbour office", "action": "was opened", "agent": "the Harbour Master",
            "when": "3 March 1850", "where": "Pier Head"}
    assert fx.write_statement(SENTENCE, fact, RECORD) == (
        f'According to Example Harbour Department: "{SENTENCE}" '
        "[by: the Harbour Master; when: 3 March 1850; where: Pier Head]")
    pronoun = {"subject": "He", "subject_from_notes": "Tam Ling", "action": "was shot", "negated": True}
    assert fx.write_statement("He was shot.", pronoun, RECORD).endswith(
        '"He was shot." [about: Tam Ling (from the record notes); stated as not having happened]')


def test_gaps_name_what_the_excerpt_leaves_out():
    gaps = fx.gaps_for({"subject": "", "action": "was opened", "kind": ["event"]}, None)
    assert gaps == ["The excerpt does not name who or what this is about.", "The excerpt states no date.",
                    "The excerpt states no place.", "Only one source so far (official claim, not yet corroborated)."]


def test_score_counts_fields_and_invented_spans():
    key = {"sentences": [{
        "source_id": "s1", "sentence": SENTENCE,
        "facts": [{"subject": "the harbour office", "action": "was opened", "agent": "the Harbour Master",
                   "when": "3 March 1850", "where": "Pier Head", "negated": False, "kind": ["event"]}],
        "angle": {"view_of": "Example Harbour Department", "stance": ["neutral"]},
        "tags": {"people": [], "groups": [], "places": ["Pier Head"], "things": []}}]}
    answers = {"s1": {
        "facts": [{"subject": "harbour office", "action": "was opened", "agent": "", "when": "3 March 1850",
                   "where": "at Pier Head", "negated": False, "kind": "event"}],
        "angle": {"view_of": "Example Harbour Department", "stance": "supports"},
        "tags": {"places": ["Pier Head", "Kowloon"]}}}
    result = fx.score(answers, key)
    assert result["facts_found"] == [1, 1] and result["subject"] == [1, 1] and result["agent"] == [0, 1]
    assert result["where"] == [1, 1]  # a leading "at" is ignored when comparing
    assert result["stance"] == [0, 1] and result["tags"] == [1, 2]
    assert result["invented_spans"] == 1  # the tag "Kowloon" is not in the sentence


def test_score_matches_a_fact_by_overlapping_action_and_reports_near_spans():
    # PR #105: "opened" for the key's "was opened" counted the whole fact as missed, and one answer
    # fact could match two expected facts with the same action.
    key = {"sentences": [{
        "source_id": "s1", "sentence": SENTENCE,
        "facts": [{"subject": "the harbour office", "action": "was opened", "agent": "", "when": "3 March 1850",
                   "where": "Pier Head", "negated": False, "kind": ["event"]},
                  {"subject": "the harbour office", "action": "was opened", "agent": "", "when": "",
                   "where": "", "negated": False, "kind": ["event"]}],
        "angle": {"view_of": "x", "stance": ["neutral"]},
        "tags": {"people": [], "groups": [], "places": [], "things": []}}]}
    answers = {"s1": {"facts": [{"subject": "harbour office", "action": "opened", "agent": "",
                                 "when": "On 3 March 1850", "where": "Pier Head", "kind": "event"}]}}
    result = fx.score(answers, key)
    assert result["facts_found"] == [1, 2] and result["action"] == [0, 1] and result["near_action"] == [1, 1]
    assert result["when"] == [1, 1]  # a leading "On" is ignored


def test_a_missed_fact_counts_once_under_facts_found_not_again_as_a_wrong_kind_or_slot():
    # Run 38525325652: Nemotron's kinds were all right, but each fact it missed also counted as a
    # wrong kind and wrong slots, so step C failed for step B's misses.
    key = {"sentences": [{
        "source_id": "s1", "sentence": SENTENCE,
        "facts": [{"subject": "the harbour office", "action": "was opened", "agent": "", "when": "", "where": "",
                   "negated": False, "kind": ["event"]},
                  {"subject": "", "action": "by the Harbour Master", "agent": "", "when": "", "where": "",
                   "negated": False, "kind": ["event"]}],
        "angle": {"view_of": "x", "stance": ["neutral"]},
        "tags": {"people": ["Harbour Master"], "groups": [], "places": [], "things": []}}]}
    answers = {"s1": {"facts": [{"subject": "the harbour office", "action": "was opened", "kind": "event"}],
                      "tags": {"people": ["the Harbour Master"], "places": ["Pier"]}}}
    result = fx.score(answers, key)
    assert result["facts_found"] == [1, 2] and result["kind"] == [1, 1] and result["subject"] == [1, 1]
    assert result["tags"] == [1, 2] and result["near_tags"] == [1, 2]  # "Pier" is near nothing in the key
