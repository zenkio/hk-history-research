#!/usr/bin/env python3
"""Hide sections that must not be shown (owner 2026-11-06), by marking their pages `draft: true` in the build copy.

Run in the data checkout before the Quartz build (the build removes draft pages; nothing is committed):

* `Sources/` (the source registry): hidden everywhere. We do not use it in the research yet, and showing it would
  suggest we do. Only the models and sources really used are shown.
* `04_Unverified/`: hidden everywhere. It is a backlog for the pipeline, not reader content.
* `00_Meta/` (how we research; metadata and methods): hidden in production, shown in the preview.

Usage: site_visibility.py --mode preview|production
"""
import argparse
import re
import sys
from pathlib import Path

CONTENT = Path("content")
ALWAYS_HIDDEN = ("Sources", "04_Unverified")
PREVIEW_ONLY = ("00_Meta",)
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def hide(page):
    """Add `draft: true` to the page's front matter (a page without any gets one). Returns True if changed."""
    text = page.read_text(encoding="utf-8")
    match = FRONT.match(text)
    if match is None:
        page.write_text(f"---\ndraft: true\n---\n{text}", encoding="utf-8")
        return True
    if re.search(r"^draft:\s*true\s*$", match.group(1), re.M):
        return False
    body = re.sub(r"^draft:.*\n?", "", match.group(1) + "\n", flags=re.M).rstrip("\n")
    page.write_text(f"---\n{body}\ndraft: true\n---\n{text[match.end():]}", encoding="utf-8")
    return True


def apply(mode, root=Path(".")):
    if mode not in ("preview", "production"):
        raise SystemExit(f"unknown mode: {mode}")
    folders = ALWAYS_HIDDEN + (PREVIEW_ONLY if mode == "production" else ())
    changed = 0
    for folder in folders:
        for page in sorted((root / CONTENT / folder).rglob("*.md")):
            changed += hide(page)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["preview", "production"])
    args = parser.parse_args(argv)
    print(f"[visibility] {apply(args.mode)} page(s) hidden ({args.mode})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
