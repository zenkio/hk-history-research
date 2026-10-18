import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract_records as er

# V2.2 end to end on synthetic packets: extraction, linking and status.
QUESTION = "What do records establish about the 1850 harbour office opening?"


def source(source_id, passage, institution="Example Harbour Department", **extra):
    return dict({"source_id": source_id, "passage": passage, "institution": institution,
                 "source_type": "contemporary_official_report", "source_date": "1850",
                 "inspection_status": "inspected", "processing_status": er.APPROVED}, **extra)


def fake_model(link_answers):
    """Answers every extraction question for 'X opened ...' sentences; link answers come in order."""
    queue = list(link_answers)

    def ask(prompt):
        if prompt.startswith("Copy facts"):
            sentence = prompt.rsplit("Sentence: ", 1)[1].strip()
            when = "3 March 1850" if "3 March 1850" in sentence else ("4 March 1850" if "4 March" in sentence else "")
            return f"FACT\nsubject: harbour office\naction: opened\nagent:\nwhen: {when}\nwhere:\nnot_happened: no"
        if prompt.startswith("List the names"):
            return "people:\ngroups: harbour office\nplaces:\nthings:"
        if prompt.startswith("Two statements"):
            return queue.pop(0)
        if prompt.startswith("What does the sentence do"):
            return "4"
        return "1"
    return ask


def test_topic_era_label_and_family_come_from_code():
    assert er.topic_era(QUESTION) == "06-early-colony" and er.topic_era("no year") is None
    assert er.claim_label({"source_type": "contemporary_newspaper_report"}) == "claim"
    assert er.claim_label({"source_type": "contemporary_legislative_record"}) == "official claim"
    assert er.source_family({"institution": "Example Government, news.example"}) == \
        er.source_family({"institution": "Example Government"})


def test_a_same_fact_from_another_family_supports_and_removes_the_single_source_gap():
    packet = {"event_question": QUESTION, "sources": [
        source("a", "On 3 March 1850 the harbour office opened."),
        source("b", "The harbour office opened on 3 March 1850.", institution="Example Gazette",
               source_type="contemporary_newspaper_report"),
        source("c", "Not inspected.", inspection_status="not_inspected")]}
    topic = er.run(fake_model(["1", "1"]), [("p.json", packet)])[0]
    assert topic["skipped_sources"] == ["c"]
    assert topic["links"] == [{"a": "a#s1f1", "b": "b#s1f1", "relation": "same_fact", "kind": "supports",
                               "same_source_family": False}]
    a, b = topic["facts"]
    assert a["status"] == b["status"] == "supported by another source"
    assert not any(g.startswith("Only one source") for g in a["gaps"])
    assert a["statement"].startswith('According to Example Harbour Department: "On 3 March 1850')


def test_a_link_is_kept_only_when_both_orders_agree_and_the_statements_are_swapped():
    packet = {"event_question": QUESTION, "sources": [
        source("a", "On 3 March 1850 the harbour office opened."),
        source("b", "The harbour office opened on 4 March 1850.", institution="Example Gazette")]}
    prompts = []
    model = fake_model(["2", "1"])

    def ask(prompt):
        prompts.append(prompt)
        return model(prompt)
    topic = er.run(ask, [("p.json", packet)])[0]
    assert topic["links"] == [] and topic["unsure_links"][0]["answers"] == ["different_detail", "same_fact"]
    first, second = [p for p in prompts if p.startswith("Two statements")]
    assert first.index("3 March") < first.index("4 March") and second.index("4 March") < second.index("3 March")
    assert topic["facts"][0]["gaps"][-1] == "Only one source so far (official claim, not yet corroborated)."


def test_a_different_detail_challenges_but_a_same_family_link_does_not_count():
    packet = {"event_question": QUESTION, "sources": [
        source("a", "On 3 March 1850 the harbour office opened."),
        source("b", "The harbour office opened on 4 March 1850.", institution="Example Gazette"),
        source("c", "The harbour office opened in 1850.", institution="Example Harbour Department, annual report")]}
    # Pairs in order: a-b, a-c, b-c; each asked twice.
    topic = er.run(fake_model(["2", "2", "1", "1", "4", "4"]), [("p.json", packet)])[0]
    kinds = {(l["a"], l["b"]): (l["kind"], l["same_source_family"]) for l in topic["links"]}
    assert kinds == {("a#s1f1", "b#s1f1"): ("challenges", False), ("a#s1f1", "c#s1f1"): ("supports", True)}
    status = {f["source_id"]: f["status"] for f in topic["facts"]}
    assert status == {"a": "challenged by another source", "b": "challenged by another source",
                      "c": "not yet corroborated"}


def test_facts_of_different_eras_are_never_paired():
    early = {"id": "a", "source_id": "a", "era": ["06-early-colony"]}
    late = {"id": "b", "source_id": "b", "era": ["13-transition"]}
    same_source = {"id": "c", "source_id": "a", "era": ["06-early-colony"]}
    assert er.candidate_pairs([early, late, same_source]) == []


def test_main_keeps_finished_topics_when_a_later_one_fails(tmp_path, monkeypatch):
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "MANIFEST.json").write_text(json.dumps({"sources": [source("m", "Manifest.")]}))
    (packets / "a.json").write_text(json.dumps({"event_question": QUESTION, "sources": [
        source("a", "On 3 March 1850 the harbour office opened.")]}))
    (packets / "b.json").write_text(json.dumps({"event_question": QUESTION, "sources": [
        source("b", "Boom.")]}))
    model = fake_model([])

    class FakePool:
        routing = {er.ROLE: ["Model A"]}
        models = {"Model A": {"api_id": "a-1", "provider": "openrouter", "rpd": 50}}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            if "Boom." in prompt:
                raise RuntimeError("provider down")
            return parse(model(prompt)), only[0], []

    import gemini_pool
    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "records.json"
    assert er.main(["--packets", str(packets), "--model", "Model A", "--output", str(out)]) == 1
    result = json.loads(out.read_text())
    assert [t["packet"] for t in result["topics"]] == ["a.json"]
    assert result["stopped"] == "stopped after 1 topics: RuntimeError" and result["api_id"] == "a-1"


def test_workflow_offers_the_extract_mode_with_private_output():
    import yaml
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    on = yaml.safe_load(text).get("on") or yaml.safe_load(text)[True]
    assert on["workflow_dispatch"]["inputs"]["mode"]["options"] == ["score", "extract", "links", "verify"]
    assert 'scripts/extract_records.py --model' in text
    assert '--output "$PRIVATE_OUTPUT/records.json" >"$PRIVATE_OUTPUT/diagnostics.log" 2>&1' in text


def test_a_topic_whose_question_names_no_year_takes_the_era_of_its_earliest_dated_fact():
    # Run 38639138642: undated Yeung facts got no era, so two records disagreeing on the place
    # were never compared.
    packet = {"event_question": "What do records establish about the harbour office opening?", "sources": [
        source("a", "On 3 March 1850 the harbour office opened."),
        source("b", "The harbour office opened.", institution="Example Gazette",
               source_type="official_retrospective", source_date="2021")]}  # its date is not the event's
    topic = er.run(fake_model(["3", "3"]), [("p.json", packet)])[0]
    assert [f["year"] for f in topic["facts"]] == [1850, None]
    assert [f["era"] for f in topic["facts"]] == [["06-early-colony"], ["06-early-colony"]]
    assert len(topic["unsure_links"]) + len(topic["links"]) == 0  # the pair was asked: "different event"
    assert len(er.candidate_pairs(topic["facts"])) == 1


def test_the_link_question_says_a_more_precise_date_is_the_same_fact():
    # Run 38639138642 marked "in 1901" against "on 10 January 1901" as a conflict.
    same, differ = er.LINK_CHOICES[0][1], er.LINK_CHOICES[1][1]
    assert "more precise" in same and "contradict" in differ


def test_a_semicolon_ends_the_institution_name_too():
    # Run 38972366561 put two reports of the same newspaper in different source families.
    assert er.source_family({"institution": "Example Mail (newspaper); scan digitised by Example Archive"}) == \
        er.source_family({"institution": "Example Mail (newspaper), from its correspondent; scan digitised"})


def test_the_time_budget_stops_extraction_and_the_finished_topics_are_saved(tmp_path, monkeypatch):
    # Run 39002894226: extraction with a slow model hit the job's timeout and saved nothing.
    packets = tmp_path / "packets"
    packets.mkdir()
    for name in "ab":
        (packets / f"{name}.json").write_text(json.dumps({"event_question": QUESTION, "sources": [
            source(name, "On 3 March 1850 the harbour office opened.")]}))
    model, clock, out = fake_model([]), [0.0], tmp_path / "records.json"
    monkeypatch.setattr(er.time, "time", lambda: clock[0])

    class FakePool:
        routing = {er.ROLE: ["Model A"]}
        models = {"Model A": {"api_id": "a-1"}}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            if out.exists():  # topic a is saved, so this is topic b: each question takes a minute
                clock[0] += 60
            return parse(model(prompt)), only[0], []

    import gemini_pool
    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    assert er.main(["--packets", str(packets), "--model", "Model A", "--output", str(out),
                    "--minutes", "2"]) == 1
    result = json.loads(out.read_text())
    assert [t["packet"] for t in result["topics"]] == ["a.json"]
    assert result["stopped"] == "stopped after 1 topics: OutOfTime"
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    assert "scripts/extract_records.py --model \"$model\" --minutes 100" in text


def test_a_support_from_a_fact_with_no_date_or_place_does_not_confirm_them():
    # Run 39088685255 (PR #125): a record with no date "supported" another record's exact date.
    def fact(fid, source, family, when="", where=""):
        return {"id": fid, "source_id": source, "family": family, "label": "claim", "year": 1850,
                "subject": "he", "action": "opened", "when": when, "where": where, "kind": "event"}
    dated = fact("a#1", "a", "board", when="3 March 1850", where="Pier Head")
    letter = fact("b#1", "b", "letter")
    placed = fact("c#1", "c", "paper", where="Pier Head")
    er.settle([dated, letter, placed], [
        {"a": "a#1", "b": "b#1", "kind": "supports", "same_source_family": False},
        {"a": "a#1", "b": "c#1", "kind": "supports", "same_source_family": False}])
    assert dated["status"] == "supported by another source"
    assert "No other source gives its date." in dated["gaps"]
    assert "No other source gives its place." not in dated["gaps"]
    assert not any(g.startswith("No other source") for g in letter["gaps"])


def test_details_that_can_both_be_true_make_no_link():
    # Run 39088685255 (PR #126): a street address "challenged" a record placing the event in a room.
    labels = [label for _, label in er.LINK_CHOICES]
    compatible = labels.index(next(l for l in labels if "can both be true" in l)) + 1
    packet = {"event_question": QUESTION, "sources": [
        source("a", "On 3 March 1850 the harbour office opened."),
        source("b", "The harbour office opened on 3 March 1850.", institution="Example Gazette")]}
    topic = er.run(fake_model([str(compatible), str(compatible)]), [("t.json", packet)])[0]
    assert topic["links"] == [] and topic["unsure_links"] == []
    assert er.LINK_KINDS.get("compatible_detail") is None
