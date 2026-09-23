# Prompt 01: Evidence backbone, one era per run

Run once per era, replacing `{ERA}` and `{YEARS}` with a row below. Save each answer
to `research/inbox/01-{YEARS}.md`.

| ERA | YEARS |
|---|---|
| Canton trade, First Opium War and the British occupation of Hong Kong Island | 1834-1842 |
| The early colony | 1842-1860 |
| Kowloon and the Victorian colony | 1860-1898 |
| The New Territories lease and the early 20th century | 1898-1918 |
| Interwar Hong Kong | 1919-1941 |
| Battle of Hong Kong and the Japanese occupation | 1941-1945 |
| Postwar recovery, refugees and industrialisation | 1945-1966 |
| Riots and the MacLehose reforms | 1966-1982 |
| Sino-British negotiations and the transition | 1982-1997 |
| The early HKSAR | 1997-2008 |
| Political contention and protest | 2008-2020 |
| The National Security Law era | 2020-present |

---

## Prompt (copy from here)

You are a research assistant building an evidence base for a public Hong Kong history website.
Every statement on the site must be traceable to a source, so sources matter more than prose.

Era: **{ERA} ({YEARS})**

Task:
1. Identify the 25 most important events, decisions, laws, disasters and social changes in Hong Kong during this era. Include social, economic and daily-life history, not only politics and war.
2. For each one, find the strongest evidence available, in this order of preference:
   - **A (primary):** archival records (UK National Archives CO 129 / FO files with references), Hong Kong Government Gazette, Blue Books, Legislative Council records or Hansard, contemporary newspapers (with title and date), treaties, official reports.
   - **B (scholarship):** peer-reviewed articles and academic books, with author, year, title, publisher or journal, and DOI or stable URL. Include the Journal of the Royal Asiatic Society Hong Kong Branch where relevant.
   - **C (reference):** Hong Kong government, museum or university pages; encyclopedias.
3. Record where historians disagree, and any common myths or popular claims that the sources contradict.

Output format (strict; this is parsed by a script):

For each event, one row in this Markdown table:

| # | Event | Date (YYYY or YYYY-MM-DD) | What happened (one sentence) | Grade A source | Grade B source | Grade C source | Disputes or myths |
|---|---|---|---|---|---|---|---|

- Put full citations in the source cells: title, author or issuing body, date, archive reference, and URL if one exists.
- Write "none found" rather than leaving a cell empty or guessing.
- Do not invent references. If you are unsure a source exists, leave it out.

After the table, add:
- **## Key sources for this era**: the 5–10 most useful collections, books or archives, with URLs.
- **## Gaps**: important topics where you could not find good evidence.
