# Backlog: the single source of truth

Read this before starting any work. If an idea is not in **Now**, it waits.
New ideas go to **Inbox** first and are sorted at the next review, never started on the spot.

_Last reviewed: 2026-09-24_

## North star

A trustworthy, browsable history of Hong Kong where every statement can be traced to evidence.

**Scope, in priority order**
1. **Core: 1841 to today.** The British occupation of Hong Kong Island, the colony, the Japanese occupation, the handover and the HKSAR. Eras `05-opium-war` to `16-national-security-era`.
2. **Background: before 1841.** Kept, but only expanded when there is evidence (archaeology, photos, documents, news). No more AI-only drafting for these eras.

**Principles**
- Evidence before volume. A verified page is worth more than ten drafted ones.
- AI text is always labelled. Nothing is presented as fact without a source.
- Respect copyright: link to and describe rights-held material, and embed only freely licensed media.
- Free tier only. This is a hobby project, so there are no paid APIs.

## Evidence grades (what "verified" means)

| Grade | Evidence | Examples |
|---|---|---|
| A | Primary sources | UK National Archives (CO 129), HK Government Gazette, Blue Books, contemporary newspapers, contemporary photos |
| B | Scholarship | Peer-reviewed papers, academic books (OpenAlex/Crossref DOI), JRAS Hong Kong Branch |
| C | Reference | Edited encyclopedias (Britannica), museums, HK government sites. **Not Wikipedia/Wikidata**: anyone can edit them, so they are cross-checks and pointers to sources, never evidence |
| D | Web | Blogs, general web results |
| – | Unverified | AI draft only |

## 🔥 Burning (fix first)

- [ ] **Fact-check is broken: Gemini 2.5 Flash and Flash Lite are closed to new users** (404 "no longer available to new users"). They were the only free models with Google Search grounding. Gemini 3.x search grounding is 0/day on the free tier (AI Studio). _Fix in PR #7: a Wikipedia cross-check. Gemma compares each claim with Wikipedia text only (agrees / differs / not in Wikipedia) and lists the books and papers Wikipedia cites, with DOI/ISBN checked. Wikipedia never counts as evidence (anyone can edit it), so it never raises a grade. Up to 80 pages a run, core eras first._
- [ ] **10 source pages still waiting in the ingestion queue** (were 14). The repair run on 2026-09-23 re-queued them (11 have videos to summarise), but the video quota was spent. They come back after 07:00 UTC. _Fixed for the future: repair now keeps the old page until its replacement is written._
- [x] ~~OpenRouter wrongly switched off for the day when a step lacks the key~~: now skipped per run; the key is also passed to the classify step.
- [x] ~~Model ids~~: Gemma 26B resolves to `gemma-4-26b-a4b-it`, Gemini 3 Flash to `gemini-3-flash-preview`. OpenRouter picked `qwen/qwen3.8-27b:free`; no free DeepSeek model exists now, so the second slot falls back to GLM, Kimi or Llama 4.

## Now (current focus: verification)

- [x] **P1 Evidence engine v1** built (`scripts/evidence.py`): OpenAlex + National Archives + Internet Archive, AI relevance filter, grades A/B/none, status page. _Not yet built: Wikidata date checks, Internet Archive full-text passage checks._
- [ ] **P1 Evidence engine v2.** For every AI claim, collect evidence and grade the page A–D:
  1. Wikidata: check dates and names with Python (no AI).
  2. OpenAlex / Crossref: academic works on the topic; Gemma or OpenRouter confirms relevance.
  3. Internet Archive full text: old books and official publications; AI reads the passage and marks the claim supported or contradicted.
  4. UK National Archives Discovery: link the matching CO 129 files.
  5. Wikipedia cross-check is live, but it is a pointer, not evidence. Next: have the evidence engine read the sources Wikipedia cites and mark each claim supported or not, so Wikipedia's own statements are tested too.

  Output: a `## Evidence` section per page, `evidence_grade` in the frontmatter, and a site page listing pages by grade.
- [ ] **P1 Order: core period first** (1841+), and within it the most-linked events first. _(Ordering is done; the engine is still to build.)_
- [x] **P1 Deep Research import** built (`scripts/research_import.py`): link-checks every citation and attaches only rows with a working link. First file (1834–1842) imported: 17 of 25 rows matched pages. DOIs and ISBNs are verified by title against Crossref/Open Library, and `[cite: N]` numbers are resolved to the source list.
- [ ] **P1 Review `research/unmatched.md`**: missing events found by Deep Research (8 from 1834–1842, e.g. the 1840 expeditionary force and the 1842 Chinese Registration Ordinance). Add the real ones to the plan as new events.
- [ ] **P1 Owner: run Deep Research prompt 01 for the next eras** (1834–1842 and 1842–1860 done; next 1860–1898).
- [ ] **P1 Owner: run Deep Research prompt 02 (source map)** once, save as `research/source-map.md`.
- [ ] **P1 Hong Kong government records as evidence sources.** Today only UK records are searched (National Archives catalogue: CO 129, FO 17). Add, most useful first: HKU Hong Kong Government Reports Online (Gazette 1842–1941, Blue Books, Hansard, Sessional Papers), old HK newspapers (HKPL MMIS), Government Records Service (HKRS catalogue). Use the source map to choose and test them.

## Next

- [ ] **P2 Myths and disputes hub.** One page listing claims where the draft, Wikipedia and the evidence disagree (tag `wikipedia-differs`, Deep Research "Disputes or myths"), with what the primary sources actually say. Readers want to know what is made up.

- [ ] **P2 Place pages by angle.** Fixed sections per place: overview, politics & government, economy & work, food, daily life & culture, nature, animals & weather, buildings, happy moments, sad moments, photos. Each links to its events.
- [ ] **P2 Topic hubs** across places: typhoons, fires, food history, housing, festivals, epidemics.
- [ ] **P2 Photo galleries per era** that collect all matched Commons photos.
- [ ] **P2 Flickr Commons** as a photo source (needs a free `FLICKR_API_KEY`).
- [ ] **P3 HPHK collection search** (hpcbristol.net) beyond blog posts. Needs a look at how the site is structured.

## Later

- [ ] Evidence-grade badge and filter on the site (Quartz component).
- [ ] Chinese pages: for now readers use the browser's built-in translation. Revisit AI translation (Qwen/DeepSeek via OpenRouter) once verification is done. The code exists in `scripts/translate.py` and is switched off by `TRANSLATE_WITH_AI` in `seed_history.py`.
- [ ] Sustainability: donations (GitHub Sponsors, Ko-fi), heritage/education grants, school or tour partnerships. Only once content is verified. See "Decisions".

## Inbox (unsorted ideas; do not start)

- An MCP server or connector so Claude can search the web from a session.
- Oral history: interviews, audio.
- Maps: historical map overlays by year.

## Done

- 2026-09-24: Run 12 (first run on PR #6): 52 pages graded (A 14, B 8, none 30), 21 of 118 pages got Commons photos, Deep Research 1834–1842 imported. Runs 9 and 11 failures fixed (PRs #5, #6).

- 2026-09-24: Parallel workers (Gemini / research / photos) in the seeding step; commit per page; overload cooldown.

- 2026-09-24: Evidence engine v1 and Deep Research importer.

- 2026-09-24: Focus set: 1841+ first; AI translation off; pre-1841 eras no longer deepened.
- 2026-09-23: PR #2: hourly pipeline, 3-hourly deploy, quota fixes, summary and teaser repair, video summaries, photos (source cards and Commons), OpenRouter support.
- 2026-09-23: PR #1: model pool, AI-drafted timeline (16 eras, ~870 events, ~850 people/places).

## Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-09-23 | Free tier only, no pay-as-you-go keys | Hobby project |
| 2026-09-23 | Hourly pipeline, deploy every 3 hours | Gemma is limited by tokens per minute, so idle hours waste it; the site doesn't need faster updates |
| 2026-09-23 | Rights-held photos are described and linked, never embedded | Copyright belongs to donors and families |
| 2026-09-24 | Core scope 1841 to today; pre-1841 only with evidence | Owner priority |
| 2026-09-24 | AI translation off; browser translation for now | Spend AI budget on verification |
| 2026-09-24 | Parallel workers per quota inside one job, not separate jobs | Separate jobs would race on git pushes and edit the same pages; threads share one checkout with page locks |
| 2026-09-24 | Wikipedia is a cross-check, never evidence | Anyone can edit it; agreement proves nothing, but its citations are leads |
| 2026-09-24 | Verification before any new content type | AI drafts are ~95% of the site and unproven |
