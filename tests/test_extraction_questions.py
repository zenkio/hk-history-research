import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extraction_questions as eq
import score_extraction_models as sem

# V2.2 steps B-E and model scoring. All sentences and records here are synthetic.
SENTENCE = "On 3 March 1850, the harbour office was opened at Pier Head by the Harbour Master."
RECORD = {"source_id": "s1", "institution": "Example Harbour Department",
          "source_type": "contemporary_official_report", "source_date": "1850-03-04"}
GOOD_FACT = """FACT
subject: the harbour office
action: was opened
agent: the Harbour Master
when: 3 March 1850
where: Pier Head
not_happened: no"""
GOOD_TAGS = "people: Harbour Master\ngroups:\nplaces: Pier Head\nthings:"


def scripted(*replies):
    """A fake model: answers in order and keeps the prompts it was sent."""
    prompts, queue = [], list(replies)

    def ask(prompt):
        prompts.append(prompt)
        return queue.pop(0)
    ask.prompts = prompts
    return ask


def test_parse_facts_reads_labelled_lines_and_keeps_quotes_inside_a_span():
    reply = ('Here you go:\n**FACT**\nsubject: "the Viceroy"\naction: denies the existence of a "Society"\n'
             "agent:\nwhen:\nwhere: Canton\nnot_happened: no\nnote: ignored")
    assert eq.parse_facts(reply) == [{"subject": "the Viceroy", "action": 'denies the existence of a "Society"',
                                      "agent": "", "when": "", "where": "Canton", "negated": False}]
    assert eq.parse_facts("NONE") == []


def test_a_fact_with_an_invented_span_is_asked_again_with_the_exact_problem():
    ask = scripted(GOOD_FACT.replace("3 March 1850", "4 March 1850"), GOOD_FACT)
    log = []
    assert eq.ask_facts(ask, SENTENCE, log)[0]["when"] == "3 March 1850"
    assert 'when "4 March 1850" is not copied from the sentence' in ask.prompts[1]
    assert log == [{"step": "facts", "retry": ['when "4 March 1850" is not copied from the sentence']}]


def test_a_fact_still_wrong_after_the_retry_is_dropped_and_logged_and_the_good_one_kept():
    bad = GOOD_FACT.replace("was opened", "was built")
    ask = scripted(bad, bad + "\n" + GOOD_FACT)
    log = []
    assert [f["action"] for f in eq.ask_facts(ask, SENTENCE, log)] == ["was opened"]
    assert log[-1]["dropped"]["action"] == "was built"


def test_tags_not_in_the_sentence_are_dropped_after_one_retry():
    ask = scripted(GOOD_TAGS + "\npeople: Captain Lee", GOOD_TAGS.replace("places: Pier Head", "places: Kowloon"))
    log = []
    tags = eq.ask_tags(ask, SENTENCE, log)
    assert tags == {"people": ["Harbour Master"], "groups": [], "places": [], "things": []}
    assert log[-1] == {"step": "tags", "dropped": ["Kowloon"]}


def test_choices_must_be_a_number_on_the_list():
    assert eq.parse_choice("Answer: 2.", 6) == 2
    assert eq.parse_choice("7", 6) is None and eq.parse_choice("event", 6) is None
    log = []
    assert eq.ask_kind(scripted("event", "1"), SENTENCE, {"subject": "the harbour office"}, log) == "event"
    assert eq.ask_stance(scripted("9", "maybe"), SENTENCE, "", log) == ""
    assert log[-1] == {"step": "stance", "dropped": "no number on the list"}


def test_whose_view_lists_the_record_voices_and_accepts_a_name_copied_from_the_sentence():
    record = dict(RECORD, record_context={"speaker": "Mr LEE (attendance list: LEE Tak), member of the Council",
                                          "reported_position_of": "Members at the meeting"})
    assert [name for name, _ in eq.voices(record)] == ["Example Harbour Department", "Mr LEE", "Members at the meeting"]
    log = []
    ask = scripted("2")
    assert eq.ask_view(ask, SENTENCE, record, log) == "Mr LEE"
    # Run 38525325652: without roles, a speech was given to the institution that published it.
    assert "2. Mr LEE (the speaker)" in ask.prompts[0] and "3. Members at the meeting (whose position" in ask.prompts[0]
    assert eq.ask_view(scripted('4: "the Harbour Master"'), SENTENCE, record, log) == "the Harbour Master"
    assert eq.ask_view(scripted("4: the Governor", "4: Governor"), SENTENCE, record, log) == ""
    assert log[-1] == {"step": "view_of", "dropped": "no usable answer"}


def perfect_model(prompt):
    """A fake model that answers every V2.2 question right for SENTENCE."""
    if prompt.startswith("Copy facts"):
        return GOOD_FACT
    if prompt.startswith("List the names"):
        return GOOD_TAGS
    if prompt.startswith("What does the sentence do"):
        return "4"
    return "1"  # kind: event; whose view: the institution


KEY = {"sentences": [{
    "source_id": "s1", "sentence": SENTENCE,
    "facts": [{"subject": "the harbour office", "action": "was opened", "agent": "the Harbour Master",
               "when": "3 March 1850", "where": "Pier Head", "negated": False, "kind": ["event"],
               "subject_from_notes": ""}],
    "angle": {"view_of": "Example Harbour Department", "stance": ["neutral"]},
    "tags": {"people": ["Harbour Master"], "groups": [], "places": ["Pier Head"], "things": []},
    "year": 1850, "era": ["06-early-colony"]}]}


def test_a_model_that_answers_like_the_key_passes_every_step_and_code_adds_era_statement_and_gaps():
    result = sem.score_model(perfect_model, KEY, {"s1": RECORD})
    assert result["steps_passed"] == {"B_facts": True, "C_kind": True, "D_angle": True, "E_tags": True}
    assert result["scores"]["era"] == [1, 1]
    fact = result["answers"]["s1"]["facts"][0]
    assert fact["era"] == ["06-early-colony"] and fact["statement"].startswith("According to Example Harbour")
    assert fact["gaps"] == ["Only one source so far (official claim, not yet corroborated)."]


def test_a_wrong_choice_fails_only_its_own_step():
    def wrong_stance(prompt):
        return "1" if prompt.startswith("What does the sentence do") else perfect_model(prompt)
    passed = sem.score_model(wrong_stance, KEY, {"s1": RECORD})["steps_passed"]
    assert passed == {"B_facts": True, "C_kind": True, "D_angle": False, "E_tags": True}


def test_a_model_that_runs_out_of_budget_is_scored_on_the_sentences_it_finished():
    class OutOfBudget(Exception):
        pass
    key = {"sentences": KEY["sentences"] * 2}

    def ask(prompt, calls=[]):
        calls.append(1)
        if len(calls) > 5:  # one sentence takes 5 questions
            raise OutOfBudget()
        return perfect_model(prompt)
    result = sem.score_model(ask, key, {"s1": RECORD}, stop_on=(OutOfBudget,))
    assert result["sentences_done"] == 1 and result["stopped"].startswith("stopped after 1 sentences")
    assert result["scores"]["facts_found"] == [1, 1]


def test_main_forces_each_model_in_turn_and_never_reads_the_manifest_as_a_packet(tmp_path, monkeypatch):
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "MANIFEST.json").write_text(json.dumps({"sources": [{"source_id": "manifest-only"}]}))
    (packets / "topic.json").write_text(json.dumps({"sources": [RECORD]}))
    (tmp_path / "key.json").write_text(json.dumps(KEY))
    assert list(sem.load_records(packets)) == ["s1"]
    used = []

    class FakePool:
        routing = {sem.ROLE: ["Model A", "Model B"]}
        models = {"Model A": {"api_id": "a-1", "provider": "openrouter", "rpd": 50},
                  "Model B": {"api_id": "b-1"}}

        def remaining(self, name, role):
            return 0 if name == "Model B" else 10

        def generate_text(self, role, prompt, parse, only=None):
            used.append((role, tuple(only)))
            return parse(perfect_model(prompt)), only[0], []

    import gemini_pool
    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "scores.json"
    assert sem.main(["--key", str(tmp_path / "key.json"), "--packets", str(packets),
                     "--models", "Model A, Model B, Model C", "--output", str(out)]) == 0
    results = json.loads(out.read_text())["results"]
    assert set(used) == {(sem.ROLE, ("Model A",))}
    assert results[0]["steps_passed"]["B_facts"] and results[0]["api_id"] == "a-1" and results[0]["calls"] == 5
    assert results[1]["error"].startswith("unavailable")
    assert results[2]["error"] == f"not in routing role {sem.ROLE}"


def test_the_trial_role_lists_only_models_that_exist():
    cfg = json.loads((Path(__file__).resolve().parents[1] / "scripts" / "models.json").read_text())
    names = {m["display"] for m in cfg["models"]}
    trial = cfg["routing"][sem.ROLE]
    assert set(trial) <= names and {"Gemma 4 31B", "Gemini 3.1 Flash Lite", "OpenRouter Large"} <= set(trial)


@pytest.mark.parametrize("prompt", [eq.FACTS_PROMPT, eq.TAGS_PROMPT])
def test_copy_prompts_show_one_sentence_and_no_research_question(prompt):
    other = "The ferry pier closed in 1851."
    text = prompt.format(sentence=other)
    assert text.count(other) == 1 and "question" not in text.lower()


def test_scoring_workflow_is_dispatch_only_private_and_never_overlaps_other_experiments():
    import yaml
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    text = (root / "v2-2-model-scoring.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    on = flow.get("on", flow.get(True))
    assert list(on) == ["workflow_dispatch"] and flow["permissions"] == {"contents": "read"}
    v21 = yaml.safe_load((root / "v2-1-source-first.yml").read_text(encoding="utf-8"))
    assert flow["concurrency"] == v21["concurrency"]
    defaults = [m.strip() for m in on["workflow_dispatch"]["inputs"]["models"]["default"].split(",")]
    cfg = json.loads((Path(__file__).resolve().parents[1] / "scripts" / "models.json").read_text())
    assert set(defaults) <= set(cfg["routing"][sem.ROLE])
    assert '>"$PRIVATE_OUTPUT/diagnostics.log" 2>&1' in text  # replies never reach the public run log
    assert "experiment/v2-2-model-scores-" in text


def test_a_label_left_empty_and_run_into_the_next_one_is_not_read_as_a_tag():
    # Run 38525325652: the reply line "people: groups:" became the people tag "groups:".
    assert eq.parse_tags("people: groups:\nplaces: Pier Head") == {
        "people": [], "groups": [], "places": ["Pier Head"], "things": []}


def test_the_facts_prompt_shows_a_subjectless_fragment_and_keeps_dates_to_their_own_clause():
    # Run 38525325652: fragments such as "shot dead in his residence" got no fact at all, and a date
    # from one clause was copied into the other clause's fact.
    text = eq.FACTS_PROMPT
    assert "Sentence: closed by the governor in 1903" in text and "subject:\naction: closed" in text
    assert "only the date and place written in its own part of the sentence" in text


def test_a_busy_model_is_rested_and_asked_again_a_limited_number_of_times(tmp_path, monkeypatch):
    import gemini_pool
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "topic.json").write_text(json.dumps({"sources": [RECORD]}))
    (tmp_path / "key.json").write_text(json.dumps(KEY))
    failures = {"Model A": 2, "Model B": 99}
    slept = []
    monkeypatch.setattr(sem.time, "sleep", slept.append)

    class FakePool:
        routing = {sem.ROLE: ["Model A", "Model B"]}
        models = {"Model A": {"api_id": "a"}, "Model B": {"api_id": "b"}}
        cooldown = {}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            if failures[only[0]]:
                failures[only[0]] -= 1
                raise gemini_pool.QuotaExhausted("busy")
            return parse(perfect_model(prompt)), only[0], []

    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "scores.json"
    assert sem.main(["--key", str(tmp_path / "key.json"), "--packets", str(packets),
                     "--models", "Model A,Model B", "--output", str(out)]) == 0
    a, b = json.loads(out.read_text())["results"]
    assert a["sentences_done"] == 1 and a["steps_passed"]["B_facts"]
    assert b["sentences_done"] == 0 and b["stopped"].startswith("stopped after 0 sentences")
    assert slept == [sem.REST_SECONDS] * (2 + sem.TRIAL_RESTS)
