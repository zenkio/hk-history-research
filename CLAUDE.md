# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

**Two repositories.** This one (`zenkio/hk-history-research`, **public**) holds only code: `scripts/`, `tests/`, `quartz/`, site config and workflows. The content, research, evidence state, `BACKLOG.md` and `PRODUCT.md` live in **`zenkio/hk-history-data` (private)**. Never copy content, research notes, state files or pipeline output into this repository, its issues, PR text or workflow logs.

**Read `BACKLOG.md` first** (in hk-history-data), and `PRODUCT.md` for what we are building, how it runs and how it may earn money. `BACKLOG.md` is the single source of truth for scope (1841 to today first), priorities (verification before new content), the burning list and the decisions log. Put new ideas in its Inbox; don't start them unprompted. Deep Research hand-offs live in `research/` (prompts to give the owner, results in `research/inbox/`).

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

**Automation (this repository's workflows):** every job checks out **hk-history-data as the working folder** (secret `DATA_REPO_TOKEN`: fine-grained, Contents read/write on hk-history-data only) and copies this repository's code on top (`rsync`, excluding `.git`, `.gitignore`, README, CLAUDE.md, LICENSE). The scripts therefore find `content/` and `scripts/state/` where they always did, and their `git push` goes to the data repository.
- `.github/workflows/ingestion.yml` — the pipeline (fetch, repair, classify, seed; 45-minute seeding cap). **Off unless the repository variable `PIPELINE_ON_ACTIONS=on`**: it runs either here or on our own Oracle machine, never both (same quota, same branch). Script output goes to `$LOG`, saved by `scripts/save_log.sh` to the `logs` branch of hk-history-data (last 7 days, one commit, force-replaced), because public run logs would expose page names, queries and grades. A test checks every script step redirects.
- `.github/workflows/deploy.yml` — builds Quartz from the data, trims the search index (`scripts/trim_search_index.py`: page text cut to its opening) and publishes to GitHub Pages at `zenkio.github.io/hk-history-research`, on push to main and every 3 hours. Only the built site is ever uploaded as an artifact (artifacts of a public repo are downloadable; a test checks).
- `tests.yml` (every PR; `actionlint`, then pytest on the real content) and `site-build.yml` (full build when a PR touches the site setup).
- Not open source: `LICENSE` reserves all rights outside `quartz/` (Quartz's MIT licence is `quartz/LICENSE.txt`).

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

# Work on real data locally: clone hk-history-data, then copy this repo's code over it
# (the same overlay the workflows use), and run the steps inside that folder.
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

**Model pool:** `scripts/models.json` holds each free-tier model's RPM/TPM/RPD (copied from AI Studio) and a `routing` table naming which models serve each role, in order: `outline` (3.x Flash, 20 RPD each), `draft` (3.5/3.1 Flash Lite at 500 RPD, then Flash, then Gemma 4, which is TPM-bound at 16K), `classify` (Flash Lite, then Gemma), `verify` and `evidence` (the largest free OpenRouter models first: `OpenRouter Large` picks Nemotron 3 Ultra, `OpenRouter Medium` Nemotron 3 Super; Gemma only as fallback, after a 2026-09-28 audit found it too generous). `scripts/gemini_pool.py` resolves AI Studio display names to real API ids via `models.list()`, paces RPM and TPM, records usage in `scripts/quota_state.json` (resets at Pacific midnight), parks a model for the day on a daily-quota 429 or 404, and holds `reserve_for_ingestion` calls on classify models.

**Priority:** `seed_history.py` treats eras from `CORE_ERA_START` (`05-opium-war`, i.e. 1841 on) as core: they are drafted, verified and illustrated first, and only they are deepened.

**Evidence (top priority):** `scripts/evidence.py` runs first in each seeding run (`EVIDENCE_PAGES_PER_RUN`, core eras first). It searches OpenAlex (scholarship, grade B; needs the free `OPENALEX_API_KEY` since Feb 2026, without it only ~10 searches a day), UK National Archives Discovery (records, grade A) and Internet Archive (pre-1950 publications, grade A); the `evidence` role keeps only candidates about this specific event and labels each *supports* / *contradicts* / *background*; only the first two earn a grade (`grade_of`), background works are listed under "Background reading", a contradicting source adds tag `evidence-contradicts`. Once per `JUDGE_VERSION` the pages the engine graded A/B are judged again (pages with Deep Research notes are left alone). About 5% of pages (`AUDIT_SHARE`) are judged again by a different model; agreement is kept in `scripts/state/evidence_audit.json` and shown on the status page (target 90%+). A 429/503 waits for Retry-After and retries; a source that fails 3 times in a row is rested for the run, and a page that found nothing while a source was down is not recorded (it is searched again later, up to 20 such pages a run). Queries drop words that describe the event rather than name it ("Disastrous", "Establishment"), and each page logs what every source returned and how many the AI kept (`[evidence] "query": OpenAlex 6, National Archives 0, ...; AI kept 1`). Pages get `## Evidence`, `evidence_grade: A|B|none` and tag `evidence-*`; `content/00_Meta/Evidence_Status.md` shows totals. `scripts/research_import.py` imports Deep Research tables from `research/inbox/`: rows are matched to pages by year and a shared distinctive title word, every URL/DOI/ISBN is checked, only rows with a verified reference are attached (`## Research notes`). The grade comes from what a verified reference is (archive/record host A, DOI/ISBN/academic publisher B), never from the column Deep Research put it in; homepages and encyclopedias never count. Grades are only raised, except once per `GRADING_VERSION`, when files in `inbox/done/` are re-checked and regraded (state: `scripts/state/research.json`). Unmatched rows go to `research/unmatched.md` (candidate missing events); processed files move to `research/inbox/done/`. Progress: `scripts/state/evidence.json`.

**Parallel workers:** `seed_history.run` runs three workers at once, each on a different quota, so a slow or exhausted provider only delays its own work: `research` thread (Deep Research import, then evidence: OpenRouter + archive APIs, then Gemma), `photos` thread (Gemma vision + Commons), and the main thread (Gemini 2.5 fact-check, then drafting). `ModelPool` is thread-safe (quota state under a lock, per-model pacing locks). Each worker keeps progress in its own file, `scripts/state/<name>.json` (atomic writes; `photos` and `evidence` were migrated out of `seed_plan.json`), and page edits go through `state.PAGE_LOCK`. `process_ingestion.py` commits after every page and stops after `INGEST_MINUTES` (default 20); a model that exhausts its overload retries is rested for 10 minutes.

**History seeding:** `scripts/seed_history.py` spends leftover quota on AI-drafted pages (tag `ai-draft`): era overviews and event pages in `content/01_Timeline/<NN-era>/`, and people/place pages in `content/02_Entities/`. Each run cross-checks up to 80 unchecked event pages (core first) against Wikipedia (`scripts/wikipedia.py`; Gemini 2.5, the only free search-grounded models, is closed to new users and Gemini 3 grounding is 0 on the free tier). The "Claims to verify" checklist becomes `## Wikipedia cross-check`: each claim agrees / differs / not in Wikipedia, plus the books and papers the articles cite with DOI/ISBN checked (tags `wikipedia-checked` / `wikipedia-differs`). Wikipedia is never evidence: it does not change `evidence_grade` or `confidence`. Progress lives in `scripts/seed_plan.json`, so runs resume where they stopped. Runs after RSS ingestion in the same workflow.

**OpenRouter and translation:** `models.json` entries with `"provider": "openrouter"` pick a current `:free` model by name fragment at startup and share the account-wide `providers.openrouter.rpd` limit: at startup `gemini_pool` asks OpenRouter's key endpoint whether the account is on the free tier (50/day) or has bought credits (1,000/day; the owner's has). The per-minute free limit (~20) is account-wide too, so the entries' `rpm` add up to less. Keys are tried in order `OPENROUTER_API_KEY`, then `OPEN_ROUTER_KEY_RESEARCHER` (values stripped); a key OpenRouter rejects with 401 is dropped for the run and the log names the key in use (never its value). `scripts/translate.py` writes Traditional Chinese (Hong Kong) versions to `content/zh/<same path>` with links both ways. It is switched off (`TRANSLATE_WITH_AI = False` in `seed_history.py`): readers use browser translation and the AI budget goes to verification. Progress: `translations` in `seed_plan.json`.

**Videos:** `fetch_sources.py` records YouTube ids embedded or linked in a post (`videos:` header in the queue file). `process_ingestion.py` handles up to 2 per post through `scripts/videos.py`, subtitles first: it reads the video's own subtitles with `youtube-transcript-api` (channel-made before auto-generated, Chinese then English; no key) and the `video_text` role (Flash Lite, then Gemma) summarises them. When the `video` quota allows, a model also watches the video and lists what it shows beyond its words (documents, photos, on-screen text) and whether the subtitles were enough (`### What the video shows beyond its words`). With no subtitles, or when YouTube blocks the runner's IP (then skipped for the rest of the run), the `video` role watches the video as before (low media resolution, ~100 tokens/s). Every video's outcome is kept in `scripts/state/videos.json` (`videos.stats()` shows how often subtitles were enough). The page's `## Video` section has the embed, a callout saying which method was used, and timestamped key points. A 400 / INVALID_ARGUMENT (e.g. private video) raises `RequestRejected` at once instead of retrying across models.

**Photos:** `scripts/photos.py`, two paths split by copyright. (1) Photos inside source posts (HPHK, Gwulo): `fetch_sources.py` records them (`images:` header); `process_ingestion.py` has the `vision` role describe up to 3 and adds a `## Photos in the source` section of caption cards linking to the photo and post, never re-hosting or embedding. (2) Wikimedia Commons: each seeding run searches Commons for `PHOTO_EVENTS_PER_RUN` event pages, keeps only free licences (PD/CC0/CC BY/CC BY-SA), has the `vision` role judge relevance against the page, and adds `## Photos from this period` with author, licence, link and what the photo corroborates or contradicts (tag `photo-corroborated`); a Commons file is used on one page only. Progress: `scripts/state/photos.json`. Models that reject image input are skipped for media for the rest of the run.

**Repair:** `scripts/repair_content.py` runs before classification each run: rebuilds summaries cut mid-word, adds `description` (what Quartz shows in search and previews), checks every RSS page against its source once (`scripts/repaired_urls.json`) and re-queues it if it is only a teaser or the source embeds a video we have not summarised, and removes `_NNNNNN` duplicate pages.

**SDK:** Uses `google.genai` (not the deprecated `google.generativeai`).

**Output format:** Files written as `.md` with YAML frontmatter containing `title`, `tags`, `summary`, `confidence`, `ingested`, `date`.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
```

- `tests/` runs offline: `conftest.py` blocks real network calls, fakes `time.sleep`, points
  `scripts/state/` and `TIMELINE_DIR` at temp folders, gives each test a 10 s limit (an endless retry
  loop fails instead of hanging) and builds a `ModelPool` with fake providers (`make_pool`).
- Unit tests cover each module; integration tests run whole steps (research import with regrade,
  evidence batch, Wikipedia cross-check, videos) on temp pages with fake AI and fake websites;
  `test_content_and_config.py` checks the real `models.json`, workflows and every pipeline page.
- **Every bug fix comes with a test that fails on the old code** (name the PR in a comment), and the
  suite must pass before a pull request is opened or updated.
- CI: `.github/workflows/tests.yml` runs the suite on every pull request, on the private content
  (overlay as above); `site-build.yml` runs a full Quartz build when a PR touches the site setup.
- Locally: copy the code over a clone of hk-history-data (`tar` or `rsync`, excluding `.git`) and run
  `python -m pytest tests -q` there; in this repository alone the content checks find no pages.

## Git workflow

- Code changes are pull requests here; content, research and backlog changes are pull requests in hk-history-data.
- The owner reviews and merges every pull request; Claude opens them and never pushes to `main`.
- **At most one open pull request from Claude at a time** (across both repositories). While it is open, add further work to
  that same branch (it is not merged yet) and update its description; don't open a second one.
- **A new branch after every merge.** Once that pull request is merged, start the next piece of work on
  a new branch from the latest `origin/main` (`git fetch origin && git checkout -b claude/<short-topic>
  origin/main`). Never reuse a branch whose pull request has been merged, even for a follow-up.
- The pipeline commits to hk-history-data's `main` every hour, so fetch it right before branching and before pushing there.

## Important Constraints

- The `quartz/` directory MUST be committed to git — the build fails without it since the package is private and not available from npm.
- New ingested content goes to `content/` subdirs (not root `01_Timeline/` etc.) so Quartz can render it.
- The pipeline pushes to hk-history-data with `DATA_REPO_TOKEN`; this repository's workflows only need `contents: read` (plus Pages permissions for deploy).
- Raw data files in root `01_Timeline/`, `03_Angles/` are legacy and not rendered by Quartz.
