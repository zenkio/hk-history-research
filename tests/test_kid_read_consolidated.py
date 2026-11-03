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


def test_at_most_five_questions_a_section_and_the_level_is_named():
    texts = ["Alpha beta gamma delta epsilon zeta eta."]
    asked = []
    many = "\n".join(f"Q [1] | {w} | What is {w}?" for w in ["Alpha", "beta", "gamma", "delta", "epsilon", "zeta"])
    got = kr.ask(lambda s, p: asked.append(p) or many, "en", "S", texts)
    assert len(got) == kr.MAX_PER_SECTION and "B1" in asked[0]


def test_a_chinese_question_in_colloquial_cantonese_is_never_kept():
    """Zenkio 2026-11-03: '九龍割讓究係英國要求抑或中國主動提議' is Cantonese, not written Chinese."""
    texts = ["九龍被割讓。", "義律到達。"]
    ans = "Q [1] | 九龍 | 九龍割讓究係英國要求抑或中國主動提議？\nQ [2] | 義律 | 義律是誰？"
    got = kr.ask(lambda s, p: ans, "zh", "S", texts, tries=2)
    assert got == [(2, "義律", "義律是誰？")]


def test_a_repair_run_asks_again_only_where_a_question_went_stale():
    rec = record()
    rec["sections"].append({"title": "Other", "units": [{"text": "Peace came.", "zh": "和平來臨。", "by": ["A"]}]})
    kr.run(rec, lambda s, p: "NONE" if ("Peace" in p or "和平" in p) else kid(s, p), "M")
    first = [q["id"] for q in rec["questions"] if q["section"] == "Other"]
    for q in rec["questions"]:
        if q["lang"] == "zh" and q["term"] == "行館":
            q["question"] = "行館係咩？"  # colloquial Cantonese: stale
    asked = []

    def call(system, prompt):
        asked.append(prompt)
        return "NONE" if ("Peace" in prompt or "和平" in prompt) else kid(system, prompt)
    rec, rep = kr.run(rec, call, "M", only_problems=True)
    assert len(asked) == 1 and "What happened" in asked[0] and rep["asked_again"] == 1
    assert not any(kr.cp.cantonese(q["question"]) for q in rec["questions"] if q["lang"] == "zh")
    assert len(rec["questions"]) == len({q["id"] for q in rec["questions"]})
