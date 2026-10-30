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
