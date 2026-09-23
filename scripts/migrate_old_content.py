#!/usr/bin/env python3
"""One-time migration: convert broken .txt files in content/ to proper .md with YAML frontmatter."""
import os
import re
import json
import html

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = [
    os.path.join(PROJECT_ROOT, "content", "01_Timeline"),
    os.path.join(PROJECT_ROOT, "content", "03_Angles"),
]


def strip_html(text):
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_old_file(content):
    """Parse the old JSON-in-YAML + plain-body format."""
    meta = {}
    # Extract JSON block between first pair of ---
    json_match = re.search(r'---\s*(\{.*?\})\s*---', content, re.DOTALL)
    if json_match:
        try:
            meta = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Extract plain-text fields from body
    body_text = content
    if json_match:
        body_text = content[json_match.end():]

    title = ""
    source_url = ""
    feed_name = ""
    body_lines = []
    in_content = False

    for line in body_text.splitlines():
        if line.startswith("Title:"):
            title = line[6:].strip()
        elif line.startswith("Source:"):
            source_url = line[7:].strip()
        elif line.startswith("Feed:"):
            feed_name = line[5:].strip()
        elif line.startswith("Content:"):
            in_content = True
        elif in_content:
            body_lines.append(line)

    raw_body = "\n".join(body_lines).strip()
    clean_body = strip_html(raw_body)

    return {
        "title": strip_html(title or meta.get("summary", "Untitled"))[:60],
        "source_url": source_url,
        "feed_name": feed_name,
        "summary": meta.get("summary", ""),
        "tags": meta.get("tags", []),
        "category": meta.get("category", "Unverified"),
        "body": clean_body,
    }


def make_slug(text, max_len=80):
    slug = text.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug.strip('-')[:max_len] or "article"


def migrate_file(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    parsed = parse_old_file(content)
    slug = make_slug(parsed["title"])
    md_path = os.path.join(os.path.dirname(txt_path), slug + ".md")

    # Avoid clobbering existing .md
    if os.path.exists(md_path):
        h = str(abs(hash(txt_path)))[:6]
        md_path = os.path.join(os.path.dirname(txt_path), f"{slug}_{h}.md")

    tags = parsed["tags"]
    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    lines = [
        "---",
        f'title: "{parsed["title"]}"',
        f"tags: {tags_yaml}",
    ]
    if parsed["summary"]:
        lines.append(f'summary: "{parsed["summary"][:120].replace(chr(34), chr(39))}"')
    lines += [
        "confidence: medium",
        f"source_feed: {parsed['feed_name']}",
        f'source_url: "{parsed["source_url"]}"',
        "ingested: 2026-09-23",
        "---",
        "",
        parsed["body"] or parsed["summary"],
    ]
    if parsed["source_url"]:
        lines += ["", f"> Source: [{parsed['feed_name']}]({parsed['source_url']})"]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    os.remove(txt_path)
    print(f"Migrated: {os.path.basename(txt_path)} → {os.path.basename(md_path)}")


if __name__ == "__main__":
    total = 0
    for d in DIRS:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if fname.endswith(".txt"):
                migrate_file(os.path.join(d, fname))
                total += 1
    print(f"\nMigrated {total} files.")
