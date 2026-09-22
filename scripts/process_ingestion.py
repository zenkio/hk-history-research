#!/usr/bin/env python3
import os
import shutil
import subprocess
import json
import re
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
ANGLES_DIR = os.path.join(PROJECT_ROOT, "content", "03_Angles")
UNVERIFIED_DIR = os.path.join(PROJECT_ROOT, "content", "04_Unverified")

# Models in order of preference (free tier first)
MODEL_TIERS = ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"]

def setup_dirs():
    for d in [TIMELINE_DIR, ANGLES_DIR, UNVERIFIED_DIR]:
        os.makedirs(d, exist_ok=True)

def call_gemini_with_fallback(content):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = f"""Analyze the following text about Hong Kong history.
Return ONLY a valid JSON object:
{{
    "title": "Short descriptive title (max 10 words)",
    "summary": "One sentence summary of the historical content",
    "tags": ["tag1", "tag2", "tag3"],
    "confidence": "high|medium|low",
    "category": "Timeline or Angles or Unverified",
    "date_mentioned": "YYYY or YYYY-MM-DD if a specific date is mentioned, else empty string"
}}
Category rules:
- Timeline: clearly dated historical events, facts about specific periods
- Angles: analysis, perspectives, photos, documents offering a viewpoint on history
- Unverified: unclear, speculative, or off-topic content

Text: {content[:3000]}
"""

    for model_name in MODEL_TIERS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print(f"Quota exceeded for {model_name}, trying next...")
                continue
            print(f"Error with {model_name}: {e}")
            continue

    raise Exception("All models exhausted or failed.")

def analyze_and_route(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Determine output filename (.md extension)
    base = os.path.basename(filepath)
    if base.endswith('.txt'):
        base = base[:-4] + '.md'
    elif not base.endswith('.md'):
        base = base + '.md'

    try:
        analysis = call_gemini_with_fallback(content)
        category = analysis.get("category", "Unverified")
        title = analysis.get("title", base)
        tags = analysis.get("tags", [])
        summary = analysis.get("summary", "")
        confidence = analysis.get("confidence", "low")
        date_mentioned = analysis.get("date_mentioned", "")

        # Build YAML frontmatter
        tags_yaml = ", ".join(f'"{t}"' for t in tags)
        frontmatter_lines = [
            "---",
            f'title: "{title}"',
            f'tags: [{tags_yaml}]',
            f'summary: "{summary}"',
            f'confidence: {confidence}',
            f'source_file: {os.path.basename(filepath)}',
            f'ingested: {datetime.now().strftime("%Y-%m-%d")}',
        ]
        if date_mentioned:
            frontmatter_lines.append(f'date: {date_mentioned}')
        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines)

        if category == "Timeline":
            dest = os.path.join(TIMELINE_DIR, base)
        elif category == "Angles":
            dest = os.path.join(ANGLES_DIR, base)
        else:
            dest = os.path.join(UNVERIFIED_DIR, base)

        with open(dest, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n\n" + content)

        os.remove(filepath)
        print(f"Routed to {category}: {base}")

    except Exception as e:
        print(f"LLM analysis failed for {base}: {e}")
        dest = os.path.join(UNVERIFIED_DIR, base)
        shutil.move(filepath, dest)

def run_git_commit():
    try:
        subprocess.run(["git", "add", "."], cwd=PROJECT_ROOT, check=True)
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
        if (f.startswith("raw_") or f.endswith(".md") or f.endswith(".txt"))
        and os.path.isfile(os.path.join(QUEUE_DIR, f))
    ]
    if files:
        for f in files:
            analyze_and_route(os.path.join(QUEUE_DIR, f))
        run_git_commit()
    else:
        print("No files to process.")
