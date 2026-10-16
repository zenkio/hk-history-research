import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import find_independent_records as fr

# Synthetic topic: one uncorroborated event, one opinion, one fact already supported.


def fact(fid, status="not yet corroborated", kind="event", tags=None, year=1850, family="example harbour department",
         **extra):
    return dict({"id": fid, "status": status, "kind": kind, "year": year, "family": family,
                 "tags": tags if tags is not None else {"people": [], "groups": ["Harbour Office"],
                                                         "places": ["Hong Kong"], "things": ["Pier Ordinance"]},
                 "statement": 'According to Example Harbour Department: "The Harbour Office opened in 1850."'},
                **extra)


TOPIC = {"packet": "p.json", "facts": [
    fact("a#s1f1"),
    fact("a#s2f1", kind="opinion"),
    fact("b#s1f1", status="supported by another source", family="example gazette")]}

ARCHIVE = {"source": "UK National Archives Discovery", "kind": "archive record", "year": "1850",
           "url": "https://example.org/r/1", "cite": "The National Archives (UK), CO 1/1, 1850.",
           "note": "Letters about the colony. The Harbour Office opened in March 1850 under the Pier Ordinance. "
                   "Accounts of the Treasury."}
SAME_FAMILY = dict(ARCHIVE, source="Other", cite="Example Harbour Department, annual report (1850).",
                   url="https://example.org/own")


def gather_returning(*candidates):
    queries = []

    def gather(query):
        queries.append(query)
        return list(candidates), []
    return gather, queries


def test_only_uncorroborated_or_challenged_facts_of_checkable_kinds_are_searched():
    assert fr.searchable(fact("x")) and fr.searchable(fact("x", status="challenged by another source"))
    assert not fr.searchable(fact("x", kind="opinion")) and not fr.searchable(fact("x", kind="reported_words"))
    assert not fr.searchable(fact("x", status="supported by another source"))


def test_the_query_uses_the_most_specific_tags_and_drops_words_every_record_shares():
    assert fr.query_for(fact("x")) == '"Harbour Office" "Pier Ordinance"'
    abbreviated = fact("x", tags={"people": [], "groups": [], "places": [],
                                  "things": ["Mandatory Provident Fund Schemes Ordinance (MPFO)"]})
    assert fr.query_for(abbreviated) == '"Mandatory Provident Fund Schemes Ordinance"'


def test_a_sentence_that_names_no_one_searches_the_notes_subject_then_the_topic_terms():
    empty = {"people": [], "groups": [], "places": [], "things": []}
    assert fr.query_for(fact("x", tags=empty, subject_from_notes="Yeung Ku-wan")) == '"Yeung Ku-wan"'
    assert fr.query_for(fact("x", tags=empty), fallback=["Hong Kong", "Pier Ordinance"]) == '"Pier Ordinance"'


def test_only_sentences_sharing_the_year_or_two_terms_are_offered_and_excerpts_stay_short():
    sentences = fr.matching_sentences(ARCHIVE["note"], fact("x"))
    assert sentences == ["The Harbour Office opened in March 1850 under the Pier Ordinance."]
    long = " ".join(["word"] * 40) + " the Pier Ordinance of 1850 " + " ".join(["more"] * 20)
    cut = fr.excerpt(long, fact("x"))
    assert len(cut.split()) == fr.MAX_WORDS and "Pier" in cut


def test_a_record_from_another_institution_is_kept_as_an_unapproved_candidate():
    gather, queries = gather_returning(SAME_FAMILY, ARCHIVE)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return "1"
    records, log = fr.find_for_topic(ask, TOPIC, gather)
    assert queries == ['"Harbour Office" "Pier Ordinance"']  # the opinion and the supported fact are not searched
    assert len(prompts) == 1 and "2. None of these" in prompts[0]  # the same-family record is never asked
    record = records[0]
    assert record["for_fact"] == "a#s1f1" and record["institution"] == "The National Archives (UK)"
    assert record["passage"] == "The Harbour Office opened in March 1850 under the Pier Ordinance."
    assert record["processing_status"] == "awaiting_review" and record["inspection_status"] == "not_inspected"
    assert record["public_reuse_not_approved"] is True and len(record["retrieved_text_sha256"]) == 64
    assert log[0]["kept"] == 1 and log[0]["other_family"] == 1


def test_none_of_these_or_an_unclear_answer_keeps_nothing():
    for answer in ("2", "maybe"):
        gather, _ = gather_returning(ARCHIVE)
        records, log = fr.find_for_topic(lambda prompt: answer, TOPIC, gather)
        assert records == [] and log[0]["asked"] == 1


def test_facts_with_the_same_tags_search_once_and_a_topic_keeps_at_most_five_records():
    topic = {"packet": "p.json", "facts": [fact(f"a#s{i}f1") for i in range(1, 8)]}
    gather, queries = gather_returning(ARCHIVE)
    records, log = fr.find_for_topic(lambda prompt: "1", topic, gather)
    assert queries == ['"Harbour Office" "Pier Ordinance"']
    assert len(records) == fr.RECORDS_PER_TOPIC and log[-1]["skipped"] == "topic limit reached"


def test_main_writes_candidates_apart_from_the_packets(tmp_path, monkeypatch):
    (tmp_path / "records.json").write_text(json.dumps({"topics": [TOPIC]}))
    import evidence
    import gemini_pool
    monkeypatch.setattr(evidence, "gather", gather_returning(ARCHIVE)[0])
    monkeypatch.setattr(evidence, "PRE_1929_FOR_INTERNAL_RESEARCH", False)  # restored after the test
    monkeypatch.setattr(evidence, "IA_READ_BYTES", evidence.IA_READ_BYTES)
    monkeypatch.setattr(evidence, "IA_TEXT_CHARS", evidence.IA_TEXT_CHARS)

    class FakePool:
        routing = {fr.er.ROLE: ["Model A"]}
        models = {"Model A": {"api_id": "a-1", "provider": "openrouter", "rpd": 50}}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            return parse("1"), only[0], []

    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "candidates.json"
    assert fr.main(["--records", str(tmp_path / "records.json"), "--model", "Model A", "--output", str(out)]) == 0
    result = json.loads(out.read_text())
    assert result["calls"] == 1 and result["live_records_modified"] is False
    assert evidence.PRE_1929_FOR_INTERNAL_RESEARCH is True  # owner decision 2026-10-16
    assert evidence.IA_TEXT_CHARS >= 1_000_000  # a whole newspaper issue, not its first page of adverts
    assert result["topics"][0]["candidate_records"][0]["for_fact"] == "a#s1f1"


def test_the_workflow_verifies_only_after_a_successful_extraction():
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    assert 'if [[ "$MODE" == verify && $failed == 0 ]]; then' in text
    assert '--output "$PRIVATE_OUTPUT/candidates.json" >>"$PRIVATE_OUTPUT/diagnostics.log" 2>&1' in text


def test_a_possessive_tag_is_searched_without_its_s():
    # Run 38660927145 searched for "government's".
    tags = {"people": [], "groups": ["the government's"], "places": [], "things": ["MPF System"]}
    assert fr.query_for(fact("x", tags=tags)) == '"the government" "MPF System"'


def test_a_file_dated_to_the_facts_year_needs_only_one_shared_term():
    # Run 38660927145 asked about none of the Tatsu Maru candidates: catalogue descriptions name
    # the subject once and keep the year in the covering dates.
    note = "Despatch on the Pier Ordinance and the harbour works."
    assert fr.matching_sentences(note, fact("x"), record_year="1901") == []
    assert fr.matching_sentences(note, fact("x"), record_year="1849-1851") == [note]
    assert fr.covers("1 Jan 1850 - 31 Dec 1859", 1850) and not fr.covers("", 1850) and not fr.covers("1850", None)


def test_the_log_says_what_each_candidate_was_and_why_it_went_no_further():
    other = dict(ARCHIVE, note="Nothing relevant here.", url="https://example.org/r/2", title="CO 1/2")
    gather, _ = gather_returning(SAME_FAMILY, other, dict(ARCHIVE, title="CO 1/1"))
    records, log = fr.find_for_topic(lambda prompt: "1", TOPIC, gather)
    outcomes = [(c["title"], c["outcome"]) for c in log[0]["candidates"]]
    assert outcomes == [("", "same source family"), ("CO 1/2", "no sentence shares the year or terms"),
                        ("CO 1/1", "kept")]


def test_a_file_known_only_by_its_title_is_read_by_its_title():
    # Run 38667312335: Records Service files have a title and no description, and none was offered.
    grs = {"source": "Hong Kong Government Records Service", "kind": "archive record", "year": "",
           "url": "https://example.org/grs/1", "title": "Harbour Office and Pier Ordinance files"}
    gather, _ = gather_returning(grs)
    records, log = fr.find_for_topic(lambda prompt: "1", TOPIC, gather)
    assert records[0]["passage"] == "Harbour Office and Pier Ordinance files"


def test_an_unreadable_record_of_the_events_own_time_is_listed_as_a_lead():
    # Run 38667312335: 1901 newspapers about Yeung Ku-wan came back with no readable text.
    paper = {"source": "Internet Archive", "kind": "digitised publication", "year": "1850",
             "url": "https://example.org/ia/1", "title": "Example Gazette 1850-03-04", "passage": ""}
    later = dict(paper, year="1934", url="https://example.org/ia/2", title="Example Gazette 1934-01-08")
    gather, _ = gather_returning(paper, later)
    records, log = fr.find_for_topic(lambda prompt: "1", TOPIC, gather)
    assert records == []
    assert log[0]["leads"] == [{"source": "Internet Archive", "title": "Example Gazette 1850-03-04",
                                "year": "1850", "url": "https://example.org/ia/1"}]


def test_the_workflow_can_verify_from_an_earlier_runs_saved_records():
    # Runs 10-12 (2026-10-16) stopped on 504s from the extraction model before any search.
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    assert 'if [[ "$MODE" == verify && -n "$RECORDS_RUN" ]]; then' in text
    assert 'if [[ "$RECORDS_RUN" =~ ^[0-9]+$ ]]; then' in text  # a run id only, never a path or ref
    assert 'git show "origin/experiment/v2-2-model-scores-$RECORDS_RUN:experiments/v2-2/model-runs/$RECORDS_RUN/records.json"' in text


def test_in_a_record_of_the_facts_own_year_the_year_alone_does_not_match():
    # Run 38906795423 kept "Hongkong, March 15, 1908. NOTICE." from a 1908 newspaper.
    text = "Hongkong, March 15, 1850. NOTICE. The Pier Ordinance was read a second time."
    assert fr.matching_sentences(text, fact("x"), record_year="1850") == ["The Pier Ordinance was read a second time."]
    assert "Hongkong, March 15, 1850." in fr.matching_sentences(text, fact("x"), record_year="1923")


def test_a_kept_record_says_why_its_text_could_be_read():
    paper = {"source": "Internet Archive", "kind": "digitised publication", "year": "1923",
             "url": "https://example.org/ia/3", "passage": "The Harbour Office opened in 1850 under the Pier Ordinance.",
             "rights_status": "published_before_1929"}
    gather, _ = gather_returning(paper)
    records, _ = fr.find_for_topic(lambda prompt: "1", TOPIC, gather)
    assert records[0]["rights_status"] == "published_before_1929"
