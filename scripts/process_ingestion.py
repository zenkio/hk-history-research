#!/usr/bin/env python3
import os
import re
import json
import html
import time
import subprocess
from datetime import datetime
from gemini_pool import ModelPool, QuotaExhausted

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
ANGLES_DIR = os.path.join(PROJECT_ROOT, "content", "03_Angles")
UNVERIFIED_DIR = os.path.join(PROJECT_ROOT, "content", "04_Unverified")

GEMINI_PROMPT = """You are a Hong Kong history researcher. Analyze this source text and respond with ONLY a JSON object.

SOURCE TEXT:
{content}

SOURCE URL: {url}
PUBLICATION DATE: {pub_date}

Return exactly this JSON structure:
{{
    "title": "Concise title max 10 words describing the historical topic or event",
    "narrative": "3-6 sentences in encyclopedic third-person past tense. Start directly with the historical content. Use **bold** for key names and dates. Attribute claims to their source. No preamble.",
    "historical_date": "When the described event happened (not when published). YYYY-MM-DD if specific date known, YYYY if only year known, YYYY/YYYY for a range like 1941/1945, empty string if cannot determine.",
    "year_tags": ["1941", "1942"],
    "tags": ["lowercase-hyphenated-topic", "max-6-tags"],
    "confidence": "high if academic/archive/official source, medium if journalism/blog, low if speculative or unclear",
    "category": "Timeline if this is about a specific historical event or period | Angles if this is analysis, photos, or a perspective piece | Unverified if off-topic or insufficient historical content"
}}

Tag rules: lowercase-hyphenated (e.g. wwii, handover-1997, colonial-administration, japanese-occupation).
Year tags: include all years prominently mentioned as plain strings like "1841", "1997".
If the source has no real historical content, set category to Unverified."""


def setup_dirs():
    for d in [TIMELINE_DIR, ANGLES_DIR, UNVERIFIED_DIR]:
        os.makedirs(d, exist_ok=True)


def strip_html(text):
    text = html.unescape(text)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_header(content):
    """Extract source_url, feed, pub_date, title from the plain-text header written by fetch_sources.py."""
    meta = {}
    for line in content.splitlines():
        for key in ("source_url", "feed", "pub_date", "title"):
            if line.startswith(f"{key}:"):
                meta[key] = line[len(key) + 1:].strip()
    return meta


def normalize_date(d):
    if not d:
        return ""
    if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        return d
    if re.match(r'^\d{4}$', d):
        return f"{d}-01-01"
    m = re.match(r'^(\d{4})/\d{4}$', d)
    if m:
        return f"{m.group(1)}-01-01"
    return ""


def make_slug(text, max_len=80):
    slug = text.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')[:max_len]
    return slug or "article"


def call_gemini(pool, content, url, pub_date):
    prompt = GEMINI_PROMPT.format(
        content=strip_html(content)[:6000],
        url=url,
        pub_date=pub_date
    )
    analysis, _ = pool.generate_json("classify", prompt)
    return analysis


def dest_path(category, slug):
    base = f"{slug}.md"
    if category == "Timeline":
        d = TIMELINE_DIR
    elif category == "Angles":
        d = ANGLES_DIR
    else:
        d = UNVERIFIED_DIR
    path = os.path.join(d, base)
    if os.path.exists(path):
        h = str(abs(hash(slug + str(time.time()))))[:6]
        path = os.path.join(d, f"{slug}_{h}.md")
    return path


def analyze_and_route(pool, filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    meta = parse_header(raw)
    url = meta.get("source_url", "")
    pub_date = meta.get("pub_date", "")
    feed_name = meta.get("feed", "")

    # Body is everything after the blank line following headers
    body_start = raw.find("\n\n")
    body = raw[body_start:].strip() if body_start != -1 else raw

    try:
        analysis = call_gemini(pool, body, url, pub_date)
    except QuotaExhausted:
        raise  # leave the file queued for the next run
    except Exception as e:
        print(f"LLM failed for {os.path.basename(filepath)}: {e}")
        os.replace(filepath, os.path.join(UNVERIFIED_DIR, os.path.basename(filepath)))
        return

    title = analysis.get("title", meta.get("title", "Untitled"))
    narrative = analysis.get("narrative", "")
    historical_date = normalize_date(analysis.get("historical_date", ""))
    year_tags = analysis.get("year_tags", [])
    topic_tags = analysis.get("tags", [])
    all_tags = sorted(set(topic_tags + year_tags))
    confidence = analysis.get("confidence", "low")
    category = analysis.get("category", "Unverified")
    slug = make_slug(title)
    output_path = dest_path(category, slug)

    tags_yaml = "[" + ", ".join(f'"{t}"' for t in all_tags) + "]"
    lines = [
        "---",
        f'title: "{title}"',
    ]
    if historical_date:
        lines.append(f"date: {historical_date}")
    lines += [
        f"tags: {tags_yaml}",
        f'summary: "{narrative[:120].replace(chr(34), chr(39))}"',
        f"confidence: {confidence}",
        f"source_feed: {feed_name}",
        f'source_url: "{url}"',
        f"ingested: {datetime.now().strftime('%Y-%m-%d')}",
        "---",
        "",
        narrative,
        "",
        f"> Source: [{feed_name}]({url})",
    ]
    output = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    os.remove(filepath)
    print(f"[{category}] {title[:60]} → {os.path.basename(output_path)}")


def run_git_commit():
    try:
        # The queue is tracked too, so files left over when quota runs out
        # survive to the next CI run instead of vanishing with the runner.
        paths = ["content/", "scripts/seen_urls.json", "scripts/quota_state.json", "04_Ingestion_Queue/"]
        subprocess.run(
            ["git", "add", "-A", "--"] + [p for p in paths if os.path.exists(os.path.join(PROJECT_ROOT, p))],
            cwd=PROJECT_ROOT, check=True
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            print("Nothing new to commit.")
            return
        msg = f"auto(ingestion+ai-batch): synced {datetime.now().strftime('%Y-%m-%d %H:%M')} history data"
        subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)
        print("Git push completed.")
    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")


if __name__ == "__main__":
    setup_dirs()
    files = [
        f for f in os.listdir(QUEUE_DIR)
        if os.path.isfile(os.path.join(QUEUE_DIR, f))
        and (f.endswith(".md") or f.endswith(".txt"))
    ]
    if not files:
        print("No files to process.")
    else:
        print(f"Processing {len(files)} files...")
        pool = ModelPool()
        try:
            for f in files:
                analyze_and_route(pool, os.path.join(QUEUE_DIR, f))
        except QuotaExhausted as e:
            print(f"Stopping early, remaining files stay queued: {e}")
        print(f"Quota used today: {pool.summary()}")
        run_git_commit()
