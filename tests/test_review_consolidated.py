import review_consolidated as rv
import render_consolidated_facts as rc


def record():
    texts = ["Britain imported Chinese tea and silk.", "China imported British tea and silk.", "Opium paid for tea.",
             "The war began in 1839."]
    units = [{"text": t, "by": ["A"], "facts": []} for t in texts]
    units[0]["by"] = ["A", "B"]  # the sentence several AIs back
    return {"facts": [], "sections": [{"title": "Background", "units": units}]}


def answer(system, prompt):
    if prompt.startswith("SENTENCE A:"):
        return "CONTRADICTORY: reversed" if "China imported" in prompt.split("SENTENCE B:")[0] or "China imported" in prompt else "COMPATIBLE"
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


def test_prompt_shows_how_many_ais_back_each_sentence():
    rec = record()
    rec["sections"][0]["units"][0]["by"] = ["A", "B", "C"]
    seen = []
    rv.run(rec, lambda s, p: seen.append(p) or "NONE", "M")
    asked = next(p for p in seen if p.startswith("SENTENCE:\nChina imported"))
    assert "SENTENCE:\nChina imported British tea and silk. (backed by 1 AI)" in asked
    assert "Britain imported Chinese tea and silk. (backed by 3 AIs)" in asked


def test_only_the_side_fewer_ais_back_is_flagged_when_both_sides_report_each_other():
    rec = record()
    units = rec["sections"][0]["units"]
    units[0]["by"] = ["A", "B", "C"]

    def both(system, prompt):
        if prompt.startswith("SENTENCE A:"):
            return "CONTRADICTORY: reversed"
        sentence = prompt.split("SENTENCE:\n")[1].split("\n")[0]
        if sentence.startswith("China imported"):
            return "CONFLICT [1]: reversed"
        if sentence.startswith("Britain imported"):
            return "CONFLICT [1]: reversed"  # lists "China imported" first among its related sentences
        return "NONE"

    rv.run(rec, both, "M")
    assert "conflict" not in units[0] and "conflict" in units[1]


def test_a_pair_the_second_question_finds_compatible_is_not_flagged():
    def call(system, prompt):
        if prompt.startswith("SENTENCE A:"):
            return "COMPATIBLE"
        return "CONFLICT [1]: x" if prompt.split("SENTENCE:\n")[1].startswith("China imported") else "NONE"

    rec, rep = rv.run(record(), call, "M")
    assert rep["conflicts"] == 0


def test_a_sentence_that_already_names_another_account_is_not_asked_about():
    rec = record()
    rec["sections"][0]["units"][1]["text"] = "Another account says China imported British tea and silk."
    rec2, rep = rv.run(rec, lambda s, p: "CONFLICT [1]: x" if "Another account" in p else "NONE", "M")
    assert rep["conflicts"] == 0


def test_a_figure_far_from_a_related_sentences_figure_is_flagged_on_the_side_fewer_ais_back():
    texts = ["About 20,000 chests of opium were destroyed at Humen.", "Over one million chests of opium were destroyed at Humen."]
    units = [{"text": t, "by": b, "facts": []} for t, b in zip(texts, (["A", "B", "C"], ["D"]))]
    rec = {"facts": [], "sections": [{"title": "S", "units": units}]}

    def call(system, prompt):
        if prompt.startswith("SENTENCE:\n") and "Answer one line: `OUTLIER" in prompt:
            return "OUTLIER [1]: 20,000 against over one million" 
        return "NONE"

    rv.run(rec, call, "M")
    assert "conflict" not in units[0] and units[1]["conflict"]["note"].startswith("figure differs")
