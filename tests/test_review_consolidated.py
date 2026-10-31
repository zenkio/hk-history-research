import review_consolidated as rv
import render_consolidated_facts as rc


def record():
    texts = ["Britain imported Chinese tea and silk.", "China imported British tea and silk.", "Opium paid for tea.",
             "The war began in 1839."]
    return {"facts": [], "sections": [{"title": "Background", "units": [{"text": t, "by": ["A"], "facts": []} for t in texts]}]}


def answer(system, prompt):
    sentence = prompt.split("SENTENCE:\n")[1].split("\n")[0]
    if sentence.startswith("China imported"):
        return "CONFLICT [1]: direction of the tea trade is reversed"
    return "NONE"


def test_related_sentences_share_words():
    units = rv.flat(record())
    assert 0 in rv.related(units, 1) and 3 not in rv.related(units, 1)


def test_conflict_is_flagged_checked_and_shown_disputed():
    rec, rep = rv.run(record(), answer, "M")
    units = rec["sections"][0]["units"]
    assert rep["reviewed"] and rep["conflicts"] == 1 and rep["by_ai"]["A"] == {"flagged": 1, "sentences": 4}
    assert "conflict" not in units[0] and units[1]["conflict"]["judged_by"] == "M"
    html = rc.paragraph_from_units("**1. x** ", units, {})
    assert "Disputed: an AI reviewer" in html and "fact-disputed" in html


def test_bad_answers_are_retried_then_the_sentence_counts_as_unreviewed():
    asked = []
    rec, rep = rv.run(record(), lambda s, p: asked.append(p) or "CONFLICT [9]: x", "M")
    assert not rep["reviewed"] and rep["unreviewed"] == 3 and rep["conflicts"] == 0  # the sentence with no related ones is never asked
    assert all("conflict" not in u for u in rec["sections"][0]["units"])


def test_flagged_sentences_are_marked_and_hidden_behind_a_switch():
    rec, _ = rv.run(record(), answer, "M")
    html = rc.render(rec)
    assert 'class="sent fact-disputed flagged"' in html and 'class="flag-switch"' in html and "1 sentence(s)" in html
    clean, _ = rv.run(record(), lambda s, p: "NONE")
    assert "flag-switch" not in rc.render(clean)
