# HK History Research: pipeline

The code behind **[HK History Research](https://hkhistory.zenkio.uk/)**, a
history of Hong Kong from 1841 to today in which every page carries an **evidence grade** and links
to the archive records, newspapers and scholarship behind it.

This repository holds only the code: the pipeline that drafts, checks and grades pages, and the
site build. The content, research notes and evidence data live in a private repository and are
not published here.

## How a page earns its grade

| Grade | Evidence |
|---|---|
| A | Primary sources: archive records, contemporary newspapers and publications |
| B | Scholarship: peer-reviewed papers, academic books |
| none | Searched, nothing specific to the event found yet |

- AI-drafted text is labelled `ai-draft` until evidence backs it.
- A source counts only if it *supports* or *contradicts* a specific claim; works on the general
  subject are listed as background reading and grade nothing.
- Wikipedia is a cross-check and a pointer to sources, never evidence.
- A share of judgements is repeated by a second AI model; the agreement rate is published on the site.

## Licence

Not open source. © Zenkio, all rights reserved: see `LICENSE`. The site is built with
[Quartz](https://quartz.jzhao.xyz/) by Jacky Zhao, MIT licence (`quartz/LICENSE.txt`).
