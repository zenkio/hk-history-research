import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preview_noindex as pn


def site(tmp_path):
    public = tmp_path / "public"
    (public / "sub").mkdir(parents=True)
    (public / "index.html").write_text("<!doctype html><html><head><title>x</title></head><body>a</body></html>")
    (public / "sub" / "p.html").write_text('<html><HEAD lang="en"><meta charset="utf-8"></HEAD><body>b</body></html>')
    (public / "sitemap.xml").write_text("<urlset/>")
    (public / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://x/sitemap.xml\n")
    (public / "CNAME").write_text("hkhistory.zenkio.uk\n")
    return public


def test_every_page_gets_noindex_sitemap_goes_and_robots_disallows_all(tmp_path):
    public = site(tmp_path)
    assert pn.prepare(public) == []
    for page in public.rglob("*.html"):
        assert pn.NOINDEX in page.read_text()
    assert not (public / "sitemap.xml").exists()
    robots = (public / "robots.txt").read_text()
    assert "Disallow: /" in robots and "Allow: /" not in robots and "Sitemap" not in robots
    assert (public / "CNAME").read_text() == "hkhistory.zenkio.uk\n"


def test_running_twice_does_not_duplicate_the_tag(tmp_path):
    public = site(tmp_path)
    pn.prepare(public)
    pn.prepare(public)
    assert (public / "index.html").read_text().count("noindex") == 1


def test_a_page_without_head_is_reported_and_fails_the_command(tmp_path):
    public = site(tmp_path)
    (public / "bad.html").write_text("<p>no head</p>")
    assert pn.prepare(public) == ["bad.html"]
    assert pn.main([str(public)]) == 1


def test_refuses_a_directory_not_named_public(tmp_path):
    (tmp_path / "other").mkdir()
    with pytest.raises(ValueError):
        pn.prepare(tmp_path / "other")
