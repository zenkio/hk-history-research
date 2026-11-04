import json

import titles_zh as tz


def test_pages_with_a_chinese_title_and_folders_get_names_marks_removed(tmp_path):
    (tmp_path / "data/consolidated_facts").mkdir(parents=True)
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    (tmp_path / "content/05_Multi_AI/lin-humen.md").write_text("x")
    (tmp_path / "data/consolidated_facts/lin-humen.json").write_text(json.dumps({"title_zh": "⟦林則徐⟧在⟦虎門⟧銷毀鴉片"}))
    (tmp_path / "data/consolidated_facts/gone.json").write_text(json.dumps({"title_zh": "沒有頁面"}))
    t = tz.build(tmp_path)
    assert t["05_Multi_AI/lin-humen"] == "林則徐在虎門銷毀鴉片"
    assert "05_Multi_AI/gone" not in t and t["01_Timeline"] == "時間線"
