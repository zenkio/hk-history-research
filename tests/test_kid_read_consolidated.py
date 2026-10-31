import kid_read_consolidated as kr


def record():
    units = [{"text": "Lin confined merchants to their factories.", "zh": "⟦林則徐⟧將商人限制在行館內。", "by": ["A"]},
             {"text": "Elliot promised compensation.", "zh": "⟦義律⟧承諾賠償。", "by": ["A"]}]
    return {"sections": [{"title": "What happened", "units": units}], "glossary": {"Elliot": "x"}}


def kid(system, prompt):
    if "Traditional Chinese" in prompt:
        return "Q [1] | 行館 | 行館是什麼？\nQ [2] | 義律 | 義律是誰？\nQ [2] | 不在句子 | 亂寫"
    return "Q [1] | factories | What are factories here?\nQ [2] | Elliot | Who is Elliot?"


def test_questions_are_kept_per_language_and_checked_against_the_sentence():
    rec, rep = kr.run(record(), kid, "M")
    terms = {(q["lang"], q["term"]) for q in rec["questions"]}
    assert terms == {("en", "factories"), ("zh", "行館"), ("zh", "義律")}  # glossary skips Elliot; invented term dropped
    assert rep["by_lang"] == {"en": 1, "zh": 2} and all(q["status"] == "open" and q["answer"] is None for q in rec["questions"])


def test_none_and_unreadable_answers():
    rec, rep = kr.run(record(), lambda s, p: "NONE", "M")
    assert rep["questions"] == 0 and rep["unread"] == 0
    rec, rep = kr.run(record(), lambda s, p: "blah", "M")
    assert rep["unread"] == 2
