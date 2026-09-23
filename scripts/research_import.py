#!/usr/bin/env python3
"""Import Gemini Deep Research results from research/inbox/ as evidence.

The owner runs research/prompts/01-evidence-backbone.md in Gemini Deep Research and
saves each answer as research/inbox/<name>.md. Each table row (event, date, grade A/B/C
sources, disputes) is matched to an event page by year and title words. Every URL and
DOI in the row is checked, since Deep Research can cite sources that do not exist, and
only rows with at least one working link are attached, as a `## Research notes`
section. A working grade A link raises the page's evidence grade to A; a grade B link
raises "none" to B.

Rows that match no page are listed in research/unmatched.md: they are candidate events
the timeline is missing. Processed files move to research/inbox/done/.
"""
import os
import re
import glob
import shutil
import urllib.request
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(PROJECT_ROOT, "research", "inbox")
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
UNMATCHED = os.path.join(PROJECT_ROOT, "research", "unmatched.md")
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
URL_RE = re.compile(r"https?://[^\s)\]>|,;\"']+")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s)\]>|,;\"']+)")
STOP = set("the of and in to a an for on at by with from hong kong british".split())


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


def checked_links(cell):
    links = [u.rstrip(".") for u in URL_RE.findall(cell)]
    links += [f"https://doi.org/{d.rstrip('.')}" for d in DOI_RE.findall(cell) if not any(d in u for u in links)]
    return [(u, link_ok(u)) for u in dict.fromkeys(links)]


def research_block(row, source_name, results):
    lines = ["## Research notes", "",
             f"> [!note] From Gemini Deep Research ({source_name}), imported {datetime.now().strftime('%Y-%m-%d')}. "
             "Links were checked automatically: ✓ reachable, ✗ not reachable (may be wrong).", ""]
    for label, cell, links in results:
        if not cell or cell.lower().startswith("none"):
            continue
        marks = " ".join(f"[{'✓' if ok else '✗'}]({u})" for u, ok in links)
        lines.append(f"- **{label}:** {cell}" + (f" {marks}" if marks else ""))
    disputes = col(row, "dispute", "myth")
    if disputes and not disputes.lower().startswith("none"):
        lines += ["", f"**Disputes or myths:** {disputes}"]
    return "\n".join(lines) + "\n\n"


def attach(path, block, best_grade):
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


def import_inbox(plan):
    files = sorted(glob.glob(os.path.join(INBOX, "*.md")))
    if not files:
        return 0
    events = plan.get("events", [])
    grades = plan.setdefault("evidence", {})
    unmatched, attached = [], 0
    for fpath in files:
        name = os.path.basename(fpath)
        with open(fpath, encoding="utf-8") as f:
            rows = parse_tables(f.read())
        print(f"[research] {name}: {len(rows)} rows")
        for row in rows:
            ev = match_page(row, events)
            if not ev:
                unmatched.append((name, row))
                continue
            results = [(label, col(row, key), checked_links(col(row, key)))
                       for label, key in (("Grade A", "grade a"), ("Grade B", "grade b"), ("Grade C", "grade c"))]
            if not any(ok for _, _, links in results for _, ok in links):
                unmatched.append((name, {**row, "_note": f"matched {ev['file']} but no link was reachable"}))
                continue
            best = next((g for g, (_, _, links) in zip("ABC", results) if any(ok for _, ok in links)), None)
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
                f.write(f"- ({name}) **{col(row, 'event')}** {col(row, 'date')}: {col(row, 'what happened')}"
                        + (f" _{row['_note']}_" if row.get("_note") else "") + "\n")
    return attached
