#!/usr/bin/env python3
"""Traditional Chinese (Hong Kong) versions of the drafted history pages.

Each English page under content/01_Timeline/<NN-era>/ and content/02_Entities/
gets a sibling under content/zh/ with the same relative path, and the two pages
link to each other. Era overviews go first, then events in plan order, then
people and places by how often they are mentioned. Progress is kept in
seed_plan.json under "translations" so runs resume where they stopped.

Called from seed_history.py: each run first spends the OpenRouter free budget
(Chinese-native models), and once the drafting plan is complete, idle Gemma
capacity continues the work. Standalone: python3 scripts/translate.py --limit N
"""
import os
import re
import sys
import time
import argparse
from datetime import datetime

from gemini_pool import QuotaExhausted
from textutil import make_summary, yaml_quote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(PROJECT_ROOT, "content")
ZH_DIR = os.path.join(CONTENT, "zh")
LANG_LINK = "🌐"

PROMPT = """Translate this page of a Hong Kong history website into Traditional Chinese
as written in Hong Kong (繁體中文，香港用語及譯名).

Rules:
- Keep the markdown structure: headings, lists, **bold**, and callout lines such as "> [!warning] ..." (keep the "[!warning]" marker itself in English).
- In wikilinks [[target|label]] keep the target exactly as is and translate only the label.
- Use the established Hong Kong Chinese names for people, places, laws and institutions.
- Translate faithfully. Do not add, remove or soften content.

Reply in exactly this format and nothing else:
TITLE: <translated title>
SUMMARY: <one-sentence summary in Chinese>
===
<translated markdown body>

PAGE TITLE: {title}

PAGE BODY:
{body}"""


def split_page(text):
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def field(fm, key):
    m = re.search(rf"^{key}: *(.*)$", fm, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else ""


def parse_reply(text):
    text = re.sub(r"^```\w*\n|\n```$", "", (text or "").strip())
    m = re.match(r"\s*TITLE:\s*(.+?)\s*\n\s*SUMMARY:\s*(.+?)\s*\n\s*={3,}\s*\n(.*)", text, re.DOTALL)
    if not m or len(m.group(3).strip()) < 50:
        raise ValueError("reply not in TITLE/SUMMARY/=== format")
    body = m.group(3).strip()
    # A model that answers in English or Simplified defeats the purpose.
    if len(re.findall(r"[一-鿿]", body)) < len(body) * 0.15:
        raise ValueError("reply is not mostly Chinese")
    return {"title": m.group(1).strip(), "summary": m.group(2).strip(), "body": body}


def candidate_pages(plan):
    """Relative paths under content/, most important first."""
    pages = [os.path.join("01_Timeline", slug, "index.md") for slug in plan.get("eras", {})]
    pages += [os.path.join("01_Timeline", e["file"]) for e in plan.get("events", []) if e.get("file")]
    ents = sorted((e for e in plan.get("entities", {}).values() if e.get("file")),
                  key=lambda e: -len(e.get("mentions", [])))
    pages += [os.path.join("02_Entities", e["file"]) for e in ents]
    done = plan.setdefault("translations", {})
    return [p for p in pages if p not in done and os.path.exists(os.path.join(CONTENT, p))]


def link_target(rel):
    return rel[:-3] if rel.endswith(".md") else rel


def add_english_link(rel):
    """Put a link to the Chinese page right under the English page's AI-draft callout."""
    path = os.path.join(CONTENT, rel)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if f"[[zh/{link_target(rel)}|" in text:
        return
    line = f"{LANG_LINK} [[zh/{link_target(rel)}|中文版]]\n\n"
    fm, body = split_page(text)
    m = re.search(r"\n> \[!warning\][^\n]*\n(?:>[^\n]*\n)*\n", body)
    body = body[:m.end()] + line + body[m.end():] if m else "\n" + line + body.lstrip("\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---" + fm + "---" + body)


def translate_one(pool, rel, only=None):
    with open(os.path.join(CONTENT, rel), encoding="utf-8") as f:
        fm, body = split_page(f.read())
    title = field(fm, "title")
    body = re.sub(rf"^{LANG_LINK} \[\[zh/[^\n]*\n\n?", "", body.strip(), flags=re.MULTILINE)
    data, model, _ = pool.generate_text("translate", PROMPT.format(title=title, body=body),
                                        parse_reply, only=only)
    tags = re.search(r"^tags: *(.*)$", fm, re.MULTILINE)
    lines = ["---",
             f"title: {yaml_quote(data['title'])}",
             f"title_en: {yaml_quote(title)}"]
    for key in ("date", "year"):
        if field(fm, key):
            lines.append(f"{key}: {field(fm, key)}")
    lines += [f"tags: {tags.group(1) if tags else '[]'}",
              f"summary: {yaml_quote(data['summary'])}",
              f"description: {yaml_quote(make_summary(data['summary']))}",
              "lang: zh-Hant",
              f"confidence: {field(fm, 'confidence') or 'ai-draft'}",
              f"translation_of: {yaml_quote(rel)}",
              f"translated_by: {model}",
              f"translated: {datetime.now().strftime('%Y-%m-%d')}",
              "---", "",
              f"{LANG_LINK} [[{link_target(rel)}|English]]", "",
              "> [!note] 機器翻譯",
              "> 本頁由 AI 從英文版翻譯，譯名及內容未經人手校對。", "",
              data["body"]]
    out = os.path.join(ZH_DIR, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    add_english_link(rel)
    return model


def translate_batch(pool, plan, deadline, only=None, limit=None, save=None):
    """Translate pending pages until the budget of the allowed models or the time runs out."""
    done = 0
    for rel in candidate_pages(plan):
        if time.time() > deadline or (limit is not None and done >= limit):
            break
        try:
            model = translate_one(pool, rel, only=only)
        except QuotaExhausted:
            break
        except Exception as e:
            print(f"[translate] {rel} failed: {str(e)[:160]}")
            plan["translations"][rel] = "failed"
            continue
        plan["translations"][rel] = datetime.now().strftime("%Y-%m-%d")
        done += 1
        print(f"[translate] zh/{rel} ({model})")
        if save:
            save(plan)
    return done


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gemini_pool import ModelPool
    from seed_history import load_plan, save_plan
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--minutes", type=float, default=30)
    args = ap.parse_args()
    plan = load_plan()
    n = translate_batch(ModelPool(), plan, time.time() + args.minutes * 60, limit=args.limit, save=save_plan)
    print(f"Translated {n} pages")
