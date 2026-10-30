import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_consolidated_facts as rc

RECORD = {"event": "e", "facts": [
    {"id": "f1", "kind": "date", "text": "Signed <1842>", "status": "accepted",
     "backed_by_ai": [{"model": "A", "said": "1842"}, {"model": "B", "said": "1842"}],
     "differs": [{"model": "C", "said": "1843"}], "not_mentioned_by": ["D"], "backed_by_sources": []},
    {"id": "f2", "kind": "number", "text": "21 million", "status": "disputed",
     "backed_by_ai": [], "backed_by_sources": [{"source": "Treaty text"}]}],
    "narrative": ["**Lead.** Signed {{f1|in 1842 <ok>}} and cost {{f2|21 million}}."]}


def setup(tmp_path, marker=True, record=True):
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    (tmp_path / "content/05_Multi_AI/e.md").write_text(
        "---\ntitle: E\n---\n\nIntro\n\n" + (rc.MARKER if marker else "") + "\n\n## Next\n")
    (tmp_path / "content/05_Multi_AI/other.md").write_text("no marker\n")
    if record:
        (tmp_path / "data/consolidated_facts").mkdir(parents=True)
        (tmp_path / "data/consolidated_facts/e.json").write_text(json.dumps(RECORD))


def test_marker_becomes_a_consolidated_block_with_switch_and_tips(tmp_path):
    setup(tmp_path)
    assert rc.build(tmp_path) == [str(tmp_path / "content/05_Multi_AI/e.md")]
    text = (tmp_path / "content/05_Multi_AI/e.md").read_text()
    assert rc.MARKER not in text and "## Consolidated version" in text and "## Next" in text
    assert '<input type="checkbox">' in text  # switch starts off (no "checked" on it)
    assert text.count('type="radio"') == len(rc.COLOURS) and text.count(" checked>") == 1  # one default colour
    assert "<b>Backed by AI:</b> A, B" in text and "C (1843)" in text
    assert "not yet checked" not in text  # plain accepted is not repeated (owner 2026-10-30)
    assert "<i>disputed</i>" in text
    assert "Not mentioned" not in text  # owner rule 2026-10-30: never list who did not mention a fact
    assert "Treaty text" in text and "none yet" not in text and text.lower().count("official sources") == 3  # the intro note, then only f2 (sentence tip + list); f1 has none
    assert "Signed &lt;1842&gt;" in text  # page text is escaped
    assert (tmp_path / "content/05_Multi_AI/other.md").read_text() == "no marker\n"


def test_missing_record_file_fails_loudly(tmp_path):
    setup(tmp_path, record=False)
    with pytest.raises(SystemExit, match="missing"):
        rc.build(tmp_path)


def test_each_sentence_is_one_hover_span_with_its_ais_and_facts(tmp_path):
    # owner 2026-10-30: the whole sentence is underlined and shows the tip, not only the date inside it
    setup(tmp_path)
    rec = dict(RECORD, narrative=["**Lead.** Signed {{f1|in 1842 <ok>}} and cost {{f2|21 million}}. Plain second one."],
               sentence_ai=[[["A", "B"], ["A"]]])
    (tmp_path / "data/consolidated_facts/e.json").write_text(json.dumps(rec))
    rc.build(tmp_path)
    text = (tmp_path / "content/05_Multi_AI/e.md").read_text()
    assert text.count('<span class="sent') == 2
    assert '<p><strong>Lead.</strong> <span class="sent fact-disputed" tabindex="0">Signed <mark class="fact-in">in 1842 &lt;ok&gt;</mark>' in text
    assert "<b>Backed by AI:</b> A, B<br><b>in 1842 &lt;ok&gt;</b>: A, B" in text
    assert "<b>Backed by AI:</b> A</span></span></p>" in text  # sentence without a fact still shows its AIs
    assert text.index("Lead.") < text.index("All 2 facts and who backs them")  # narrative above the list


def test_narrative_with_unknown_fact_id_fails(tmp_path):
    setup(tmp_path)
    bad = dict(RECORD, narrative=["x {{nope|y}}"])
    (tmp_path / "data/consolidated_facts/e.json").write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="unknown fact id"):
        rc.build(tmp_path)
