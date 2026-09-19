#!/bin/bash
PROJECT_DIR="/home/zenkio/hk-history-research"
$PROJECT_DIR/scripts/fetch_sources.py
$PROJECT_DIR/scripts/process_ingestion.py
