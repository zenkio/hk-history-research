import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consolidate_pipeline as cp
from test_consolidate_drafts import PAGE

GOOD = ("The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking, and Pottinger signed for "
        "Britain, although another account gives 29 August 1843.")


def record():
    return {"facts": [{"id": "f1", "text": "Signed 29 August 1842"}]}


def test_writer_is_told_what_failed_and_a_passing_try_is_kept():
    prompts = []

    def call(system, prompt):
        prompts.append(prompt)
        return "The Treaty was drawn up by the Draft model." if len(prompts) % 3 == 1 else GOOD
    text, left, used = cp.write_section(call, "What happened",
                                        ["The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking."],
                                        [("Claude", "Pottinger signed for Britain."),
                                         ("Gemini", "29 August 1843 was given by this draft.")])
    assert (left, used) == ([], 2) and text == GOOD
    assert "failed these checks" in prompts[1] and "do not write" in prompts[1]


def test_section_that_never_passes_falls_back_to_the_plain_merge_and_is_reported():
    rec, report = cp.run(PAGE, record(), lambda s, p: "Nothing useful.", tries=2)
    assert report["sections"][0]["fallback"] and report["sections"][0]["tries"] == 2
    assert "Pottinger signed for Britain." in " ".join(rec["narrative"])


def test_invented_number_is_refused():
    assert any("1999" in p for p in cp.check_section(GOOD + " In 1999 it ended.",
              ["The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking."],
              [("Claude", "Pottinger signed for Britain.")]))
