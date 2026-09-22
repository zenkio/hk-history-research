#!/bin/bash
# Use current working directory as project root
PROJECT_DIR=$(pwd)
cd $PROJECT_DIR

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run research scripts
python3 scripts/fetch_sources.py
python3 scripts/process_ingestion.py
