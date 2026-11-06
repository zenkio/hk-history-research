#!/usr/bin/env python3
"""Order of the left menu (owner 2026-11-06): writes <site>/static/menu-order.json for the page script (lang.inline.ts).

Top level: What's New, Timeline, People, Places, then the rest (00_Meta, the preview-only methods section, last).
People and places are not A-Z: the most important come first. Importance = the page's front matter `importance`
(a score an AI will give later, higher first) when it has one, otherwise how many other pages link to it.
Names only, no page text. Slugs are lower case, as Quartz writes them.

Usage (data checkout, after the Quartz build): menu_order.py [public]
"""
import json
import re
import sys
from pathlib import Path

CONTENT = "content"
TOP = ["whats_new", "01_timeline", "02_entities", "05_multi_ai", "03_angles"]
LAST = ["00_meta"]
RANKED = {"02_entities/people": "02_Entities/People", "02_entities/places": "02_Entities/Places"}
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MD_LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)#\s]+)")
IMPORTANCE = re.compile(r"^importance:\s*([0-9.]+)\s*$", re.M)


def slug_of(rel):
    return re.sub(r"\s+", "-", rel.removesuffix(".md").strip()).lower()


def inbound_links(root):
    """{slug: number of other pages linking to it}; a page linking twice to the same target counts once."""
    pages = {slug_of(str(p.relative_to(root / CONTENT))): p for p in (root / CONTENT).rglob("*.md")}
    by_name = {}
    for slug in pages:
        by_name.setdefault(slug.rsplit("/", 1)[-1], []).append(slug)
    counts = {slug: 0 for slug in pages}
    for slug, page in pages.items():
        text = page.read_text(encoding="utf-8", errors="replace")
        targets = {t.strip() for t in LINK.findall(text)} | {t.strip() for t in MD_LINK.findall(text)}
        hit = set()
        for target in targets:
            key = slug_of(target.removesuffix(".html").lstrip("/"))
            if key in pages:
                hit.add(key)
            elif key.rsplit("/", 1)[-1] in by_name and len(by_name[key.rsplit("/", 1)[-1]]) == 1:
                hit.add(by_name[key.rsplit("/", 1)[-1]][0])
        for target in hit - {slug}:
            counts[target] += 1
    return counts, pages


def build(root=Path(".")):
    counts, pages = inbound_links(root)
    order = {}
    for parent, folder in RANKED.items():
        mine = [s for s in pages if s.startswith(parent + "/") and s.count("/") == parent.count("/") + 1]

        def key(slug):
            found = IMPORTANCE.search(pages[slug].read_text(encoding="utf-8", errors="replace")[:2000])
            return (0 if found else 1, -float(found.group(1)) if found else 0, -counts[slug], slug)
        order[parent] = sorted(mine, key=key)
    order["02_entities"] = ["02_entities/people", "02_entities/places"]
    top = {s.split("/", 1)[0] for s in pages}
    rest = sorted(top - set(TOP) - set(LAST))
    order[""] = [s for s in TOP if s in top] + rest + [s for s in LAST if s in top]
    return {"order": order, "links": {s: c for s, c in counts.items() if s.startswith("02_entities/")}}


def main(argv=None):
    out = Path((argv or sys.argv[1:] or ["public"])[0]) / "static"
    out.mkdir(parents=True, exist_ok=True)
    data = build()
    (out / "menu-order.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[menu-order] top level: {', '.join(data['order'][''])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
