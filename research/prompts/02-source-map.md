# Prompt 02: Source map (run once)

Goal: a list of the primary-source (grade A) collections for Hong Kong history, with what a
program needs to search them. This is read by Claude to build new evidence sources in
`scripts/evidence.py`; it is not imported automatically.

Save the answer as `research/source-map.md` (**not** in `inbox/`: the importer only reads
event tables). Every URL in it is tested before anything is built on it.

---

## Prompt (copy from here)

You are helping build an automated evidence checker for a public, non-commercial Hong Kong
history website (core period 1841 to today). A Python program will search online collections
for each historical event and link the matching primary source. I need a map of where
primary sources for Hong Kong history can be found online, and how a program can search them.

List every collection you can find that holds **primary sources** for Hong Kong history:
government records and publications (Hong Kong and UK), legislative records, court records,
contemporary newspapers (English and Chinese), treaties, maps, photographs, census and
statistics, missionary and company archives, oral histories. Include Hong Kong, UK, Chinese,
US, Australian and other holders. Include both free and paid collections, but mark which is which.

Output format (strict; one row per collection):

| # | Collection | Holder | What it contains | Years covered | Language | Access | Digitised | Search URL | Machine access | Terms for automated use |
|---|---|---|---|---|---|---|---|---|---|---|

Column rules:
- **Access**: `free`, `free with registration`, `library subscription`, or `paid`.
- **Digitised**: `full text`, `page images only`, `catalogue only` (documents only in a reading room), or `mixed`.
- **Search URL**: a real search results URL for the query `Praya reclamation` (or the nearest
  equivalent the site supports), so the URL pattern is visible. Write "none" if searching needs a form or login.
- **Machine access**: any API, OAI-PMH, IIIF, JSON/CSV export, RSS, or "none known". Give the documentation URL if there is one.
- **Terms for automated use**: what the site's terms or robots rules say about automated searching, or "not stated".

Rules:
- Only list collections you can confirm exist, with their real URLs. Do not invent URLs or APIs; write "unknown" instead.
- Cover at least: Hong Kong Government Reports Online (HKU), Historical Laws of Hong Kong Online, Government Records Service / Public Records Office (HKRS series), Hong Kong Public Libraries MMIS Old HK Newspapers, Legislative Council records, the Government Gazette after 1941, UK National Archives (CO 129, FO 17, CO 1030 and others), British Library, SOAS missionary archives, HSBC and Jardine Matheson archives, Hong Kong Memory, HKU and CUHK special collections, Trove (Australia), Chronicling America and other newspaper archives that covered Hong Kong, and oral history collections.

After the table, add:
- **## Best five for automation**: the five collections that are both strongest as evidence and easiest for a program to search free of charge, with one sentence each on why.
- **## Chinese-language sources**: the most important Chinese-language primary collections (newspapers such as 華僑日報 and 工商日報, government Chinese notices), and how they can be searched.
- **## Not online**: important primary collections that exist only in reading rooms, so the site can point readers to them.
