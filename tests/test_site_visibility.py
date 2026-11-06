"""Owner 2026-11-06: Sources and 04_Unverified are never shown; 00_Meta is shown in the preview only."""
import site_visibility as sv


def _page(root, rel, text="---\ntitle: T\n---\nbody\n"):
    p = root / "content" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_preview_hides_sources_and_unverified_but_keeps_meta(tmp_path):
    s, u, m, t = (_page(tmp_path, r) for r in ("Sources/a.md", "04_Unverified/b.md", "00_Meta/c.md", "01_Timeline/d.md"))
    assert sv.apply("preview", tmp_path) == 2
    assert "draft: true" in s.read_text() and "draft: true" in u.read_text()
    assert "draft" not in m.read_text() and "draft" not in t.read_text()


def test_production_also_hides_meta_and_is_idempotent(tmp_path):
    m = _page(tmp_path, "00_Meta/c.md")
    assert sv.apply("production", tmp_path) == 1
    assert sv.apply("production", tmp_path) == 0
    assert m.read_text().count("draft: true") == 1 and "body" in m.read_text()


def test_page_without_front_matter_and_with_draft_false(tmp_path):
    a = _page(tmp_path, "Sources/a.md", "no front matter\n")
    b = _page(tmp_path, "Sources/b.md", "---\ntitle: B\ndraft: false\n---\nx\n")
    sv.apply("preview", tmp_path)
    assert a.read_text().startswith("---\ndraft: true\n---\nno front matter")
    assert "draft: false" not in b.read_text() and "draft: true" in b.read_text()
