#!/usr/bin/env python3
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")

# 預設監控嘅 RSS 史料與新聞來源 Feed
FEEDS = [
    {"name": "UK_National_Archives", "url": "https://www.nationalarchives.gov.uk/rss/news.xml"},
    {"name": "HK_Memory_Project", "url": "https://www.hkmemory.hk/rss/updates.xml"}
]

def fetch_rss():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    print(f"[{datetime.now().isoformat()}] Starting source ingestion...")

    for feed in FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)

                # 提取前 3 則最新項目
                for item in root.findall('.//item')[:3]:
                    title = item.find('title').text if item.find('title') is not None else "Untitled"
                    link = item.find('link').text if item.find('link') is not None else ""
                    desc = item.find('description').text if item.find('description') is not None else ""

                    filename = f"raw_{feed['name']}_{int(datetime.now().timestamp())}.txt"
                    filepath = os.path.join(QUEUE_DIR, filename)

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Title: {title}\nSource: {link}\nFeed: {feed['name']}\n\nContent:\n{desc}\n")

                    print(f"Saved: {filename}")
        except Exception as e:
            print(f"Skipping {feed['name']} due to error or offline feed: {e}")

if __name__ == "__main__":
    fetch_rss()
