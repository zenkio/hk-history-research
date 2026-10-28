#!/usr/bin/env python3
"""Make a built site a private draft preview that search engines are told to ignore.

Owner decision 2026-10-28: the AI-draft history is shown on the site again, but not offered to search
engines until the owner decides. Run after the Quartz build and before the upload:

* every HTML page gets `<meta name="robots" content="noindex, nofollow">` in its head;
* `sitemap.xml` is removed (a sitemap invites crawling);
* `robots.txt` disallows every crawler.

robots.txt is only a request, so the meta tag is what makes compliant engines leave the pages out.
The command exits 1 if any page is left without the tag.
"""
import argparse
import re
import sys
from pathlib import Path

NOINDEX = '<meta name="robots" content="noindex, nofollow">'
ROBOTS = "# Draft preview: please do not index or collect these pages.\nUser-agent: *\nDisallow: /\n"
HEAD = re.compile(r"<head(\s[^>]*)?>", re.I)
HAS_NOINDEX = re.compile(r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*noindex', re.I)


def add_noindex(html):
    """The page with the noindex tag as the first thing in its head; unchanged when already there."""
    if HAS_NOINDEX.search(html):
        return html
    found = HEAD.search(html)
    if not found:
        return None
    return html[:found.end()] + NOINDEX + html[found.end():]


def prepare(public):
    public = Path(public)
    if public.name != "public" or not public.is_dir():
        raise ValueError("expected the built site directory named 'public'")
    missing = []
    for page in public.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        new = add_noindex(text)
        if new is None:
            missing.append(str(page.relative_to(public)))
        elif new != text:
            page.write_text(new, encoding="utf-8")
    (public / "sitemap.xml").unlink(missing_ok=True)
    (public / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("public", nargs="?", default="public")
    args = ap.parse_args(argv)
    missing = prepare(args.public)
    pages = sum(1 for _ in Path(args.public).rglob("*.html"))
    print(f"noindex added to {pages - len(missing)} of {pages} pages; sitemap removed; robots.txt disallows all")
    if missing:
        print(f"{len(missing)} pages have no <head> to tag")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
