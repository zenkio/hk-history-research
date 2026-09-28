"""The published search index must not carry the full text of every page."""
import json

import trim_search_index as t


def test_page_text_is_cut_to_its_opening_and_the_rest_is_kept(tmp_path):
    index = {"a": {"title": "Shek Kip Mei fire", "tags": ["evidence-b"], "links": ["b"],
                   "content": "The fire broke out on 25 December 1953.\n\n" + "More detail. " * 200},
             "b": {"title": "Short", "tags": [], "links": [], "content": "Only a line."}}
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "contentIndex.json").write_text(json.dumps(index), encoding="utf-8")

    t.main(str(tmp_path))

    out = json.loads((tmp_path / "static" / "contentIndex.json").read_text(encoding="utf-8"))
    assert out["a"]["content"].startswith("The fire broke out on 25 December 1953. More detail.")
    assert len(out["a"]["content"]) <= t.KEEP_CHARS + 2 and out["a"]["content"].endswith("…")
    assert out["a"]["title"] == "Shek Kip Mei fire" and out["a"]["tags"] == ["evidence-b"] and out["a"]["links"] == ["b"]
    assert out["b"]["content"] == "Only a line."
