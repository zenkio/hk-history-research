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
