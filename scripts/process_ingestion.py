#!/usr/bin/env python3
import os
import shutil
import subprocess
from datetime import datetime

PROJECT_ROOT = "/home/zenkio/hk-history-research"
QUEUE_DIR = os.path.join(PROJECT_ROOT, "04_Ingestion_Queue")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "01_Timeline")
ANGLES_DIR = os.path.join(PROJECT_ROOT, "03_Angles")
UNVERIFIED_DIR = os.path.join(QUEUE_DIR, "Unverified")

def setup_dirs():
    os.makedirs(TIMELINE_DIR, exist_ok=True)
    os.makedirs(ANGLES_DIR, exist_ok=True)
    os.makedirs(UNVERIFIED_DIR, exist_ok=True)

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Simple logic based on placeholders/keywords for demonstration
    # In a real scenario, this would involve LLM-based classification
    if "證據等級 : 高" in content:
        dest = os.path.join(TIMELINE_DIR, os.path.basename(filepath))
        shutil.move(filepath, dest)
        print(f"Moved to Timeline: {filepath}")
    elif "視角 : 多重" in content:
        dest = os.path.join(ANGLES_DIR, os.path.basename(filepath))
        shutil.move(filepath, dest)
        print(f"Moved to Angles: {filepath}")
    elif "證據等級 : 低" in content:
        dest = os.path.join(UNVERIFIED_DIR, os.path.basename(filepath))
        shutil.move(filepath, dest)
        print(f"Moved to Unverified: {filepath}")
    else:
        # Default/unclassified
        pass

def run_git_commit():
    try:
        subprocess.run(["git", "add", "."], cwd=PROJECT_ROOT, check=True)
        msg = f"auto(ingestion): synced {datetime.now().strftime('%Y-%m-%d')} history data"
        subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)
        print("Git commit completed.")
    except Exception as e:
        print(f"Git operation failed: {e}")

if __name__ == "__main__":
    setup_dirs()
    files_processed = False
    for filename in os.listdir(QUEUE_DIR):
        filepath = os.path.join(QUEUE_DIR, filename)
        if os.path.isfile(filepath) and filename.startswith("raw_"):
            process_file(filepath)
            files_processed = True
    
    if files_processed:
        run_git_commit()
