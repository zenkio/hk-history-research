#!/usr/bin/env python3
import os
import re
import json
import html
import time
import subprocess
from datetime import datetime
from gemini_pool import ModelPool, QuotaExhausted
from textutil import make_summary, yaml_quote
from photos import describe_source_photos, source_photo_section

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
    "narrative": "150-350 words of markdown in encyclopedic third-person past tense, as full paragraphs. Report everything of historical value in the source (names, dates, places, numbers, what happened and why). Start directly with the historical content. Use **bold** for key names and dates. Attribute claims to their source. No preamble. If the source is only a short teaser, write only what it actually says.",
    "context": "2-4 sentences of general historical background that helps a reader place this in Hong Kong history, from your own knowledge. Empty string if not relevant.",
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
        for key in ("source_url", "feed", "pub_date", "title", "videos", "images"):
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


PHOTO_CREDITS = {
    "Historical_Photos_HK": "Historical Photographs of Hong Kong (University of Bristol) and the donating families",
    "Gwulo_Old_HK": "their Gwulo contributors",
}
MAX_VIDEOS = 2
VIDEO_PROMPT = """Watch this video. It is linked from a Hong Kong history post titled "{title}".
Report what the video itself says and shows, so a reader who cannot watch it gets the same facts
and viewpoints. Do not add outside knowledge; if something is unclear in the video, say so.

Respond with ONLY this JSON:
{{"speaker": "Who presents it (name and role) if stated, else empty",
  "language": "Main spoken language",
  "summary": "200-400 words of markdown in English, third person, attributing claims to the speaker. Use **bold** for key names and dates.",
  "key_points": [{{"time": "mm:ss", "point": "One fact, claim, source or viewpoint stated at that moment"}}],
  "people": ["Name (中文名 if given)"],
  "years": ["1979"]}}"""


def summarize_videos(pool, video_ids, title):
    """AI summaries of the YouTube videos a post links to. Posts that are only a blurb plus a
    video would otherwise publish almost nothing."""
    out = []
    for vid in video_ids[:MAX_VIDEOS]:
        url = f"https://www.youtube.com/watch?v={vid}"
        try:
            data, model, _ = pool.generate_json("video", VIDEO_PROMPT.format(title=title), media=[url])
        except QuotaExhausted:
            raise  # keep the post queued until video quota is back
        except Exception as e:
            print(f"  video {vid} could not be summarised: {str(e)[:120]}")
            continue
        data.update(id=vid, url=url, model=model)
        out.append(data)
        print(f"  video {vid} summarised ({model})")
    return out


def seconds(stamp):
    parts = [int(p) for p in re.findall(r"\d+", str(stamp))][-3:]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def video_section(videos):
    lines = []
    for v in videos:
        lines += ["## Video", "", f"![]({v['url']})", "",
                  f"> [!info] What the video says (AI summary by {v['model']}, not a transcript)", ""]
        if v.get("speaker"):
            lines += [f"**Presenter:** {v['speaker']}" + (f" · **Language:** {v['language']}" if v.get("language") else ""), ""]
        lines += [v.get("summary", "").strip(), ""]
        points = [k for k in v.get("key_points", []) if k.get("point")]
        if points:
            lines += ["### Key points", ""]
            for k in points:
                t = seconds(k.get("time", ""))
                lines.append(f"- [{k.get('time', '')}](https://youtu.be/{v['id']}?t={t}) {k['point']}")
            lines.append("")
    return lines


def call_gemini(pool, content, url, pub_date):
    prompt = GEMINI_PROMPT.format(
        content=strip_html(content)[:6000],
        url=url,
        pub_date=pub_date
    )
    analysis = pool.generate_json("classify", prompt)[0]
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

    video_ids = [v for v in meta.get("videos", "").split(",") if v]
    videos = summarize_videos(pool, video_ids, meta.get("title", "")) if video_ids else []
    if videos:
        # Let the article be written from what the video says, not just the post's blurb.
        # Put it first so the 6,000-character input cap never cuts it off.
        body = ("VIDEO CONTENT (AI summary of the linked video):\n" + "\n\n".join(
            v.get("summary", "") for v in videos) + "\n\nPOST TEXT:\n" + body)

    image_urls = meta.get("images", "").split()
    photos = describe_source_photos(pool, image_urls, meta.get("title", ""), url) if image_urls else []
    if photos:
        body += "\n\nPHOTOS IN THE POST (AI descriptions):\n" + "\n".join(
            f"- {p.get('caption', '')}: {p.get('shows', '')} (date clues: {p.get('date_estimate', '')})" for p in photos)

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
        f"title: {yaml_quote(title)}",
    ]
    if historical_date:
        lines.append(f"date: {historical_date}")
    lines += [
        f"tags: {tags_yaml}",
        f"summary: {yaml_quote(make_summary(narrative))}",
        f"description: {yaml_quote(make_summary(narrative))}",
        f"confidence: {confidence}",
        f"source_feed: {feed_name}",
        f'source_url: "{url}"',
        f"ingested: {datetime.now().strftime('%Y-%m-%d')}",
        "---",
        "",
        narrative,
        "",
    ]
    context = analysis.get("context", "").strip()
    if context:
        lines += ["## Historical context", "", "> [!note] General background (AI, not from the source)", "", context, ""]
    lines += video_section(videos)
    lines += source_photo_section(photos, url, PHOTO_CREDITS.get(feed_name, "the original post's owners"))
    lines += [
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
