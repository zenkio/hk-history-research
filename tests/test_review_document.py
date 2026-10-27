import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_document as rd

GOOD = '{"verdict": "needs_changes", "problems": [{"rule": "cap", "issue": "0.95 is arbitrary", "change": "derive it"}]}'


def test_prompt_carries_the_document_and_asks_for_objections():
    prompt = rd.prompt_for("INVENTED RULES")
    assert "INVENTED RULES" in prompt and "Do not praise" in prompt


def test_parse_review_accepts_json_in_prose_and_rejects_bad_ones():
    assert rd.parse_review("Here: " + GOOD)["verdict"] == "needs_changes"
    assert rd.parse_review("no json") is None
    assert rd.parse_review('{"verdict": "great", "problems": []}') is None
    assert rd.parse_review('{"verdict": "sound"}') is None


def test_parse_review_drops_empty_problems_and_caps_the_list():
    many = ",".join('{"issue": "x"}' for _ in range(20))
    got = rd.parse_review('{"verdict": "unsound", "problems": [' + many + ', {"rule": "no issue"}]}')
    assert len(got["problems"]) == rd.MAX_PROBLEMS


def test_models_are_asked_alone_and_a_failed_one_is_counted_not_hidden():
    results = rd.review({"M1": lambda p: GOOD, "M2": lambda p: "garbage"}, "doc")
    assert results["M2"] is None
    summary = rd.summarise(results)
    assert summary["models_asked"] == 2 and summary["models_answered"] == 1
    assert summary["verdicts"]["needs_changes"] == 1 and summary["problems_listed"] == 1


def test_verdict_spelling_is_normalised():
    assert rd.parse_review('{"verdict": "Needs Changes", "problems": []}')["verdict"] == "needs_changes"


def test_unreadable_first_answer_gets_one_shorter_retry():
    answers = iter(["cut off {\"verdict\": \"unsound\", \"prob", GOOD])
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return next(answers)

    results = rd.review({"M1": ask}, "doc")
    assert results["M1"]["verdict"] == "needs_changes" and len(seen) == 2 and "at most 4 problems" in seen[1]
