#!/home/zenkio/hk-history-research/venv/bin/python3
import os
import shutil
import subprocess
import time
import random
import json
from datetime import datetime
import google.generativeai as genai

# Configure API
genai.configure(api_key="AIzaSyALsBmRBxPMPs8IPeVeuGLYOHvaCgpLzYM")

PROJECT_ROOT = "/home/zenkio/hk-history-research"
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "01_Timeline")
ANGLES_DIR = os.path.join(PROJECT_ROOT, "03_Angles")
UNVERIFIED_DIR = os.path.join(QUEUE_DIR, "Unverified")

def setup_dirs():
    os.makedirs(TIMELINE_DIR, exist_ok=True)
    os.makedirs(ANGLES_DIR, exist_ok=True)
    os.makedirs(UNVERIFIED_DIR, exist_ok=True)

def call_gemini_with_backoff(content, model_name="gemini-2.5-flash-lite", max_retries=5):
    model = genai.GenerativeModel(model_name)
    prompt = f"""Analyze the following text about Hong Kong history.
    Return ONLY a JSON object with the following structure:
    {{
        "summary": "One sentence summary",
        "tags": ["tag1", "tag2"],
        "category": "Timeline", "Angles", or "Unverified"
    }}
    Text: {content}
    """
    
    base_delay = 2
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
            time.sleep(sleep_time)

def analyze_and_route(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    try:
        analysis = call_gemini_with_backoff(content, model_name="gemini-2.5-flash-lite")
        
        with open(filepath, 'r+', encoding='utf-8') as f:
            old_content = f.read()
            f.seek(0, 0)
            f.write(f"---\n{json.dumps(analysis, indent=2)}\n---\n\n{old_content}")
            
        category = analysis.get("category", "Unverified")
        if category == "Timeline":
            dest = os.path.join(TIMELINE_DIR, os.path.basename(filepath))
        elif category == "Angles":
            dest = os.path.join(ANGLES_DIR, os.path.basename(filepath))
        else:
            dest = os.path.join(UNVERIFIED_DIR, os.path.basename(filepath))
        
        shutil.move(filepath, dest)
    except Exception as e:
        print(f"LLM analysis failed: {e}")
        dest = os.path.join(UNVERIFIED_DIR, os.path.basename(filepath))
        shutil.move(filepath, dest)

def run_git_commit():
    try:
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        
        subprocess.run(["/usr/bin/git", "add", "."], cwd=PROJECT_ROOT, check=True, env=env)
        msg = f"auto(ingestion+ai-batch): synced {datetime.now().strftime('%Y-%m-%d %H:%M')} history data"
        subprocess.run(["/usr/bin/git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True, env=env)
        subprocess.run(["/usr/bin/git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True, env=env)
        print("Git push completed.")
    except Exception as e:
        print(f"Git operation failed: {e}")

if __name__ == "__main__":
    setup_dirs()
    # Process ALL files in the queue in one batch
    files = [f for f in os.listdir(QUEUE_DIR) if f.startswith("raw_") and os.path.isfile(os.path.join(QUEUE_DIR, f))]
    if files:
        for f in files:
            analyze_and_route(os.path.join(QUEUE_DIR, f))
        
        # Perform commit/push only ONCE at the end of the batch
        run_git_commit()
