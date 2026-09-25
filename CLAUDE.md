# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

**Read `BACKLOG.md` first.** It is the single source of truth for scope (1841 to today first), priorities (verification before new content), the burning list and the decisions log. Put new ideas in its Inbox; don't start them unprompted. Deep Research hand-offs live in `research/` (prompts to give the owner, results in `research/inbox/`).

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
- `.github/workflows/ingestion.yml` — runs hourly (45-minute seeding cap): fetch, repair, classify, seed
- `.github/workflows/deploy.yml` — builds and deploys Quartz on a human push to main and every 3 hours on a schedule. Bot pushes (GITHUB_TOKEN) never trigger `push` workflows, hence the schedule.

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

**Priority:** `seed_history.py` treats eras from `CORE_ERA_START` (`05-opium-war`, i.e. 1841 on) as core: they are drafted, verified and illustrated first, and only they are deepened.

**Evidence (top priority):** `scripts/evidence.py` runs first in each seeding run (`EVIDENCE_PAGES_PER_RUN`, core eras first). It searches OpenAlex (scholarship, grade B), UK National Archives Discovery (records, grade A) and Internet Archive (pre-1950 publications, grade A) with no API keys; the `evidence` role (OpenRouter free models first, then Gemma) keeps only candidates really about the page and maps them to its claims. Pages get `## Evidence`, `evidence_grade: A|B|none` and tag `evidence-*`; `content/00_Meta/Evidence_Status.md` shows totals. `scripts/research_import.py` imports Deep Research tables from `research/inbox/`: rows are matched to pages by year and a shared distinctive title word, every URL/DOI/ISBN is checked, only rows with a verified reference are attached (`## Research notes`). The grade comes from what a verified reference is (archive/record host A, DOI/ISBN/academic publisher B), never from the column Deep Research put it in; homepages and encyclopedias never count. Grades are only raised, except once per `GRADING_VERSION`, when files in `inbox/done/` are re-checked and regraded (state: `scripts/state/research.json`). Unmatched rows go to `research/unmatched.md` (candidate missing events); processed files move to `research/inbox/done/`. Progress: `scripts/state/evidence.json`.

**Parallel workers:** `seed_history.run` runs three workers at once, each on a different quota, so a slow or exhausted provider only delays its own work: `research` thread (Deep Research import, then evidence: OpenRouter + archive APIs, then Gemma), `photos` thread (Gemma vision + Commons), and the main thread (Gemini 2.5 fact-check, then drafting). `ModelPool` is thread-safe (quota state under a lock, per-model pacing locks). Each worker keeps progress in its own file, `scripts/state/<name>.json` (atomic writes; `photos` and `evidence` were migrated out of `seed_plan.json`), and page edits go through `state.PAGE_LOCK`. `process_ingestion.py` commits after every page and stops after `INGEST_MINUTES` (default 20); a model that exhausts its overload retries is rested for 10 minutes.

**History seeding:** `scripts/seed_history.py` spends leftover quota on AI-drafted pages (tag `ai-draft`): era overviews and event pages in `content/01_Timeline/<NN-era>/`, and people/place pages in `content/02_Entities/`. Each run cross-checks up to 80 unchecked event pages (core first) against Wikipedia (`scripts/wikipedia.py`; Gemini 2.5, the only free search-grounded models, is closed to new users and Gemini 3 grounding is 0 on the free tier). The "Claims to verify" checklist becomes `## Wikipedia cross-check`: each claim agrees / differs / not in Wikipedia, plus the books and papers the articles cite with DOI/ISBN checked (tags `wikipedia-checked` / `wikipedia-differs`). Wikipedia is never evidence: it does not change `evidence_grade` or `confidence`. Progress lives in `scripts/seed_plan.json`, so runs resume where they stopped. Runs after RSS ingestion in the same workflow.

**OpenRouter and translation:** `models.json` entries with `"provider": "openrouter"` pick a current `:free` model by name fragment at startup and share the account-wide `providers.openrouter.rpd` limit (50/day; 1000 after a lifetime $10 top-up), using `OPENROUTER_API_KEY`. `scripts/translate.py` writes Traditional Chinese (Hong Kong) versions to `content/zh/<same path>` with links both ways. It is switched off (`TRANSLATE_WITH_AI = False` in `seed_history.py`): readers use browser translation and the AI budget goes to verification. Progress: `translations` in `seed_plan.json`.

**Videos:** `fetch_sources.py` records YouTube ids embedded or linked in a post (`videos:` header in the queue file). `process_ingestion.py` has Gemini watch up to 2 per post (role `video`, low media resolution, ~100 tokens/s), feeds that summary into the article, and adds a `## Video` section with the embed, an AI-summary callout and timestamped key points. A 400 / INVALID_ARGUMENT (e.g. private video) raises `RequestRejected` at once instead of retrying across models.

**Photos:** `scripts/photos.py`, two paths split by copyright. (1) Photos inside source posts (HPHK, Gwulo): `fetch_sources.py` records them (`images:` header); `process_ingestion.py` has the `vision` role describe up to 3 and adds a `## Photos in the source` section of caption cards linking to the photo and post, never re-hosting or embedding. (2) Wikimedia Commons: each seeding run searches Commons for `PHOTO_EVENTS_PER_RUN` event pages, keeps only free licences (PD/CC0/CC BY/CC BY-SA), has the `vision` role judge relevance against the page, and adds `## Photos from this period` with author, licence, link and what the photo corroborates or contradicts (tag `photo-corroborated`); a Commons file is used on one page only. Progress: `scripts/state/photos.json`. Models that reject image input are skipped for media for the rest of the run.

**Repair:** `scripts/repair_content.py` runs before classification each run: rebuilds summaries cut mid-word, adds `description` (what Quartz shows in search and previews), checks every RSS page against its source once (`scripts/repaired_urls.json`) and re-queues it if it is only a teaser or the source embeds a video we have not summarised, and removes `_NNNNNN` duplicate pages.

**SDK:** Uses `google.genai` (not the deprecated `google.generativeai`).

**Output format:** Files written as `.md` with YAML frontmatter containing `title`, `tags`, `summary`, `confidence`, `ingested`, `date`.

## Git workflow

- The owner reviews and merges every pull request; Claude opens them and never pushes to `main`.
- **One branch per pull request.** Start each new piece of work on a new branch from the latest
  `origin/main` (`git fetch origin && git checkout -b claude/<short-topic> origin/main`). Never reuse
  a branch whose pull request has been merged, even for a follow-up.
- The pipeline commits to `main` every hour, so fetch right before branching and before pushing.

## Important Constraints

- The `quartz/` directory MUST be committed to git — the build fails without it since the package is private and not available from npm.
- New ingested content goes to `content/` subdirs (not root `01_Timeline/` etc.) so Quartz can render it.
- The ingestion workflow uses `contents: write` permission to push new content back to main.
- Raw data files in root `01_Timeline/`, `03_Angles/` are legacy and not rendered by Quartz.
