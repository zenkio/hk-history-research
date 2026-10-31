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
    assert len(asked) == td.cp.MAX_TRIES and rep["sections"][0]["fallback"]
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
