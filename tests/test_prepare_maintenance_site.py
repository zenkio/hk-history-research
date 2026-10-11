from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.prepare_maintenance_site import prepare_site  # noqa: E402


class PrepareMaintenanceSiteTests(unittest.TestCase):
    def test_removes_existing_pages_feeds_and_indexes_and_keeps_domain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "public"
            output.mkdir()
            (output / "old-history.html").write_text("Unverified history", encoding="utf-8")
            (output / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
            (output / "index.html").write_text("Old homepage", encoding="utf-8")
            (output / "search-index.json").write_text('{"old":"content"}', encoding="utf-8")

            page = root / "maintenance.html"
            page.write_text(
                '<!doctype html><html><head><meta name="robots" content="noindex, nofollow"></head>'
                "<body>Temporarily unavailable</body></html>",
                encoding="utf-8",
            )
            robots = root / "robots.txt"
            robots.write_text("User-agent: *\nAllow: /\nSitemap: https://example.test/sitemap.xml\n", encoding="utf-8")
            cname = root / "CNAME"
            cname.write_text("hkhistory.zenkio.uk\n", encoding="utf-8")

            prepare_site(output, page, robots, cname)

            self.assertEqual({p.name for p in output.iterdir()}, {"index.html", "robots.txt", "CNAME"})
            self.assertIn("noindex, nofollow", (output / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Unverified history", (output / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Sitemap:", (output / "robots.txt").read_text(encoding="utf-8"))
            self.assertEqual((output / "CNAME").read_text(encoding="utf-8"), "hkhistory.zenkio.uk\n")

    def test_refuses_non_public_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "maintenance.html"
            page.write_text('<meta name="robots" content="noindex, nofollow">', encoding="utf-8")
            robots = root / "robots.txt"
            robots.write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
            cname = root / "CNAME"
            cname.write_text("hkhistory.zenkio.uk\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_site(root / "data", page, robots, cname)

    def test_refuses_page_without_noindex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "maintenance.html"
            page.write_text("<html><body>Maintenance</body></html>", encoding="utf-8")
            robots = root / "robots.txt"
            robots.write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
            cname = root / "CNAME"
            cname.write_text("hkhistory.zenkio.uk\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_site(root / "public", page, robots, cname)


if __name__ == "__main__":
    unittest.main()
