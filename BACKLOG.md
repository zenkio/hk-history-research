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
| C | Reference | Encyclopedias, museums, HK government sites, Wikidata |
| D | Web | Blogs, general web results |
| – | Unverified | AI draft only |

## 🔥 Burning (fix first)

- [ ] **Fact-check is broken.** The Gemini 2.5 models are parked as "unavailable". Read `parked` and `available` in `scripts/quota_state.json` after the next run, then fix the model id or switch verification to another route.
- [ ] **Watch the first runs after the PR #2 merge**: the repair step, video summaries, Commons photos, and the Gemma 26B id. Check the Actions logs and `quota_state.json`.

## Now (current focus: verification)

- [ ] **P1 Evidence engine.** For every AI claim, collect evidence and grade the page A–D:
  1. Wikidata: check dates and names with Python (no AI).
  2. OpenAlex / Crossref: academic works on the topic; Gemma or OpenRouter confirms relevance.
  3. Internet Archive full text: old books and official publications; AI reads the passage and marks the claim supported or contradicted.
  4. UK National Archives Discovery: link the matching CO 129 files.
  5. Google Search grounding: only for claims still unresolved (40 a day).

  Output: a `## Evidence` section per page, `evidence_grade` in the frontmatter, and a site page listing pages by grade.
- [ ] **P1 Order: core period first** (1841+), and within it the most-linked events first. _(Ordering is done; the engine is still to build.)_
- [ ] **P1 Deep Research import.** Ingest the results the owner pastes from Gemini Deep Research (`research/inbox/`) as grade A/B evidence and attach them to the matching pages.

## Next

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
| 2026-09-24 | Verification before any new content type | AI drafts are ~95% of the site and unproven |
