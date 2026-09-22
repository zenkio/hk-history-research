#!/bin/bash
PROJECT_DIR="/home/zenkio/hk-history-research"
cd $PROJECT_DIR
source venv/bin/activate
python3 scripts/fetch_sources.py
python3 scripts/process_ingestion.py
