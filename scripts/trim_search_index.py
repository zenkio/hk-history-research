#!/usr/bin/env python3
"""Cut the page text in Quartz's search index to its opening lines.

Quartz writes public/static/contentIndex.json with the full text of every page, so one
download would hand over the whole site as a dataset. After this step the index keeps
titles, tags, links (for the graph) and the first KEEP_CHARS of each page: search still
finds pages by title, tag and opening, and readers open the page for the rest.

Run after `npm run quartz -- build`: python3 scripts/trim_search_index.py [public]
"""
import json
import os
import re
import sys

KEEP_CHARS = 300


def trim(index, keep=KEEP_CHARS):
    for entry in index.values():
        text = re.sub(r"\s+", " ", entry.get("content") or "").strip()
        if len(text) > keep:
            text = text[:keep].rsplit(" ", 1)[0] + " …"
        entry["content"] = text
    return index


def main(public="public"):
    path = os.path.join(public, "static", "contentIndex.json")
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    before = os.path.getsize(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trim(index), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Search index trimmed: {len(index)} pages, {before // 1024} KB -> {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main(*sys.argv[1:])
