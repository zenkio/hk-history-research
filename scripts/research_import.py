#!/usr/bin/env python3
"""Import Gemini Deep Research results from research/inbox/ as evidence.

The owner runs research/prompts/01-evidence-backbone.md in Gemini Deep Research and
saves each answer as research/inbox/<name>.md. Each table row (event, date, grade A/B/C
sources, disputes) is matched to an event page by year and title words. Deep Research
can cite sources that do not exist, so every reference is checked:
  - DOIs against Crossref and ISBNs against Open Library: the real title must match
    the cited one, not just resolve;
  - "[cite: N]" numbers are resolved through the numbered source list at the end of the
    answer (unwrapping google.com/url redirects) and link-checked; piracy/document-dump
    sites are skipped;
  - UK National Archives references (CO 129/1, FO 17/32, ...) become catalogue search
    links, marked as not independently verified.
Only rows with at least one verified reference are attached, as a `## Research notes`
section. A working grade A link raises the page's evidence grade to A; a grade B link
raises "none" to B.

Rows that match no page are listed in research/unmatched.md: they are candidate events
the timeline is missing. Processed files move to research/inbox/done/.
"""
import os
import re
import glob
import shutil
import json
import urllib.parse
import urllib.request
from datetime import datetime

from state import PAGE_LOCK

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(PROJECT_ROOT, "research", "inbox")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
UNMATCHED = os.path.join(PROJECT_ROOT, "research", "unmatched.md")
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
URL_RE = re.compile(r"https?://[^\s)\]>|,;\"']+")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s)\]>|,;\"']+)")
STOP = set("the of and in to a an for on at by with from hong kong british".split())
ISBN_RE = re.compile(r"ISBN[:\s]*((?:97[89][-\s]?)?\d[\d\s-]{8,15}[\dXx])")
CITE_RE = re.compile(r"\s*\[cite:\s*([\d,\s]+)\]")
ARCHIVE_RE = re.compile(r"\b((?:CO|FO|ADM|WO|HO|T|MFQ)\s?\d{1,4}/\d{1,5})\b")
REF_LINE_RE = re.compile(r"^\s*(\d{1,3})\.\s+(.+?),?\s*\[(https?://[^\]]+)\]", re.M)
SKIP_DOMAINS = re.compile(r"dokumen\.pub|scribd\.com|studocu|pdfcoffee|z-lib|libgen|annas-archive|coursehero", re.I)


def parse_tables(text):
    """Rows of every Markdown table whose header has an Event column, as dicts keyed by header."""
    rows, header = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            if any("event" in c.lower() for c in cells):
                header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def col(row, *names):
    for key, val in row.items():
        if any(n in key for n in names):
            return val
    return ""


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def match_page(row, events):
    year = re.search(r"\d{4}", col(row, "date") or "")
    year = int(year.group()) if year else None
    want = words(col(row, "event"))
    best, score = None, 0.0
    for ev in events:
        if not ev.get("file") or (year and isinstance(ev.get("year"), int) and abs(ev["year"] - year) > 1):
            continue
        have = words(ev["title"])
        s = len(want & have) / max(1, len(want | have))
        if s > score:
            best, score = ev, s
    return best if score >= 0.25 else None


def _json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def link_ok(url):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=12) as r:
                if r.status < 400:
                    return True
        except Exception:
            continue
    return False


def title_matches(real, cited_text):
    """True when most words of the real title appear in the citation (catches DOIs/ISBNs that
    resolve to a different work)."""
    want = words(real)
    return bool(want) and len(want & words(cited_text)) / len(want) >= 0.6


def check_doi(doi, cell):
    try:
        real = (_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")["message"].get("title") or [""])[0]
    except Exception:
        return None, "DOI not found"
    return title_matches(real, cell), f"DOI resolves to: {real[:90]}"


def check_isbn(isbn, cell):
    try:
        real = _json(f"https://openlibrary.org/isbn/{isbn}.json").get("title", "")
    except Exception:
        return None, "ISBN not found"
    return title_matches(real, cell), f"ISBN is: {real[:90]}"


def unwrap(url):
    """google.com/url?q=<real> redirects (as Gemini exports them) -> the real URL."""
    url = url.replace("&amp;", "&")
    if "google.com/url" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
        if q:
            return q[0]
    return url


def reference_list(text):
    """{n: (title, url)} from the numbered source list Deep Research appends."""
    return {int(n): (title.strip(), unwrap(url)) for n, title, url in REF_LINE_RE.findall(text)}


def check_cell(cell, refs):
    """Verified references in one cell: [(label, url or None, ok, note)]."""
    out = []
    for doi in dict.fromkeys(d.rstrip(".") for d in DOI_RE.findall(cell)):
        ok, note = check_doi(doi, cell)
        out.append(("DOI", f"https://doi.org/{doi}", ok, note))
    for raw in dict.fromkeys(ISBN_RE.findall(cell)):
        isbn = re.sub(r"[^\dXx]", "", raw)
        ok, note = check_isbn(isbn, cell)
        out.append(("ISBN", f"https://openlibrary.org/isbn/{isbn}", ok, note))
    urls = [unwrap(u).rstrip(".") for u in URL_RE.findall(cell)]
    for m in CITE_RE.findall(cell):
        urls += [refs[int(n)][1] for n in re.findall(r"\d+", m) if int(n) in refs]
    for u in dict.fromkeys(urls):
        if "doi.org/" in u or SKIP_DOMAINS.search(u):
            continue
        out.append(("link", u, link_ok(u), ""))
    for ref in dict.fromkeys(ARCHIVE_RE.findall(cell)):
        q = urllib.parse.quote(ref)
        out.append(("archive ref", f"https://discovery.nationalarchives.gov.uk/results/r?_q={q}", None,
                    f"{ref}: catalogue search, not independently verified"))
    return out


def research_block(row, source_name, results):
    lines = ["## Research notes", "",
             f"> [!note] From Gemini Deep Research ({source_name}), imported {datetime.now().strftime('%Y-%m-%d')}. "
             "References were checked automatically: ✓ verified (DOI/ISBN title matches, or link works), "
             "✗ failed (wrong or unreachable, treat with suspicion), ? not independently verifiable.", ""]
    for label, cell, checks in results:
        if not cell or cell.lower().startswith("none"):
            continue
        cell = CITE_RE.sub("", cell).strip()
        marks = " ".join(f"[{kind} {'✓' if ok else '✗' if ok is False else '?'}]({u})"
                         + (f" _({note})_" if note and ok is False else "")
                         for kind, u, ok, note in checks)
        lines.append(f"- **{label}:** {cell}" + (f" {marks}" if marks else ""))
    disputes = CITE_RE.sub("", col(row, "dispute", "myth")).strip()
    if disputes and not disputes.lower().startswith("none"):
        lines += ["", f"**Disputes or myths:** {disputes}"]
    return "\n".join(lines) + "\n\n"


def attach(path, block, best_grade):
    with PAGE_LOCK:
        return _attach_unlocked(path, block, best_grade)


def _attach_unlocked(path, block, best_grade):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"\n## Research notes\n.*?(?=\n## |\nPart of: |\Z)", "\n", text, flags=re.S)
    anchor = "\n## Evidence" if "\n## Evidence" in text else ("\nPart of: " if "\nPart of: " in text else None)
    if anchor:
        i = text.index(anchor)
        text = text[:i] + "\n" + block + text[i + 1:] if anchor == "\n## Evidence" else text[:i] + "\n" + block + text[i:]
    else:
        text = text.rstrip() + "\n\n" + block
    current = (re.search(r"^evidence_grade: *(\w+)", text, re.M) or [None, "none"])[1]
    rank = {"A": 2, "B": 1}
    if best_grade and rank.get(best_grade, 0) > rank.get(current, 0):
        if re.search(r"^evidence_grade:", text, re.M):
            text = re.sub(r"^evidence_grade:.*$", f"evidence_grade: {best_grade}", text, count=1, flags=re.M)
        else:
            text = re.sub(r"^(confidence:.*)$", rf"\1\nevidence_grade: {best_grade}", text, count=1, flags=re.M)
        text = re.sub(r'"evidence-(a|b|none)", ', "", text)
        text = re.sub(r"^tags: \[", f'tags: ["evidence-{best_grade.lower()}", ', text, count=1, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return current if not best_grade or rank.get(best_grade, 0) <= rank.get(current, 0) else best_grade


def import_inbox(events, grades):
    """Import every file in research/inbox/; grades (rel -> evidence grade) is updated in place."""
    files = sorted(glob.glob(os.path.join(INBOX, "*.md")))
    if not files:
        return 0
    unmatched, attached = [], 0
    for fpath in files:
        name = os.path.basename(fpath)
        with open(fpath, encoding="utf-8") as f:
            text = f.read()
        rows, refs = parse_tables(text), reference_list(text)
        print(f"[research] {name}: {len(rows)} rows")
        for row in rows:
            ev = match_page(row, events)
            if not ev:
                unmatched.append((name, row))
                continue
            results = [(label, col(row, key), check_cell(col(row, key), refs))
                       for label, key in (("Grade A", "grade a"), ("Grade B", "grade b"), ("Grade C", "grade c"))]
            if not any(ok for _, _, checks in results for _, _, ok, _ in checks):
                unmatched.append((name, {**row, "_note": f"matched {ev['file']} but no reference could be verified"}))
                continue
            best = next((g for g, (_, _, checks) in zip("ABC", results) if any(ok for _, _, ok, _ in checks)), None)
            best = best if best in ("A", "B") else None
            grades[ev["file"]] = attach(os.path.join(TIMELINE_DIR, ev["file"]), research_block(row, name, results), best)
            attached += 1
            print(f"[research] {ev['file']} <- {col(row, 'event')[:60]}")
        os.makedirs(os.path.join(INBOX, "done"), exist_ok=True)
        shutil.move(fpath, os.path.join(INBOX, "done", name))
    if unmatched:
        with open(UNMATCHED, "a", encoding="utf-8") as f:
            f.write(f"\n## Imported {datetime.now().strftime('%Y-%m-%d')}\n\n"
                    "Rows that matched no timeline page, or had no working link. Candidates for new events.\n\n")
            for name, row in unmatched:
                f.write(f"- ({name}) **{col(row, 'event')}** {col(row, 'date')}: {CITE_RE.sub('', col(row, 'what happened')).strip()}"
                        + (f" _{row['_note']}_" if row.get("_note") else "") + "\n")
    return attached
