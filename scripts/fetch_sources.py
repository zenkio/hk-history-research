#!/usr/bin/env python3
import os
import feedparser
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")

FEEDS = [
    {"name": "HK_History_Centre", "url": "https://www.hkhistory.net/feed/"},
    {"name": "Historical_Photos_HK", "url": "https://blog.hphkbristol.net/feed/"},
    {"name": "Gwulo_Old_HK", "url": "https://gwulo.com/rss.xml"},
    {"name": "Industrial_History_HK", "url": "https://industrialhistoryhk.org/feed/"},
    {"name": "Battle_For_HK", "url": "http://battleforhongkong.blogspot.com/feeds/posts/default"}
]

def fetch_rss():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    print(f"[{datetime.now().isoformat()}] Starting source ingestion...")

    for feed in FEEDS:
        try:
            d = feedparser.parse(feed["url"])
            for entry in d.entries[:5]:
                title = entry.get('title', 'Untitled')
                link = entry.get('link', '')
                desc = entry.get('description', '')
                pub_date = entry.get('published', datetime.now().isoformat())

                filename = f"raw_{feed['name']}_{int(datetime.now().timestamp())}_{hash(title)}.md"
                filepath = os.path.join(QUEUE_DIR, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"title: {title}\nsource: {link}\nfeed: {feed['name']}\ndate: {pub_date}\n\n{desc}\n")

                print(f"Saved: {filename}")
        except Exception as e:
            print(f"Skipping {feed['name']} due to error: {e}")

if __name__ == "__main__":
    fetch_rss()
