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
python3 scripts/seed_history.py --minutes 30 --no-commit  # AI-draft history pages
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

**Model pool:** `scripts/models.json` holds each free-tier model's RPM/TPM/RPD (copied from AI Studio) and a `routing` table naming which models serve each role, in order: `outline` (3.x Flash, 20 RPD each), `draft` (3.5/3.1 Flash Lite at 500 RPD, then Flash, then Gemma 4, which is TPM-bound at 16K), `classify` (Flash Lite, then Gemma), `verify` (2.5 Flash / Flash Lite, the only free models with Google Search grounding). `scripts/gemini_pool.py` resolves AI Studio display names to real API ids via `models.list()`, paces RPM and TPM, records usage in `scripts/quota_state.json` (resets at Pacific midnight), parks a model for the day on a daily-quota 429 or 404, and holds `reserve_for_ingestion` calls on classify models.

**History seeding:** `scripts/seed_history.py` spends leftover quota on AI-drafted pages (tag `ai-draft`): era overviews and event pages in `content/01_Timeline/<NN-era>/`, and people/place pages in `content/02_Entities/`. Each run first fact-checks the oldest unchecked event pages with search grounding, replacing the "Claims to verify" checklist with verdicts and web sources (`confidence: ai-draft-checked`, tags `search-checked` / `needs-correction`). Progress lives in `scripts/seed_plan.json`, so runs resume where they stopped. Runs after RSS ingestion in the same workflow.

**SDK:** Uses `google.genai` (not the deprecated `google.generativeai`).

**Output format:** Files written as `.md` with YAML frontmatter containing `title`, `tags`, `summary`, `confidence`, `ingested`, `date`.

## Important Constraints

- The `quartz/` directory MUST be committed to git — the build fails without it since the package is private and not available from npm.
- New ingested content goes to `content/` subdirs (not root `01_Timeline/` etc.) so Quartz can render it.
- The ingestion workflow uses `contents: write` permission to push new content back to main.
- Raw data files in root `01_Timeline/`, `03_Angles/` are legacy and not rendered by Quartz.
