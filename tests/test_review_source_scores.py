import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_source_scores as rs

# Invented sources only; the real table and descriptions are private.
TABLE = {"full_marks": 100, "sources": {
    "a": {"score": 90}, "b": {"score": 50, "by_kind": {"contested": 30}}}}
RECORDS = {"a": {"title": "Invented Register", "institution": "Invented Office"},
           "b": {"title": "Invented Statement", "institution": "Invented Party"}}


def reply(level):
    return "{" + ", ".join(f'"{name}": {level}' for name, _ in rs.CRITERIA) + "}"


def test_prompt_hides_the_draft_score_and_names_all_criteria():
    prompt = rs.prompt_for(RECORDS["a"])
    assert "90" not in prompt and "Invented Register" in prompt
    assert all(name in prompt for name, _ in rs.CRITERIA)


def test_parse_ratings_accepts_json_in_prose_and_rejects_bad_ones():
    assert rs.share_of(rs.parse_ratings("Sure: " + reply(8))) == 0.8
    assert rs.parse_ratings("no json") is None
    assert rs.parse_ratings(reply(11)) is None
    assert rs.parse_ratings('{"provenance": 5}') is None


def test_review_asks_contested_only_where_the_table_has_it_and_measures_spread():
    asks = {"M1": lambda p: reply(9), "M2": lambda p: reply(8)}
    reviews = rs.review(asks, TABLE, RECORDS)
    assert set(reviews["a"]) == {"plain"} and set(reviews["b"]) == {"plain", "contested"}
    summary = rs.summarise(TABLE, reviews)
    assert summary["median_spread"] == 0.1 and summary["suggested_close_call"] == 0.1


def test_draft_far_from_the_reviewers_is_listed_as_disputed():
    reviews = {"a": {"plain": {"M1": 0.6, "M2": 0.7}}, "b": {"plain": {"M1": 0.5, "M2": 0.5}}}
    summary = rs.summarise(TABLE, reviews)
    assert [d["source_id"] for d in summary["disputes"]] == ["a"]
