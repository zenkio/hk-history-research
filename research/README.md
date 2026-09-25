# Research hand-offs (Gemini Deep Research)

The owner runs prompts from `prompts/` in Gemini Deep Research and saves each result
as a Markdown file in `inbox/`, named after the prompt (for example
`inbox/01-1841-1860.md`). The evidence engine (see BACKLOG.md, "Deep Research import")
reads the tables, attaches the sources to matching pages, and moves processed files
to `inbox/done/`.

Prompts:
- `01-evidence-backbone.md`: one era per run, saved to `inbox/01-<years>.md` (imported automatically).
- `02-source-map.md`: run once, saved to `research/source-map.md` (not `inbox/`). It lists the
  primary-source collections and how a program can search them; Claude builds new evidence
  sources from it after testing every URL.

Rules for results:
- Keep the table format the prompt asks for; the importer depends on it.
- Paste the full answer, including the numbered source list with URLs at the end
  (without it, `[cite: N]` references cannot be checked and the row is not attached).
- To redo an era, upload the new answer under the same file name in `inbox/` (it replaces the old one).
- One era per file.
