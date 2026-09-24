#!/usr/bin/env python3
"""Repair published pages. Safe to run on every pipeline run: it only touches pages that need it.

1. Summaries: older RSS pages stored `summary` as the first 120 characters of the
   body, cut mid-word. Rebuild it from whole sentences and add `description`,
   which Quartz shows in search results and link previews.
2. Thin pages and missed videos: every RSS page is checked against its source
   once (scripts/repaired_urls.json). It goes back into the ingestion queue if
   our page is only a feed teaser ("We'll …") or under 60 words, or if the
   source post embeds a YouTube video we have not summarised yet, so
   process_ingestion.py rewrites it from the full article and the video.
3. Duplicates: `name_123456.md` copies of `name.md` with the same title are removed.

Usage: python3 scripts/repair_content.py [--commit]
"""
import os
import re
import sys
import json
import glob
import argparse
import subprocess
from datetime import datetime

from textutil import make_summary, plain, yaml_quote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(PROJECT_ROOT, "content")
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
REPAIRED_FILE = os.path.join(PROJECT_ROOT, "scripts", "repaired_urls.json")
RSS_DIRS = ("01_Timeline", "03_Angles", "04_Unverified")
MIN_WORDS = 60


def split_page(text):
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    return parts[1], parts[2]


def get_field(fm, key):
    m = re.search(rf"^{key}: *(.*)$", fm, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else None


def set_field(fm, key, value, after="summary"):
    line = f"{key}: {yaml_quote(value)}"
    if re.search(rf"^{key}:", fm, re.MULTILINE):
        return re.sub(rf"^{key}:.*$", lambda _: line, fm, count=1, flags=re.MULTILINE)
    if re.search(rf"^{after}:", fm, re.MULTILINE):
        return re.sub(rf"^({after}:.*)$", lambda m: m.group(1) + "\n" + line, fm, count=1, flags=re.MULTILINE)
    return fm.rstrip("\n") + "\n" + line + "\n"


def article_text(body):
    """Body without the source line, callouts and appended sections."""
    body = body.split("\n> Source:")[0]
    body = re.split(r"\n## ", body)[0]
    return "\n".join(l for l in body.splitlines() if not l.startswith(">")).strip()


def is_rss(fm):
    return get_field(fm, "source_url") is not None


def fix_summaries(pages):
    changed = 0
    for path, fm, body in pages:
        if fm is None:
            continue
        new = fm
        summary = get_field(fm, "summary") or ""
        text = plain(article_text(body))
        # A summary that is just the first N characters of the body is the old truncation.
        if is_rss(fm) and text and summary and text.startswith(plain(summary)[:60]) and not re.search(r"[.!?。]$", summary):
            summary = make_summary(article_text(body))
            new = set_field(new, "summary", summary, after="tags")
        if not get_field(new, "description") and (summary or text):
            new = set_field(new, "description", make_summary(summary or text))
        if new != fm:
            with open(path, "w", encoding="utf-8") as f:
                f.write("---" + new + "---" + body)
            changed += 1
    return changed


def remove_duplicates(pages):
    removed = 0
    titles = {p: get_field(fm, "title") for p, fm, _ in pages if fm}
    for path in list(titles):
        m = re.match(r"(.*)_\d{6}\.md$", path)
        if m and os.path.exists(m.group(1) + ".md") and titles.get(m.group(1) + ".md") == titles[path]:
            os.remove(path)
            removed += 1
    return removed


def requeue_thin(pages):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fetch_sources import fetch_article

    tried = {}
    if os.path.exists(REPAIRED_FILE):
        with open(REPAIRED_FILE, encoding="utf-8") as f:
            tried = json.load(f)
    requeued = 0
    for path, fm, body in pages:
        if fm is None or not os.path.exists(path) or not is_rss(fm):
            continue
        url = get_field(fm, "source_url")
        text = article_text(body)
        thin = len(re.findall(r"\w+", text)) < MIN_WORDS or re.search(r"(…|\.\.\.|\[&#8230;\])\s*$", text)
        if not url or url in tried or "\n## Video" in body:
            continue
        tried[url] = datetime.now().isoformat()
        full, videos, images = fetch_article(url)
        if not thin and not videos:
            continue
        if (not full or len(full) < 400) and not videos:
            print(f"[repair] could not fetch more than a teaser for {url}")
            continue
        os.makedirs(QUEUE_DIR, exist_ok=True)
        name = "raw_repair_" + os.path.basename(path)
        with open(os.path.join(QUEUE_DIR, name), "w", encoding="utf-8") as f:
            f.write(f"source_url: {url}\nfeed: {get_field(fm, 'source_feed') or 'unknown'}\n"
                    f"pub_date: {get_field(fm, 'date') or ''}\ntitle: {get_field(fm, 'title')}\n"
                    f"replaces: {os.path.relpath(path, PROJECT_ROOT)}\n"
                    + (f"videos: {','.join(videos)}\n" if videos else "")
                    + (f"images: {' '.join(images)}\n" if images else "") + f"\n{full or ''}\n")
        # The old page stays live until process_ingestion.py writes its replacement.
        requeued += 1
        why = f"{len(videos)} video(s)" if videos else "thin page"
        print(f"[repair] re-queued {os.path.relpath(path, CONTENT)} ({why})")
    with open(REPAIRED_FILE, "w", encoding="utf-8") as f:
        json.dump(tried, f, indent=2, ensure_ascii=False)
    return requeued


def load_pages():
    pages = []
    for path in glob.glob(os.path.join(CONTENT, "**", "*.md"), recursive=True):
        with open(path, encoding="utf-8") as f:
            fm, body = split_page(f.read())
        pages.append((path, fm, body))
    return pages


def git_commit():
    paths = ["content", "04_Ingestion_Queue", "scripts/repaired_urls.json"]
    subprocess.run(["git", "add", "-A", "--"] + [p for p in paths if os.path.exists(os.path.join(PROJECT_ROOT, p))],
                   cwd=PROJECT_ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", "auto(repair): fix truncated summaries and thin pages"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="commit and push the repairs")
    ap.add_argument("--no-fetch", action="store_true", help="skip re-fetching thin pages")
    args = ap.parse_args()
    pages = load_pages()
    removed = remove_duplicates(pages)
    pages = [p for p in pages if os.path.exists(p[0])]
    requeued = 0 if args.no_fetch else requeue_thin(pages)
    pages = [p for p in pages if os.path.exists(p[0])]
    fixed = fix_summaries(load_pages())
    print(f"[repair] removed {removed} duplicates, re-queued {requeued} thin pages, fixed {fixed} summaries")
    if args.commit:
        git_commit()
