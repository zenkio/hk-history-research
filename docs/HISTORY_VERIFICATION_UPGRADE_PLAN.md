# HK History Research — Verification-First Website Upgrade Plan

## 1. Goal

Upgrade HK History Research from an **AI-drafted history with evidence attached** into a **research pipeline where AI drafts are hypotheses, claims are independently verified, and only verified claims become the published historical narrative**.

The existing content is not discarded. Existing AI pages become the baseline hypothesis dataset and the starting point for research.

### Core rule

> **AI may propose history. Evidence decides history.**

A page must never look "verified" merely because an AI model found a plausible source or because its evidence grade is high.

---

## 2. Target architecture

Use three explicit layers:

| Layer | Purpose | Can appear as authoritative history? |
|---|---|---|
| **Hypothesis** | Existing AI-generated event/overview/entity pages | No |
| **Research** | Claim-by-claim source discovery, evidence extraction and judgement | No; research record only |
| **Published History** | Narrative generated from claims that passed verification | Yes |

The current `AI draft` pages remain intact as Layer 1.

---

## 3. Phase 1 — Make the current data model explicit

### 3.1 Preserve existing AI pages

Do not regenerate or delete the current `hk-history-data` pages.

Every existing AI event should remain identifiable as:

- `origin: ai`
- `verification_status: unverified`
- `confidence: ai-draft`

Existing `Claims to verify` sections should become the initial research queue.

### 3.2 Introduce stable claim IDs

Every factual claim that matters should receive a stable ID, for example:

`claim:1841-british-landing-date`

Claims should be independently addressable rather than hidden inside a long event page.

Minimum claim fields:

- `id`
- `event_id`
- `text`
- `claim_type` — date / place / people / cause / action / outcome / scale / context
- `status` — unverified / supported / contradicted / partial / insufficient
- `importance` — core / supporting
- `created_from` — AI draft / imported research / manual

### 3.3 Separate source discovery from evidence

A discovered source is **not evidence yet**.

Store separately:

1. source metadata
2. relevant passage/page/record
3. which claim it addresses
4. relationship — supports / contradicts / background
5. researcher/model judgement
6. provenance and retrieval date

---

## 4. Phase 2 — Upgrade evidence research

### 4.1 Prioritise authoritative source families

The research pipeline should actively search source families in this order where applicable:

1. **Hong Kong Government / Government Records Service**
2. **UK National Archives / UK government records**
3. **Hong Kong Public Libraries / major library catalogues**
4. **University and institutional archives**
5. **Contemporary newspapers and periodicals**
6. **Peer-reviewed scholarship / academic books**
7. **Established specialist historical collections**
8. Wikipedia — cross-check only, never evidence

The existing RSS feeds remain useful discovery inputs, but they must not be treated as the main evidence base.

### 4.2 Search by claim, not only event title

Current title-based search should evolve to:

- claim text
- event name
- aliases / historical names
- date range
- place
- people
- source-family-specific queries

One event can therefore produce several independent research queries.

### 4.3 Retrieve the actual evidence

A source should not count merely because its title or short metadata note looks relevant.

For each candidate source, attempt to capture:

- exact quotation or faithful excerpt
- page / section / archive reference where available
- source publication/archive date
- source type
- URL or stable catalogue identifier
- retrieval date

If the actual relevant passage cannot be inspected, classify the source as **candidate/background**, not verified evidence.

---

## 5. Phase 3 — Replace page-level evidence with claim-level verification

### Verification states

Use explicit states:

| Status | Meaning |
|---|---|
| **supported** | Evidence directly supports the claim |
| **contradicted** | Reliable evidence directly conflicts with the claim |
| **partial** | Only part of the claim is supported |
| **insufficient** | Research exists but does not establish the claim |
| **unverified** | No meaningful research completed |

### Important rule

**Contradictory evidence must never increase a claim's confidence simply because evidence exists.**

The current evidence grade is a measure of evidence coverage, not correctness. Replace or rename it so users cannot confuse "has sources" with "is true".

Suggested published metrics:

- Evidence coverage
- Primary-source coverage
- Contradiction count
- Unresolved claim count
- Source independence

---

## 6. Phase 4 — Build a publication gate

The site should distinguish between:

### Research view

May contain:

- AI hypotheses
- unresolved claims
- contradictory sources
- weak sources
- research failures
- candidate sources

### Published history

Contains only claims that meet publication rules.

Suggested initial gate:

- all **core** claims must be supported or explicitly marked disputed
- no core claim may be contradicted by stronger evidence without disclosure
- important dates/places/people must have direct evidence
- every published factual claim must link to its evidence
- AI-only claims cannot enter published history

Do not silently delete unsupported claims. Either:

- keep them in the research layer, or
- publish them explicitly as uncertain/disputed when historically appropriate.

---

## 7. Phase 5 — Rebuild event pages around claims

Instead of:

> AI narrative → evidence grade

Use:

> Event → claims → evidence → verdict → published narrative

An event page should eventually show:

### What happened

A concise narrative generated from verified claims.

### Evidence

For each important claim:

- claim text
- verdict
- strongest evidence
- source type
- source link
- relevant quotation/excerpt
- contradiction/dispute if present

### Research status

Example:

- 8 core claims
- 7 supported
- 1 partial
- 0 contradicted
- 87% evidence coverage

### AI hypothesis

Keep the original AI draft accessible as research provenance, clearly labelled as such.

---

## 8. Phase 6 — Fix current pipeline weaknesses

Prioritised implementation work:

### P0 — Publication safety

- Do not allow a failed classification step to silently continue as if successful.
- Add an explicit pipeline failure state.
- Do not publish newly generated pages unless their required processing completed.

### P0 — Evidence correctness

- Separate "source found" from "claim verified".
- A contradiction must lower or block publication of the affected claim.
- Never let an old higher grade hide a newly discovered downgrade without an explicit audit trail.

### P1 — Evidence judgement

Current judgement is too dependent on source title/note metadata.

Upgrade the judge input to include the actual retrieved evidence passage whenever available.

The judge must answer:

1. Which exact claim does this passage address?
2. What does the passage actually establish?
3. Does it support, contradict, partially support, or merely contextualise the claim?
4. What uncertainty remains?

### P1 — Source hierarchy

Add source-quality weighting without turning it into a simplistic "government = always correct" rule.

Record both:

- source authority
- claim-specific relevance

### P1 — Independent checking

Increase independent second-model auditing selectively for:

- high-impact claims
- contradictions
- unusual dates
- casualty/number claims
- claims based on weak sources
- claims where models disagree

Agreement rate should be reported separately from historical correctness.

### P2 — Research completeness

Add monitoring for:

- AI drafts with no claims
- claims with no source search
- candidates with no inspected evidence
- claims stuck in unverified state
- events with unresolved core claims
- research failures/retries

---

## 9. Phase 7 — Source strategy upgrade

Replace the current implicit source mix with an explicit source registry.

Each source should have:

- `source_id`
- `institution`
- `source_type`
- `authority_level`
- `coverage`
- `language`
- `stable_url`
- `catalogue/reference_id`
- `retrieval_method`

Create adapters/search strategies where practical for:

- HK Government Records Service
- UK National Archives
- HK Public Libraries
- institutional/university collections
- newspaper archives
- OpenAlex / scholarly metadata

RSS/community historical sites remain valuable for discovery and context, but should not silently dominate verification.

---

## 10. Phase 8 — Website UX

The public website should make the research model understandable without overwhelming normal readers.

### Timeline

Keep the current chronological structure.

Add a visible verification state:

- Verified
- Partially verified
- Disputed
- Research in progress

### Event page

Show:

1. concise verified narrative
2. verification summary
3. key claims
4. evidence links
5. disputes/uncertainty
6. optional "AI original hypothesis" section

### Source page

Make source provenance first-class:

- institution
- source type
- date
- archive/catalogue reference
- linked claims

### Research transparency

Add a simple explanation page:

> How this history is researched

Explain that AI creates hypotheses, while historical evidence determines what is published.

---

## 11. Phase 9 — Migration strategy

Do not rebuild the history from zero.

### Migration sequence

1. Freeze the current AI dataset as the baseline.
2. Assign stable event IDs.
3. Extract existing `Claims to verify` into claim records.
4. Convert existing evidence links into source candidates.
5. Re-run research at claim level.
6. Inspect actual evidence passages.
7. Assign claim verdicts.
8. Generate a verified event narrative.
9. Keep the original AI draft for provenance.
10. Publish only after the publication gate passes.

This allows incremental improvement without losing existing research.

---

## 12. Testing strategy

Add adversarial tests before trusting the upgraded pipeline.

At minimum test:

- source title looks relevant but passage contradicts claim
- source is general background only
- source supports date but not location
- one source supports and another contradicts
- strong source contradicts weak source
- evidence search returns nothing
- source retrieval fails
- judge receives insufficient evidence
- old grade is higher than new evidence
- AI draft contains an unsupported precise number
- publication attempted with unresolved core claim
- classification/research task fails mid-pipeline

The tests must verify **publication safety**, not merely that the pipeline completes.

---

## 13. Implementation order

### Milestone 1 — Data model
- claim schema
- source/evidence schema
- verification states
- event IDs
- migration tooling

### Milestone 2 — Research engine
- claim-based search
- source-family priority
- evidence passage retrieval
- claim-level judgement
- contradiction handling

### Milestone 3 — Publication gate
- verified narrative generation
- unresolved/contradicted claim handling
- safe pipeline failure behaviour

### Milestone 4 — Existing dataset migration
- migrate current AI drafts
- extract claims
- preserve existing research
- backfill evidence

### Milestone 5 — Website
- verification badges
- claim/evidence presentation
- source pages
- AI hypothesis transparency

### Milestone 6 — Quality and operations
- adversarial tests
- coverage metrics
- research backlog
- independent audit sampling

---

## 14. Definition of success

The upgrade is successful when a visitor can take any important statement on the site and answer:

> **"Why do you believe this?"**

The page must lead to the specific historical evidence supporting that statement.

The system should also be able to say:

> **"We don't know yet."**

That is preferable to presenting a plausible AI-generated statement as established Hong Kong history.

---

## 15. Non-goals

Do **not**:

- delete the existing AI draft corpus
- pretend Wikipedia verification is primary evidence
- treat a high evidence count as proof of correctness
- replace all community sources with government sources
- force every historical question into a single "true/false" result
- rewrite all history before the verification model is in place

The first objective is to make the research pipeline trustworthy; content expansion comes after that.
