#!/home/zenkio/hk-history-research/venv/bin/python3
import os
import shutil
import subprocess
from datetime import datetime
import google.generativeai as genai


# Load API Key

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

def analyze_and_route(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # LLM Analysis
    model = genai.GenerativeModel('gemini-1.0-pro')
    prompt = f"""Analyze the following text about Hong Kong history and return a structured response:
    1. Summary (one sentence)
    2. Tags (comma separated)
    3. Category (Timeline, Angles, or Unverified)
    
    Text: {content}
    """
    
    try:
        response = model.generate_content(prompt)
        analysis = response.text
        
        # Prepend analysis to file
        with open(filepath, 'r+', encoding='utf-8') as f:
            old_content = f.read()
            f.seek(0, 0)
            f.write(f"---\n{analysis}\n---\n\n{old_content}")
            
        # Determine destination
        if "Timeline" in analysis:
            dest = os.path.join(TIMELINE_DIR, os.path.basename(filepath))
            shutil.move(filepath, dest)
        elif "Angles" in analysis:
            dest = os.path.join(ANGLES_DIR, os.path.basename(filepath))
            shutil.move(filepath, dest)
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
        msg = f"auto(ingestion+ai): synced {datetime.now().strftime('%Y-%m-%d')} history data"
        subprocess.run(["/usr/bin/git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True, env=env)
        subprocess.run(["/usr/bin/git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True, env=env)
        print("Git push completed.")
    except Exception as e:
        print(f"Git operation failed: {e}")

if __name__ == "__main__":
    setup_dirs()
    # Install dotenv if not installed in venv
    try:
        import dotenv
    except ImportError:
        subprocess.run(["/home/zenkio/hk-history-research/venv/bin/pip", "install", "python-dotenv"])
        
    files_processed = False
    for filename in os.listdir(QUEUE_DIR):
        filepath = os.path.join(QUEUE_DIR, filename)
        if os.path.isfile(filepath) and filename.startswith("raw_"):
            analyze_and_route(filepath)
            files_processed = True
    
    if files_processed:
        run_git_commit()
