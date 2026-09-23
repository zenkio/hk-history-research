# Research hand-offs (Gemini Deep Research)

The owner runs prompts from `prompts/` in Gemini Deep Research and saves each result
as a Markdown file in `inbox/`, named after the prompt (for example
`inbox/01-1841-1860.md`). The evidence engine (see BACKLOG.md, "Deep Research import")
reads the tables, attaches the sources to matching pages, and moves processed files
to `inbox/done/`.

Rules for results:
- Keep the table format the prompt asks for; the importer depends on it.
- Paste the full answer, including the source list with URLs.
- One era per file.
