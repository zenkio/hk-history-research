import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_reliability as sr

# Owner rule 2026-10-20. All sources here are invented.


def table(full=100):
    scale = full / 100
    return {"full_marks": full, "sources": {
        "record": {"score": 92 * scale}, "yearbook": {"score": 80 * scale},
        "paper": {"score": 66 * scale}, "party": {"score": 70 * scale, "by_kind": {"contested": 50 * scale}},
        "blog": {"score": 30 * scale}}}


def v(value, source, level, family=None):
    return {"value": value, "source_id": source, "family": family or source, "level": level}


def test_levels_are_shares_of_full_marks_so_500_behaves_like_100():
    assert sr.level(table(100), "record") == sr.level(table(500), "record") == 0.92
    assert sr.level(table(), "party") == 0.7 and sr.level(table(), "party", "contested") == 0.5
    assert sr.level(table(), "unknown") is None


def test_tier_names_are_labels_for_ranges():
    assert [sr.tier_of(x) for x in (0.95, 0.8, 0.65, 0.5, 0.1, None)] == [
        "primary_record", "authoritative", "reliable", "cautious", "weak", "unrated"]


def test_a_fact_from_one_reliable_source_is_accepted_without_a_second_source():
    r = sr.resolve([v("1841", "record", 0.92)])
    assert r["accepted"] and r["confidence"] == 0.92 and r["challenges"] == []
    assert not sr.resolve([v("1841", "blog", 0.3)])["accepted"]


def test_independent_support_raises_confidence_and_the_same_family_counts_once():
    one = sr.resolve([v("a", "yearbook", 0.8)])["confidence"]
    two = sr.resolve([v("a", "yearbook", 0.8), v("a", "paper", 0.66)])["confidence"]
    same = sr.resolve([v("a", "yearbook", 0.8, "gov"), v("a", "paper", 0.66, "gov")])["confidence"]
    assert two > one and same == one


def test_a_weak_source_cannot_challenge_a_reliable_one_but_is_noted():
    r = sr.resolve([v("a", "record", 0.92), v("b", "blog", 0.3)])
    assert r["leading"] == "a" and r["challenges"] == [] and r["noted_disputes"][0]["source_id"] == "blog"
    assert r["confidence"] == 0.92


def test_a_source_clearly_below_the_origin_cannot_challenge_even_if_reliable():
    assert not sr.may_challenge(0.61, 0.95) and sr.may_challenge(0.75, 0.92)
    r = sr.resolve([v("a", "record", 0.95), v("b", "paper", 0.61)])
    assert r["challenges"] == [] and len(r["noted_disputes"]) == 1


def test_a_reliable_source_saying_something_different_challenges_and_lowers_confidence():
    r = sr.resolve([v("a", "record", 0.92), v("b", "yearbook", 0.75)])
    assert r["status"] == sr.LEADING and r["leading"] == "a" and len(r["challenges"]) == 1
    assert r["confidence"] < 0.92


def test_conflicts_lean_to_the_highest_score_unless_it_is_too_close_to_call():
    r = sr.resolve([v("a", "yearbook", 0.80), v("b", "paper", 0.62)])
    assert r["leading"] == "a" and r["status"] == sr.LEADING
    close = sr.resolve([v("a", "yearbook", 0.80), v("b", "party", 0.70)])
    assert close["status"] == sr.DISPUTED and not close["accepted"]
    assert set(close["versions"]) == {"a", "b"}          # nothing is dropped


def test_unrated_sources_add_no_support_and_never_challenge():
    r = sr.resolve([v("a", "record", 0.92), v("b", "x", None)])
    assert r["challenges"] == [] and r["confidence"] == 0.92


def test_the_table_loads_from_json_and_needs_full_marks(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(table()))
    assert sr.level(sr.load_table(p), "record") == 0.92
    p.write_text(json.dumps({"sources": {}}))
    try:
        sr.load_table(p)
        raise AssertionError("should refuse a table without full_marks")
    except ValueError:
        pass
