import translate_consolidated as tc
import render_consolidated_facts as rc

TEXTS = ["Lin arrived in 1839.", "About 20,283 chests were surrendered."]


def test_good_answer_is_accepted():
    out, problems = tc.check("[1] 林則徐於1839年抵達。\n[2] 約20,283箱鴉片被交出。", TEXTS)
    assert not problems and out[0].startswith("林則徐")


def test_lost_number_missing_line_and_non_chinese_are_caught():
    assert tc.check("[1] 林則徐抵達。\n[2] 約20,283箱。", TEXTS)[1] == ["[1] lost the number(s) 1839"]
    assert "expected lines" in tc.check("[1] 林則徐於1839年抵達。", TEXTS)[1][0]
    assert tc.check("[1] Lin 1839\n[2] 20,283箱", TEXTS)[1] == ["[1] is not Chinese"]


def test_retry_with_feedback_then_giveup_keeps_english():
    prompts = []

    def call(system, prompt):
        prompts.append(prompt)
        return "[1] 林則徐抵達。\n[2] 約20,283箱。"

    out, left, used = tc.translate_section(call, "S", TEXTS)
    assert out == [] and left and used == tc.MAX_TRIES and "lost the number" in prompts[1]


def test_translation_is_set_and_rendered_with_english_in_the_tip():
    record = {"facts": [], "sections": [{"title": "What happened", "units": [{"text": TEXTS[0], "by": ["A"], "facts": []}]}]}
    tc.run(record, lambda s, p: "[1] 林則徐於1839年抵達。")
    assert record["sections"][0]["units"][0]["zh"].startswith("林則徐")
    html = rc.paragraph_from_units("**1. x** ", record["sections"][0]["units"], {})
    assert 'class="lang-zh"' in html and "林則徐於1839年抵達。" in html
    assert f'<span class="lang-en" lang="en">{TEXTS[0]}</span>' in html


def test_untranslated_english_word_is_caught():
    assert "left English words" in tc.check("[1] 林則徐於1839年抵達。\n[2] 約20,283箱 one million 箱。", TEXTS)[1][0]


def test_page_has_language_switch_and_chinese_headings_only_with_a_translation():
    unit = {"text": TEXTS[0], "by": ["A"], "facts": []}
    rec = {"event": "e", "facts": [], "sections": [{"title": "Background", "units": [dict(unit, zh="林則徐抵達。")]}]}
    html = rc.render(rec)
    assert 'data-lang="zh"' in html and "背景" in html and "顯示每句由哪些 AI 支持" in html
    plain = rc.render({"event": "e", "facts": [], "sections": [{"title": "Background", "units": [unit]}]})
    assert "lang-switch" not in plain and "lang-zh" not in plain and "**" not in plain


def test_name_marks_are_kept_checked_and_drawn_underlined():
    out, problems = tc.check("[1] ⟦林則徐⟧於1839年抵達。\n[2] 約20,283箱。", TEXTS)
    assert not problems and out[0].startswith("⟦林則徐⟧")
    assert "unmatched" in tc.check("[1] ⟦林則徐於1839年抵達。\n[2] 約20,283箱。", TEXTS)[1][0]
    unit = {"text": TEXTS[0], "by": ["A"], "facts": [], "zh": out[0]}
    assert '<span class="pn">林則徐</span>' in rc.paragraph_from_units("**1. x** ", [unit], {})


def test_english_month_left_in_the_chinese_is_a_problem():
    # owner 2026-10-31: "主權於1 July 1997移交" mixed English into the Chinese version
    _, problems = tc.check("[1] 主權於1 July 1997移交。", ["Sovereignty passed on 1 July 1997."])
    assert any("July" in p for p in problems)
    _, ok = tc.check("[1] 主權於1997年7月1日移交。", ["Sovereignty passed on 1 July 1997."])
    assert not ok


def test_an_overloaded_model_leaves_the_section_untranslated_instead_of_crashing():
    def down(system, prompt):
        raise tc.cp.WriterUnavailable("503")
    rec = {"sections": [{"title": "S", "units": [{"text": "Hello world.", "by": ["A"]}]}]}
    rec, rep = tc.run(rec, down)
    assert rep["sections"][0]["translated"] is False and "zh" not in rec["sections"][0]["units"][0]


def test_an_old_chinese_sentence_with_an_english_month_is_translated_again():
    def good(system, prompt):
        return "[1] 主權於1997年7月1日移交。"
    rec = {"sections": [{"title": "S", "units": [{"text": "Sovereignty passed on 1 July 1997.", "by": ["A"],
                                                  "zh": "主權於1 July 1997移交。"}]}]}
    rec, rep = tc.run(rec, good)
    assert rec["sections"][0]["units"][0]["zh"] == "主權於1997年7月1日移交。"


def test_colloquial_cantonese_is_a_problem_but_written_chinese_with_關係_is_not():
    import consolidate_pipeline as cp
    assert "究係" in cp.cantonese("九龍割讓究係英國要求抑或中國主動提議") and "邊個" in cp.cantonese("趙紫陽係邊個？")
    assert cp.cantonese("兩國關係與聯係，是誰簽署的？") == []
    import translate_consolidated as tc
    out, problems = tc.check("[1] 佢係首相。", ["He was Prime Minister."])
    assert any("Cantonese" in p for p in problems)


def test_an_old_cantonese_translation_is_translated_again():
    import translate_consolidated as tc
    rec = {"sections": [{"title": "S", "units": [{"text": "He was Prime Minister.", "zh": "佢係首相。"}]}]}
    calls = []
    rec, _ = tc.run(rec, lambda s, p: calls.append(1) or "[1] 他是首相。")
    assert calls and rec["sections"][0]["units"][0]["zh"] == "他是首相。"


def test_page_and_section_titles_are_translated_checked_and_not_asked_twice():
    import translate_consolidated as tc
    rec = {"title": "Convention of Peking", "sections": [{"title": "What happened", "units": []},
                                                         {"title": "Consequences", "units": []}]}
    answers = iter(["[1] 佢係北京條約\n[2] 事件經過\n[3] 後果", "[1] ⟦北京條約⟧\n[2] 事件經過\n[3] 後果"])
    calls = []
    assert tc.translate_titles(lambda s, p: calls.append(p) or next(answers), rec) == []
    assert rec["title_zh"] == "⟦北京條約⟧" and rec["sections"][1]["title_zh"] == "後果"
    assert "Cantonese" in calls[1]  # the first answer was sent back
    assert tc.translate_titles(lambda s, p: 1 / 0, rec) == []  # nothing missing: no call
