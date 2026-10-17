import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_links as sl

# Synthetic key: three records about one 1850 opening; facts as the answer key holds them.
QUESTION = "What do records establish about the 1850 harbour office opening?"


def record(source_id, institution):
    return {"source_id": source_id, "institution": institution, "source_type": "contemporary_official_report",
            "source_date": "1850", "inspection_status": "inspected",
            "processing_status": "approved_for_internal_research", "passage": "x"}


def row(source_id, sentence, when):
    return {"source_id": source_id, "sentence": sentence, "era": ["06-early-colony"],
            "facts": [{"subject": "the harbour office", "action": "opened", "agent": "", "when": when,
                       "where": "", "negated": False, "kind": ["event"]}]}


KEY = {"sentences": [row("a", "On 3 March 1850 the harbour office opened.", "3 March 1850"),
                     row("b", "The harbour office opened in 1850.", "1850"),
                     row("c", "The harbour office opened on 4 March 1850.", "4 March 1850")]}
PACKETS = [("p.json", {"event_question": QUESTION, "sources": [
    record("a", "Example Harbour Department"), record("b", "Example Gazette"), record("c", "Example Post")]})]
LINK_KEY = {"pairs": [
    {"a": "a#1", "b": "b#1", "expected": "supports"},
    {"a": "a#1", "b": "c#1", "expected": "challenges"},
    {"a": "b#1", "b": "c#1", "expected": "supports", "also_ok": ["none"]}]}


def model(answers):
    """Answers the link question by the two dates in the prompt (order-free)."""
    def ask(prompt):
        found = tuple(sorted(d for d in ("3 March 1850", "4 March 1850", "in 1850") if d in prompt))
        return answers[found]
    return ask


RIGHT = {("3 March 1850", "in 1850"): "1", ("3 March 1850", "4 March 1850"): "2",
         ("4 March 1850", "in 1850"): "3"}


def test_key_facts_take_ids_eras_and_statements_from_the_answer_key():
    question, facts = sl.key_facts(KEY, PACKETS)["p.json"]
    assert question == QUESTION and [f["id"] for f in facts] == ["a#1", "b#1", "c#1"]
    assert facts[0]["statement"].startswith('According to Example Harbour Department: "On 3 March 1850')
    assert facts[1]["family"] == "example gazette" and facts[2]["era"] == ["06-early-colony"]


def test_a_model_that_links_like_the_key_passes_and_an_accepted_alternative_counts_as_right():
    result = sl.score_model(model(RIGHT), sl.key_facts(KEY, PACKETS), LINK_KEY)
    assert result["scores"] == {"pairs": 3, "right": 3, "wrong_links": 0, "missed_links": 0, "unsure": 0}
    assert result["passed"] and result["wrong"] == []


def test_a_link_of_the_wrong_kind_fails_even_when_most_pairs_are_right():
    flipped = {**RIGHT, ("3 March 1850", "4 March 1850"): "1"}  # a conflict called the same fact
    result = sl.score_model(model(flipped), sl.key_facts(KEY, PACKETS), LINK_KEY)
    assert result["scores"]["wrong_links"] == 1 and not result["passed"]
    assert result["wrong"] == [{"a": "a#1", "b": "c#1", "expected": "challenges", "got": "supports"}]


def test_an_unsure_pair_counts_as_none_so_it_is_a_missed_link_not_a_wrong_one():
    answers = iter(["1", "1", "2", "4", "3", "3"])  # a-c answered differently in the two orders
    result = sl.score_model(lambda prompt: next(answers), sl.key_facts(KEY, PACKETS), LINK_KEY)
    assert result["scores"]["unsure"] == 1 and result["scores"]["missed_links"] == 1
    assert result["scores"]["wrong_links"] == 0


def test_main_stops_when_the_link_key_does_not_cover_every_pair_asked(tmp_path, monkeypatch):
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "p.json").write_text(json.dumps(PACKETS[0][1]))
    (tmp_path / "key.json").write_text(json.dumps(KEY))
    (tmp_path / "links.json").write_text(json.dumps({"pairs": LINK_KEY["pairs"][:2]}))
    args = ["--key", str(tmp_path / "key.json"), "--link-key", str(tmp_path / "links.json"),
            "--packets", str(packets), "--models", "Model A", "--output", str(tmp_path / "out.json")]
    assert sl.main(args) == 2 and not (tmp_path / "out.json").exists()


def test_main_scores_each_model_forced_in_turn(tmp_path, monkeypatch):
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "p.json").write_text(json.dumps(PACKETS[0][1]))
    (packets / "MANIFEST.json").write_text(json.dumps({"sources": []}))
    (tmp_path / "key.json").write_text(json.dumps(KEY))
    (tmp_path / "links.json").write_text(json.dumps(LINK_KEY))
    used = []

    class FakePool:
        routing = {sl.ROLE: ["Model A"]}
        models = {"Model A": {"api_id": "a-1", "provider": "openrouter", "rpd": 50}}
        cooldown = {}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            used.append(tuple(only))
            return parse(model(RIGHT)(prompt)), only[0], []

    import gemini_pool
    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "out.json"
    assert sl.main(["--key", str(tmp_path / "key.json"), "--link-key", str(tmp_path / "links.json"),
                    "--packets", str(packets), "--models", "Model A, Model Z", "--output", str(out)]) == 0
    results = json.loads(out.read_text())["results"]
    assert results[0]["passed"] and results[0]["calls"] == 6 and set(used) == {("Model A",)}
    assert results[1]["error"] == f"not in routing role {sl.ROLE}"


def test_the_workflow_runs_the_link_score_into_the_private_output():
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v2-2-model-scoring.yml").read_text()
    assert "scripts/score_links.py --minutes 100" in text
    assert '--output "$PRIVATE_OUTPUT/links.json" >"$PRIVATE_OUTPUT/diagnostics.log" 2>&1' in text


def test_a_rejected_request_ends_that_models_link_trial_only(tmp_path, monkeypatch):
    # Run 38985642200: a provider's 400 (RequestRejected) stopped the whole extraction scoring run.
    packets = tmp_path / "packets"
    packets.mkdir()
    (packets / "p.json").write_text(json.dumps(PACKETS[0][1]))
    (tmp_path / "key.json").write_text(json.dumps(KEY))
    (tmp_path / "links.json").write_text(json.dumps(LINK_KEY))
    import gemini_pool

    class FakePool:
        routing = {sl.ROLE: ["Model A", "Model B"]}
        models = {"Model A": {"api_id": "a"}, "Model B": {"api_id": "b"}}
        cooldown = {}

        def remaining(self, name, role):
            return 10

        def generate_text(self, role, prompt, parse, only=None):
            if only[0] == "Model A":
                raise gemini_pool.RequestRejected("400 Provider returned error")
            return parse(model(RIGHT)(prompt)), only[0], []

    monkeypatch.setattr(gemini_pool, "ModelPool", FakePool)
    out = tmp_path / "out.json"
    assert sl.main(["--key", str(tmp_path / "key.json"), "--link-key", str(tmp_path / "links.json"),
                    "--packets", str(packets), "--models", "Model A, Model B", "--output", str(out)]) == 0
    a, b = json.loads(out.read_text())["results"]
    assert "RequestRejected" in a["stopped"] and b["passed"]
