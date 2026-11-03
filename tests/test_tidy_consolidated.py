import tidy_consolidated as td


def record():
    texts = ["The drug was mixed with lime and salt in trenches and flushed into the sea.",
             "It was mixed with lime and salt and flushed into the sea.",
             "Another account says it was flushed into the Pearl River.",
             "Lin reported the work done on 26 June."]
    units = [{"text": t, "by": [b], "facts": [], "zh": "中"} for t, b in zip(texts, ["A", "B", "C", "A"])]
    return {"facts": [], "sections": [{"title": "What happened", "units": units}]}


GOOD = ("[C1,C2] The drug was mixed with lime and salt in trenches, then flushed into the sea.\n"
        "[C3] Another account says it was flushed into the Pearl River.\n"
        "[C4] Lin reported the work done on 26 June.")


def test_same_sentences_are_merged_with_the_union_of_backers_and_the_rest_is_kept_unchanged():
    rec, rep = td.run(record(), lambda s, p: GOOD)
    units = rec["sections"][0]["units"]
    assert [len(x) for x in (units,)] == [3] and units[0]["by"] == ["A", "B"]
    assert units[1]["zh"] == "中" and "zh" not in units[0]  # unchanged sentences keep theirs, merged ones are translated again
    assert rep["sections"][0]["before"] == 4 and not rep["sections"][0]["fallback"]
    assert rec["sentence_ai"][0][0] == ["A", "B"]


def test_a_merge_that_drops_a_sentence_or_adds_a_number_is_retried_then_left_alone():
    asked = []

    def call(s, p):
        asked.append(p)
        return "[C1,C2] The drug was mixed with lime in 1840.\n[C4] Lin reported the work done on 26 June."

    rec, rep = td.run(record(), call)
    assert len(asked) >= td.cp.MAX_TRIES and rep["sections"][0]["fallback"]  # the halves are tried too
    assert len(rec["sections"][0]["units"]) == 4 and "not used" in asked[1] or "number" in asked[1]


def test_thinking_aloud_before_the_answer_is_ignored():
    rec, rep = td.run(record(), lambda s, p: "We need to merge the sentences that say the same thing.\n" + GOOD)
    assert not rep["sections"][0]["fallback"] and rep["sections"][0]["after"] == 3


def test_a_long_section_is_tidied_in_chunks_and_each_chunk_is_answered_on_its_own():
    import re
    texts = ["Alpha ships anchored near Macao.", "Bravo merchants stored opium aboard hulks.",
             "Charlie officials inspected Canton warehouses.", "Delta soldiers guarded Humen forts.",
             "Echo traders petitioned London parliament.", "Foxtrot villagers farmed rice terraces.",
             "Golf fishermen mended nets daily.", "Hotel scholars debated tribute customs.",
             "India growers harvested poppy crops.", "Juliet captains charted Pearl River channels.",
             "Kilo clerks recorded silver payments.", "Lima envoys carried imperial edicts."]
    rec = {"facts": [], "sections": [{"title": "S", "units": [{"text": t, "by": ["A"], "facts": []} for t in texts]}]}
    asked = []

    def echo(system, prompt):  # answers every numbered sentence unchanged
        asked.append(prompt)
        return "\n".join(f"[C{n}] {t}" for n, t in re.findall(r"^C(\d+)\. (.+?) \(backed by", prompt, re.M))

    out, rep = td.run(rec, echo)
    assert len(asked) == 2 and len(out["sections"][0]["units"]) == 12 and not rep["sections"][0]["fallback"]
    assert "Alpha" in asked[0] and "Alpha" not in asked[1] and "Lima" in asked[1]


def test_a_sentence_only_a_low_trust_ai_backs_may_be_left_out_and_is_kept_in_the_record():
    rec = record()
    rec["sections"][0]["units"][3]["by"] = ["Xing 4.0"]
    answer = ("[C1,C2] The drug was mixed with lime and salt in trenches, then flushed into the sea.\n"
              "[C3] Another account says it was flushed into the Pearl River.\n[C4] OMIT")
    out, rep = td.run(rec, lambda s, p: answer, low_trust=["Xing 4.0"])
    assert [u["text"][:12] for u in out["sections"][0]["units"]] == ["The drug was", "Another acco"]
    assert out["omitted"][0]["by"] == ["Xing 4.0"] and out["omitted"][0]["section"] == "What happened"


def test_a_sentence_many_ais_back_may_not_be_left_out():
    answer = ("[C1,C2] The drug was mixed with lime and salt in trenches, then flushed into the sea.\n"
              "[C3] Another account says it was flushed into the Pearl River.\n[C4] Lin reported the work done on 26 June.\n[C2] OMIT")
    rec = record()
    asked = []
    out, rep = td.run(rec, lambda s, p: asked.append(p) or answer)
    assert rep["sections"][0]["fallback"] and "may not be left out" in asked[1] and out["omitted"] == []


def test_nothing_may_be_left_out_unless_an_ai_is_on_the_low_trust_list():
    rec = record()
    rec["sections"][0]["units"][3]["by"] = ["Xing 4.0"]
    answer = ("[C1,C2] The drug was mixed with lime and salt in trenches, then flushed into the sea.\n"
              "[C3] Another account says it was flushed into the Pearl River.\n[C4] OMIT")
    out, rep = td.run(rec, lambda s, p: answer)
    assert rep["sections"][0]["fallback"] and out["omitted"] == [] and td.LOW_TRUST == []


def test_a_chunk_that_fails_as_a_whole_is_tried_again_in_halves():
    # owner 2026-10-31: the Joint Declaration section kept its duplicates because the whole chunk failed one check
    def call(s, p):
        if "C3." in p and "C1." in p:  # the whole chunk: unusable answer
            return "[C1] The drug was flushed."
        if "Lin reported" not in p:
            return "[C1,C2] The drug was mixed with lime and salt in trenches, then flushed into the sea."
        return "[C1] Another account says it was flushed into the Pearl River.\n[C2] Lin reported the work done on 26 June."

    rec, rep = td.run(record(), call)
    assert [u["text"][:12] for u in rec["sections"][0]["units"]] == ["The drug was", "Another acco", "Lin reported"]


def test_near_duplicates_find_the_same_point_told_twice_but_not_different_points():
    import tidy_consolidated as td
    same = ["It ended the Second Opium War (1856-1860).", "The Convention of Peking concluded the Second Opium War.",
            "China ratified the 1858 Treaty of Tientsin and ceded the Kowloon Peninsula south of Boundary Street.",
            "Britain secured ratification of the 1858 Treaty of Tianjin and the Kowloon Peninsula south of Boundary Street."]
    assert td.near_duplicates(same) == [(0, 1), (2, 3)]
    assert td.near_duplicates(["Britain gained Hong Kong Island in 1842.", "Britain gained Kowloon in 1860."]) == []


def test_a_merge_that_leaves_the_same_point_twice_is_sent_back_once_then_kept_and_counted():
    import tidy_consolidated as td
    units = [{"text": "The Convention of Peking ended the Second Opium War.", "by": ["A"]},
             {"text": "It ended the Second Opium War in 1860.", "by": ["B"]},
             {"text": "France signed a separate convention.", "by": ["A"]}]
    prompts = []

    def call(system, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:  # identity: nothing merged
            return "[C1] The Convention of Peking ended the Second Opium War.\n[C2] It ended the Second Opium War in 1860.\n[C3] France signed a separate convention."
        return "[C1,C2] The Convention of Peking ended the Second Opium War in 1860.\n[C3] France signed a separate convention."
    dups = []
    out, problems, used = td.tidy_chunk(call, "S", units, 2, [], None, dups)
    assert len(out) == 2 and problems == [] and dups == [] and "tell the same point twice" in prompts[1]
    dups = []
    out, _, _ = td.tidy_chunk(lambda s, p: "[C1] The Convention of Peking ended the Second Opium War.\n[C2] It ended the Second Opium War in 1860.\n[C3] France signed a separate convention.", "S", units, 2, [], None, dups)
    assert len(out) == 3 and dups  # still twice after the tries: kept, and counted so the page status shows it


def test_a_repair_run_tidies_only_the_sections_that_still_repeat_a_point():
    import tidy_consolidated as td
    clean = [{"text": "Lin arrived in Canton in 1839.", "by": ["A"], "zh": "中"}, {"text": "France signed a convention.", "by": ["A"], "zh": "中"}]
    dirty = [{"text": "The Convention of Peking ended the Second Opium War.", "by": ["A"]},
             {"text": "It ended the Second Opium War in 1860.", "by": ["B"]}]
    rec = {"facts": [], "sections": [{"title": "Clean", "units": clean}, {"title": "Dirty", "units": dirty}]}
    asked = []

    def call(system, prompt):
        asked.append(prompt)
        return "[C1,C2] The Convention of Peking ended the Second Opium War in 1860."
    rec, report = td.run(rec, call, only_problems=True)
    assert len(asked) == 1 and "Dirty" in asked[0] and report["redone"] == 1
    assert [u["text"] for u in rec["sections"][0]["units"]] == [u["text"] for u in clean] and len(rec["sections"][1]["units"]) == 1


def test_a_sentence_cut_at_an_abbreviation_is_joined_again_and_not_cut_in_the_first_place():
    import tidy_consolidated as td
    import render_consolidated_facts as r
    text = "The Qing Dynasty under the Xianfeng Emperor (r. 1850–1861) was weak. Prince Gong set up the office."
    assert r.split_sentences(text)[1] == ["The Qing Dynasty under the Xianfeng Emperor (r. 1850–1861) was weak.", "Prince Gong set up the office."]
    cut = [{"text": "The Qing Dynasty under the Xianfeng Emperor (r. ", "by": ["A"]}, {"text": "1850–1861) was weak.", "by": ["B"]}]
    assert [u["text"] for u in td.rejoin_fragments(cut)] == ["The Qing Dynasty under the Xianfeng Emperor (r.  1850–1861) was weak.".replace("  ", " ")]
    assert td.rejoin_fragments(cut)[0]["by"] == ["A", "B"]


def test_repeats_that_fall_in_different_chunks_are_tidied_together():
    import tidy_consolidated as td
    texts = ["Lin Zexu arrived in Canton in March 1839.", "Elliot ordered the merchants to surrender opium.",
             "The Thirteen Factories were blockaded for weeks.", "Parliament debated an expedition in April 1840.",
             "Palmerston wrote instructions to the fleet.", "Chusan fell to the British in July 1840.",
             "Qishan negotiated at Taku before the Chuenpi talks."] + \
            ["Prince Gong established the Zongli Yamen in 1861, beginning the Tongzhi Restoration.",
             "Another unrelated point about trade tariffs.", "More on opium chests and silver.",
             "Prince Gong set up the Zongli Yamen in 1861."]
    units = [{"text": x, "by": ["A"]} for x in texts]

    def call(system, prompt):
        lines = [l for l in prompt.splitlines() if l.startswith("C") and ". " in l]
        if len(lines) == 2 and "Zongli" in prompt:
            return "[C1,C2] Prince Gong established the Zongli Yamen in 1861, beginning the Tongzhi Restoration."
        return "\n".join(f"[C{i}] " + l.split(". ", 1)[1].rsplit(" (backed", 1)[0] for i, l in enumerate(lines, 1))
    dups = []
    out, problems, _ = td.tidy_section(call, "S", units, 2, [], None, dups)
    assert len(out) == len(texts) - 1 and dups == [] and sum("Zongli" in u["text"] for u in out) == 1
