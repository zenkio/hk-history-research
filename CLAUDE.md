# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

An automated pipeline that fetches Hong Kong history content from RSS feeds, classifies it with Gemini AI, and publishes it as a searchable, browsable website via Quartz (static site generator) on GitHub Pages.

## Architecture

```
RSS Feeds → fetch_sources.py → 04_Ingestion_Queue/
                                      ↓
                             process_ingestion.py (Gemini AI classifies)
                                      ↓
               content/01_Timeline/   content/03_Angles/   content/04_Unverified/
                                      ↓
                              Quartz build → public/ → GitHub Pages
```

**Key directories:**
- `04_Ingestion_Queue/` — staging area for freshly fetched RSS content (root, not content/)
- `content/01_Timeline/` — dated historical events (Quartz renders this)
- `content/03_Angles/` — analysis, photos, documents offering historical perspectives
- `content/04_Unverified/` — low-confidence or off-topic content
- `quartz/` — Quartz 5.0 source (must stay in git, not gitignored)
- `scripts/` — Python pipeline scripts

**Automation:**
- `.github/workflows/ingestion.yml` — runs every 3 hours, calls `scripts/run_pipeline.sh`
- `.github/workflows/deploy.yml` — triggers on every push to main, builds and deploys Quartz

## Build & Development

```bash
# Install Node dependencies
npm ci
npm run install-plugins

# Build the Quartz site locally
npm run quartz -- build

# Serve locally (after build)
npm run quartz -- build --serve
# or
python3 scripts/serve_preview.py public 8000

# Run the ingestion pipeline locally
./scripts/run_pipeline.sh

# Run individual pipeline steps
python3 scripts/fetch_sources.py     # fetch RSS → 04_Ingestion_Queue/
python3 scripts/process_ingestion.py # classify → content/
```

## Quartz Configuration

Site config is in `quartz.config.default.yaml`. Key settings:
- `baseUrl`: `zenkio.github.io/hk-history-research`
- `pageTitle`: `HK History Research`
- Layout components are in `quartz.layout.ts`
- Content files must be `.md` with YAML frontmatter

## Python Pipeline

**Requirements:** `requirements.txt` (feedparser, google-genai, python-dotenv)

**Environment:** `GEMINI_API_KEY` in `.env` locally, GitHub secret for CI.

**Model fallback order:** `gemini-2.0-flash-lite` → `gemini-2.0-flash` → `gemini-1.5-flash`

**SDK:** Uses `google.genai` (not the deprecated `google.generativeai`).

**Output format:** Files written as `.md` with YAML frontmatter containing `title`, `tags`, `summary`, `confidence`, `ingested`, `date`.

## Important Constraints

- The `quartz/` directory MUST be committed to git — the build fails without it since the package is private and not available from npm.
- New ingested content goes to `content/` subdirs (not root `01_Timeline/` etc.) so Quartz can render it.
- The ingestion workflow uses `contents: write` permission to push new content back to main.
- Raw data files in root `01_Timeline/`, `03_Angles/` are legacy and not rendered by Quartz.
