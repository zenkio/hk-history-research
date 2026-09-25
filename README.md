# HK History Research

A browsable history of Hong Kong where every statement should be traceable to evidence.
Focus: **1841 to today**, from the British occupation of Hong Kong Island to the HKSAR.

🌐 **Site:** https://zenkio.github.io/hk-history-research/
中文讀者：請使用瀏覽器的「翻譯此網頁」功能。

> [!WARNING]
> Most pages are still **AI drafts** (tag `ai-draft`) written from general knowledge. They are being
> checked against archives, scholarship and photographs; each page shows how far that has got.
> Treat a page without evidence as a starting point, not a fact.

## How pages earn trust

| Grade | Evidence | Where it comes from |
|---|---|---|
| **A** | Primary sources | UK National Archives (CO 129, FO 17), Hong Kong Government Gazette and Blue Books, contemporary newspapers and publications, contemporary photos |
| **B** | Scholarship | Peer-reviewed articles and academic books (checked by DOI/ISBN) |
| – | None yet | AI draft only |

Each page shows its grade (`evidence_grade`, tags `evidence-a` / `evidence-b` / `evidence-none`)
and an **Evidence** section with the matched records. The site's *Evidence status* page has the totals.

**Wikipedia is never evidence**, because anyone can edit it. Pages get a *Wikipedia cross-check*
(each claim agrees / differs / is not covered) plus the books and papers Wikipedia cites, with
their DOI/ISBN checked. Pages where the draft and Wikipedia differ (tag `wikipedia-differs`) are
the first to check against primary sources.

Photos: freely licensed Wikimedia Commons images are shown with author and licence; photos
from rights-held collections (Gwulo, the University of Bristol's historical photographs) are described and linked,
never copied.

## How it works

Everything runs on free tiers: GitHub Actions, GitHub Pages, the Gemini API free tier and
OpenRouter free models. The ingestion workflow runs every hour; the site is rebuilt every 3 hours.

```
RSS feeds (history blogs, archives)      Deep Research results (research/inbox/)
        │                                          │
fetch_sources.py → 04_Ingestion_Queue/     research_import.py (links checked)
        │                                          │
process_ingestion.py (classify, summarise          │
  linked YouTube videos, describe photos)          │
        │                                          │
        └──────────────► content/ ◄────────────────┘
                            ▲
seed_history.py, three workers in parallel:
  • research: Deep Research import, then evidence.py
    (OpenAlex, UK National Archives, Internet Archive; an AI keeps only real matches)
  • photos:   photos.py (Wikimedia Commons, judged by a vision model)
  • main:     wikipedia.py cross-check, then drafting missing pages
                            │
             static site build → GitHub Pages
```

| Path | What it is |
|---|---|
| `content/01_Timeline/` | Events by era (`05-opium-war` onwards is the core period) |
| `content/02_Entities/` | People and places |
| `content/03_Angles/`, `content/04_Unverified/` | Articles from sources; low-confidence items |
| `content/00_Meta/` | Evidence status and site notes |
| `scripts/` | The Python pipeline (see `CLAUDE.md` for each script) |
| `scripts/models.json` | Free-tier model limits and which model does which job |
| `scripts/state/` | Progress of each worker, so runs resume where they stopped |
| `research/` | Deep Research prompts, results inbox, unmatched events |
| `BACKLOG.md` | Priorities, the burning list and decisions. **Read it first.** |

## Helping with research

The owner runs the prompts in `research/prompts/` in Gemini Deep Research and uploads the
answers to `research/inbox/`. The next pipeline run checks every link, DOI and ISBN, attaches
what holds up to the matching pages, and lists events we are missing in `research/unmatched.md`.
See `research/README.md`.

## Running it locally

```bash
pip install -r requirements.txt           # Python pipeline
echo "GEMINI_API_KEY=..." > .env          # optional: OPENROUTER_API_KEY=...

python3 scripts/fetch_sources.py          # fetch RSS into the queue
python3 scripts/process_ingestion.py      # classify into content/
python3 scripts/seed_history.py --minutes 30 --no-commit

npm ci && npm run install-plugins         # site
npm run quartz -- build --serve           # http://localhost:8080
```

In CI the keys are the repository secrets `GEMINI_API_KEY` and `OPENROUTER_API_KEY`.
Never commit a key.

## Credits

The site is built with [Quartz](https://quartz.jzhao.xyz/) by Jacky Zhao (MIT licence, see
`LICENSE.txt`), kept in `quartz/`. Sources are credited on every page that uses them.
