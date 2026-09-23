#!/usr/bin/env python3
import os
import re
import json
import urllib.request
import urllib.error
import feedparser
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
SEEN_URLS_FILE = os.path.join(PROJECT_ROOT, "scripts", "seen_urls.json")

FEEDS = [
    {"name": "HK_History_Centre", "url": "https://www.hkhistory.net/feed/"},
    {"name": "Historical_Photos_HK", "url": "https://blog.hphkbristol.net/feed/"},
    {"name": "Gwulo_Old_HK", "url": "https://gwulo.com/rss.xml"},
    {"name": "Industrial_History_HK", "url": "https://industrialhistoryhk.org/feed/"},
    {"name": "Battle_For_HK", "url": "http://battleforhongkong.blogspot.com/feeds/posts/default"}
]


def load_seen_urls():
    if os.path.exists(SEEN_URLS_FILE):
        with open(SEEN_URLS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen_urls(seen):
    with open(SEEN_URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def fetch_article_text(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Strip HTML tags and collapse whitespace
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-z#0-9]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:8000]
    except Exception:
        return None


def make_slug(text, max_len=60):
    slug = text.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')[:max_len]
    return slug or "article"


def fetch_rss():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    seen = load_seen_urls()
    new_count = 0
    print(f"[{datetime.now().isoformat()}] Starting source ingestion...")

    for feed in FEEDS:
        try:
            d = feedparser.parse(feed["url"])
            for entry in d.entries[:20]:
                link = entry.get('link', '')
                if not link:
                    continue
                if link in seen:
                    continue  # already processed

                title = entry.get('title', 'Untitled')
                pub_date = entry.get('published', datetime.now().isoformat())
                rss_desc = entry.get('summary', entry.get('description', ''))
                # Strip HTML from RSS description as fallback
                rss_text = re.sub(r'<[^>]+>', ' ', rss_desc)
                rss_text = re.sub(r'\s+', ' ', rss_text).strip()

                # Try to fetch full article; fall back to RSS description
                full_text = fetch_article_text(link) or rss_text

                slug = make_slug(title)
                filename = f"raw_{feed['name']}_{slug}.md"
                filepath = os.path.join(QUEUE_DIR, filename)

                # If slug collision, add hash suffix
                if os.path.exists(filepath):
                    h = str(abs(hash(link)))[:6]
                    filename = f"raw_{feed['name']}_{slug}_{h}.md"
                    filepath = os.path.join(QUEUE_DIR, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"source_url: {link}\n")
                    f.write(f"feed: {feed['name']}\n")
                    f.write(f"pub_date: {pub_date}\n")
                    f.write(f"title: {title}\n\n")
                    f.write(full_text + "\n")

                seen[link] = datetime.now().isoformat()
                new_count += 1
                print(f"Saved: {filename}")

        except Exception as e:
            print(f"Skipping {feed['name']}: {e}")

    save_seen_urls(seen)
    print(f"Done. {new_count} new articles fetched.")


if __name__ == "__main__":
    fetch_rss()
