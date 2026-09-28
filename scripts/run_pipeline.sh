#!/bin/bash
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

pip install -r requirements.txt --quiet

python3 scripts/fetch_sources.py
python3 scripts/process_ingestion.py
