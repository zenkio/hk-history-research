"""Owner 2026-11-06: What's New, Timeline, People, Places first; people and places ranked by importance, not A-Z."""
import menu_order as mo


def _w(root, rel, text="x"):
    p = root / "content" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_top_level_order_and_meta_last(tmp_path):
    for rel in ("00_Meta/a.md", "Whats_New.md", "01_Timeline/t.md", "02_Entities/People/p.md", "03_Angles/a.md", "tags/x.md"):
        _w(tmp_path, rel)
    order = mo.build(tmp_path)["order"]
    assert order[""] == ["whats_new", "01_timeline", "02_entities", "03_angles", "tags", "00_meta"]
    assert order["02_entities"] == ["02_entities/people", "02_entities/places"]


def test_people_are_ranked_by_links_then_ai_importance(tmp_path):
    _w(tmp_path, "02_Entities/People/aaa.md")
    _w(tmp_path, "02_Entities/People/zed.md")
    _w(tmp_path, "02_Entities/People/mid.md", "---\nimportance: 9\n---\n")
    for i in range(3):
        _w(tmp_path, f"01_Timeline/e{i}.md", "[[02_Entities/People/zed|Zed]] and [[zed]] and [Z](/02_Entities/People/zed)")
    _w(tmp_path, "01_Timeline/f.md", "[[aaa]]")
    data = mo.build(tmp_path)
    assert data["links"]["02_entities/people/zed"] == 3  # three pages, however often each links
    assert data["order"]["02_entities/people"] == ["02_entities/people/mid", "02_entities/people/zed", "02_entities/people/aaa"]
