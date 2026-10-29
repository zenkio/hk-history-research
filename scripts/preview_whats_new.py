#!/usr/bin/env python3
"""Mark what is new in a preview build and list it on a "What's new" page.

Owner request 2026-10-29: the preview shows a chosen data branch, but it was hard to see which content is new.
Run in the data checkout before the Quartz build (preview.yml only; the live deploy never runs it):

* compares the checked-out branch with the base (default `origin/main`) by `git diff --name-status base...HEAD`;
* adds tag `preview-new` or `preview-changed` to each added / modified page under `content/`
  (Quartz makes `/tags/preview-new` list them) and a callout under the front matter;
* writes `content/00_Meta/Whats_New.md` linking every such page, newest sections first.

Only the working copy of the build is touched; nothing is committed. A branch equal to main gets a page saying so.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

CONTENT = "content/"
PAGE = Path("content/00_Meta/Whats_New.md")
TAGS = re.compile(r"^tags:\s*\[(.*?)\]\s*$", re.M)
FRONT = re.compile(r"\A---\n.*?\n---\n", re.S)
TITLE = re.compile(r'^title:\s*"?(.*?)"?\s*$', re.M)
LABELS = {
    "A": ("preview-new", "New in this preview"),
    "M": ("preview-changed", "Changed in this preview"),
}


def changed_pages(base, run=subprocess.run):
    """{'A': [paths], 'M': [paths]} of markdown pages under content/ that differ from the base."""
    out = run(["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", CONTENT],
              capture_output=True, text=True, check=True).stdout
    found = {"A": [], "M": []}
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        if status in found and path.endswith(".md") and path != str(PAGE):
            found[status].append(path)
    return {k: sorted(v) for k, v in found.items()}


def title_of(text, path):
    found = TITLE.search(FRONT.match(text).group(0)) if FRONT.match(text) else None
    return (found.group(1) if found else Path(path).stem).replace('\\"', '"')


def mark(text, tag, note):
    """The page with `tag` added to its tags and `note` as a callout after the front matter."""
    front = FRONT.match(text)
    if not front:
        return text
    head, body = front.group(0), text[front.end():]
    found = TAGS.search(head)
    if found and f'"{tag}"' not in found.group(1):
        items = found.group(1).strip()
        head = head[:found.start()] + 'tags: [' + (items + ", " if items else "") + f'"{tag}"]' + head[found.end():]
    elif not found:
        head = head[:-4] + f'tags: ["{tag}"]\n---\n'
    return head + f"\n> [!info] {note}\n> Shown only in the preview. See [[00_Meta/Whats_New|What's new]].\n" + body


def link(path, title):
    slug = path[len(CONTENT):-3]
    return f"- [[{slug}|{title.replace('|', '/').replace(']', ')').replace('[', '(')}]]"


def build(base, root=Path(".")):
    changes = changed_pages(base)
    lines = ["---", 'title: "What\'s new in this preview"', 'tags: ["preview-meta"]',
             'description: "Pages added or changed in the previewed data branch compared with main."', "---", "",
             f"Compared with `{base}`. This page exists only in the preview.", ""]
    total = 0
    for status, (tag, heading) in LABELS.items():
        pages = changes[status]
        total += len(pages)
        lines += [f"## {heading} ({len(pages)})", ""]
        if not pages:
            lines += ["Nothing.", ""]
        for path in pages:
            file = root / path
            text = file.read_text(encoding="utf-8")
            file.write_text(mark(text, tag, heading), encoding="utf-8")
            lines.append(link(path, title_of(text, path)))
        lines.append("")
    if not total:
        lines += ["The previewed branch has no page differences from main.", ""]
    target = root / PAGE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args()
    changes = build(args.base)
    print(f"preview what's new: {len(changes['A'])} new, {len(changes['M'])} changed")


if __name__ == "__main__":
    sys.exit(main())
