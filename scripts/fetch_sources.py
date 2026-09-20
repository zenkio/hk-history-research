#!/home/zenkio/hk-history-research/venv/bin/python3
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
import feedparser

PROJECT_ROOT = "/home/zenkio/hk-history-research"
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")

# RSS/Atom Feeds from Registry
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
            
            # 提取前 5 則最新項目
            for entry in d.entries[:5]:
                title = entry.get('title', 'Untitled')
                link = entry.get('link', '')
                desc = entry.get('description', '')
                
                filename = f"raw_{feed['name']}_{int(datetime.now().timestamp())}_{hash(title)}.txt"
                filepath = os.path.join(QUEUE_DIR, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"Title: {title}\nSource: {link}\nFeed: {feed['name']}\n\nContent:\n{desc}\n")
                
                print(f"Saved: {filename}")
        except Exception as e:
            print(f"Skipping {feed['name']} due to error: {e}")

if __name__ == "__main__":
    # Ensure feedparser is installed in venv
    try:
        import feedparser
    except ImportError:
        import subprocess
        subprocess.run(["/home/zenkio/hk-history-research/venv/bin/pip", "install", "feedparser"])
    fetch_rss()
