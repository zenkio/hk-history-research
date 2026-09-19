#!/bin/bash
# Load user environment to ensure Git and SSH are available
source /home/zenkio/.bashrc
PROJECT_DIR="/home/zenkio/hk-history-research"
cd $PROJECT_DIR
$PROJECT_DIR/scripts/fetch_sources.py
$PROJECT_DIR/scripts/process_ingestion.py
