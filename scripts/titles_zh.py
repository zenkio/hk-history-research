#!/usr/bin/env python3
"""Traditional Chinese names for the left menu (owner 2026-11-04): writes <site>/static/titles-zh.json, a map from page
or folder slug to its Chinese name. The page script (lang.inline.ts) shows the Chinese name in the menu when the site
language is Chinese and a name exists; everything without one stays English. Names only, no page text.

Usage (data checkout, after the Quartz build): titles_zh.py [public]
"""
import json
import re
import sys
from pathlib import Path

FACTS = "data/consolidated_facts"
PAGES = "05_Multi_AI"
FOLDERS = {"00_Meta": "專案資料", "01_Timeline": "時間線", "02_Entities": "人物與地方", "03_Angles": "不同角度",
           "04_Unverified": "未經核實", "05_Multi_AI": "多個 AI 綜合版本", "Guides": "指南", "Sources": "資料來源",
           "tags": "標籤"}


def build(root=Path(".")):
    titles = dict(FOLDERS)
    for path in sorted((root / FACTS).glob("*.json")):
        try:
            zh = json.loads(path.read_text(encoding="utf-8")).get("title_zh")
        except ValueError:
            continue
        if zh and (root / "content" / PAGES / f"{path.stem}.md").exists():
            titles[f"{PAGES}/{path.stem}"] = re.sub(r"[⟦⟧]", "", zh)
    return titles


def main(argv=None):
    out = Path((argv or sys.argv[1:] or ["public"])[0]) / "static"
    out.mkdir(parents=True, exist_ok=True)
    titles = build()
    (out / "titles-zh.json").write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
    print(f"[titles-zh] {len(titles)} names", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
