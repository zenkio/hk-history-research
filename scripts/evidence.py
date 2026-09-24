#!/usr/bin/env python3
"""Evidence engine: attach graded evidence to AI-drafted pages.

For each event page (1841 onward first), the page's title and claims are searched in
three free sources that need no API key:

  A  UK National Archives Discovery: catalogue entries of primary records
     (e.g. CO 129, Hong Kong original correspondence).
  A  Internet Archive: books and official publications printed before 1950.
  B  OpenAlex: scholarly articles and books (with DOI and abstract).

One AI call (role "evidence") then reads the candidates next to the page's claims and
keeps only those genuinely about the page's topic, noting which claim each one
bears on. The page gets a `## Evidence` section and an `evidence_grade` in its
frontmatter (A, B, or "none"); C/D come from the Google-search fact-check
(see seed_history.verify_pages). A grade means "relevant evidence exists and is
linked", not that every sentence has been proven: the section says so on the page.

Progress lives in seed_plan.json under "evidence". Run from seed_history.py, or
standalone: python3 scripts/evidence.py --limit 5
"""
import os
import re
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
from datetime import datetime

from gemini_pool import QuotaExhausted, RequestRejected
from state import PAGE_LOCK, atomic_write

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
PRIMARY_BEFORE = 1950   # printed before this year counts as a primary/contemporary publication
PER_SOURCE = 6
STOPWORDS = set("""a an the of and or in on at to for from by with during after before under over into
its his her their new first second great end rise fall era period age hong kong""".split())

JUDGE_PROMPT = """You are checking evidence for a page of a Hong Kong history website.

Page: {title} ({date})
Claims made on the page:
{claims}

Candidate sources found by search (id, type, year, title, note):
{candidates}

Keep ONLY candidates that are genuinely about this page's specific topic (not just
Hong Kong in general, and not a different event with similar words). For each kept
candidate, say which claims (by number) it is relevant to, judging only from its title
and note. Do not claim a source proves something its description does not cover.

Respond with ONLY this JSON:
{{"relevant": [{{"id": "c3", "claims": [1, 2], "why": "One short sentence"}}],
  "missing": "One sentence on what evidence is still needed, or empty"}}"""


def _get_json(url, accept_json=False):
    headers = {"User-Agent": USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def keywords(title):
    words = [w for w in re.findall(r"[\w'-]+", title) if w.lower() not in STOPWORDS and len(w) > 2]
    return " ".join(words[:8])


# ---- sources -----------------------------------------------------------

def openalex(query, year=None):
    params = {"search": f"{query} Hong Kong", "per-page": str(PER_SOURCE),
              "select": "id,doi,title,publication_year,type,authorships,primary_location,abstract_inverted_index"}
    data = _get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    out = []
    for w in data.get("results", []):
        if not w.get("title"):
            continue
        inv = w.get("abstract_inverted_index") or {}
        words = sorted(((p, word) for word, ps in inv.items() for p in ps))
        abstract = " ".join(word for _, word in words[:60])
        authors = ", ".join(a["author"]["display_name"] for a in (w.get("authorships") or [])[:3]
                            if a.get("author", {}).get("display_name"))
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        url = w.get("doi") or w.get("id")
        out.append({"kind": "scholarship", "grade": "B", "year": w.get("publication_year"),
                    "title": w["title"], "url": url,
                    "cite": f"{authors} ({w.get('publication_year')}). *{w['title']}*." + (f" {venue}." if venue else ""),
                    "note": abstract or venue})
    return out


def national_archives(query):
    params = {"sps.searchQuery": f"{query} Hong Kong", "sps.resultsPageSize": str(PER_SOURCE),
              "sps.heldByCode": "TNA"}
    data = _get_json("https://discovery.nationalarchives.gov.uk/API/search/records?" + urllib.parse.urlencode(params),
                     accept_json=True)
    out = []
    for r in data.get("records", []):
        ref, desc = r.get("reference", ""), re.sub(r"<[^>]+>", "", r.get("description") or r.get("title") or "")
        if not ref:
            continue
        out.append({"kind": "archive record", "grade": "A", "year": r.get("coveringDates", ""),
                    "title": f"{ref}: {desc[:160]}", "url": f"https://discovery.nationalarchives.gov.uk/details/r/{r.get('id')}",
                    "cite": f"The National Archives (UK), {ref}, {r.get('coveringDates', '')}. {desc[:200]}",
                    "note": desc[:300]})
    return out


def internet_archive(query):
    q = f"({query}) AND mediatype:texts AND date:[1800-01-01 TO {PRIMARY_BEFORE - 1}-12-31] AND (\"Hong Kong\" OR Hongkong)"
    params = [("q", q), ("rows", str(PER_SOURCE)), ("output", "json")]
    params += [("fl[]", f) for f in ("identifier", "title", "year", "creator", "description")]
    data = _get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
    out = []
    for d in data.get("response", {}).get("docs", []):
        creator = d.get("creator")
        creator = ", ".join(creator[:2]) if isinstance(creator, list) else (creator or "")
        desc = d.get("description")
        desc = " ".join(desc) if isinstance(desc, list) else (desc or "")
        out.append({"kind": "contemporary publication", "grade": "A", "year": d.get("year"),
                    "title": d.get("title", d["identifier"]), "url": f"https://archive.org/details/{d['identifier']}",
                    "cite": f"{creator + ', ' if creator else ''}*{d.get('title', d['identifier'])}* ({d.get('year', 'n.d.')}), Internet Archive.",
                    "note": re.sub(r"<[^>]+>", "", desc)[:300]})
    return out


SOURCES = [("OpenAlex", openalex), ("National Archives", national_archives), ("Internet Archive", internet_archive)]


# ---- page handling -----------------------------------------------------

def read_page(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm = text.split("---", 2)[1] if text.startswith("---") else ""
    get = lambda k: (re.search(rf'^{k}: *"?(.*?)"?$', fm, re.M) or [None, ""])[1]
    claims = re.findall(r"^- \[ \] (.+)$", text, re.M)
    claims += [c for c in re.findall(r"^- [✅❌❔] \*\*\w+\*\*: (.+?)\.(?: |$)", text, re.M)]
    return text, get("title"), get("date") or get("year"), claims


def evidence_block(kept, missing, model):
    grade = "A" if any(c["grade"] == "A" for c in kept) else ("B" if kept else "none")
    today = datetime.now().strftime("%Y-%m-%d")
    how = (f"filtered for relevance by {model} on {today}. They are about this topic; they have not all been "
           "read in full, so individual claims above may still need checking." if kept else
           f"searched on {today}; nothing relevant found yet.")
    lines = ["## Evidence", "",
             f"> [!abstract] Evidence grade: **{grade}**",
             f"> Sources from the UK National Archives, Internet Archive (pre-{PRIMARY_BEFORE} publications) and "
             f"OpenAlex (scholarship), {how}", ""]
    for label, g in (("Primary sources (grade A)", "A"), ("Scholarship (grade B)", "B")):
        items = [c for c in kept if c["grade"] == g]
        if items:
            lines += [f"### {label}", ""]
            for c in items:
                claims = f" (claims {', '.join(map(str, c['claims']))})" if c.get("claims") else ""
                lines.append(f"- [{c['cite']}]({c['url']}){claims}: {c.get('why', '')}")
            lines.append("")
    if missing:
        lines += [f"**Still needed:** {missing}", ""]
    return grade, lines


def write_evidence(path, grade, lines):
    with PAGE_LOCK:
        return _write_evidence_unlocked(path, grade, lines)


def _write_evidence_unlocked(path, grade, lines):
    text = read_page(path)[0]
    block = "\n".join(lines) + "\n"
    text = re.sub(r"\n## Evidence\n.*?(?=\n## |\nPart of: |\Z)", "\n", text, flags=re.S)
    if "\nPart of: " in text:
        i = text.rindex("\nPart of: ")
        text = text[:i] + "\n" + block + text[i:]
    else:
        text = text.rstrip() + "\n\n" + block
    if re.search(r"^evidence_grade:", text, re.M):
        text = re.sub(r"^evidence_grade:.*$", f"evidence_grade: {grade}", text, count=1, flags=re.M)
    else:
        text = re.sub(r"^(confidence:.*)$", rf"\1\nevidence_grade: {grade}", text, count=1, flags=re.M)
    tag = f'"evidence-{grade.lower()}"'
    text = re.sub(r'"evidence-(a|b|none)", ', "", text)
    text = re.sub(r"^tags: \[", f"tags: [{tag}, ", text, count=1, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def gather(query):
    """Candidates from every source; a source that fails is skipped, not fatal."""
    found, failed = [], []
    for name, fn in SOURCES:
        try:
            found += fn(query)
        except Exception as e:
            failed.append(name)
            print(f"  [evidence] {name} failed: {str(e)[:100]}")
        time.sleep(0.5)  # polite to free APIs
    return found, failed


def evidence_for_page(pool, path):
    """Returns the grade written, or None if nothing could be searched (retry next run)."""
    _, title, date, claims = read_page(path)
    candidates, failed = gather(keywords(title))
    if len(failed) == len(SOURCES):
        return None
    if not candidates:
        grade, lines = evidence_block([], "", "search")
        write_evidence(path, grade, lines)
        return grade
    for i, c in enumerate(candidates, 1):
        c["id"] = f"c{i}"
    listing = "\n".join(f"{c['id']} | {c['kind']} | {c['year']} | {c['title'][:150]} | {c['note'][:220]}"
                        for c in candidates)
    claim_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1)) or "(no explicit claims; judge by topic)"
    data, model, _ = pool.generate_json("evidence", JUDGE_PROMPT.format(
        title=title, date=date, claims=claim_text, candidates=listing))
    by_id = {c["id"]: c for c in candidates}
    kept = []
    for r in data.get("relevant", []) if isinstance(data, dict) else []:
        c = by_id.get(str(r.get("id")))
        if c and c not in kept:
            c["claims"] = [n for n in r.get("claims", []) if isinstance(n, int)]
            c["why"] = r.get("why", "")
            kept.append(c)
    grade, lines = evidence_block(kept, data.get("missing", "") if isinstance(data, dict) else "", model)
    write_evidence(path, grade, lines)
    return grade


def evidence_batch(pool, done_map, events, deadline, limit=None, save=None):
    """Attach evidence to event pages in `events` order; progress in done_map (rel -> grade)."""
    done = 0
    for ev in events:
        rel = ev.get("file")
        if not rel or rel in done_map or ev.get("status") != "done":
            continue
        if time.time() > deadline or (limit is not None and done >= limit):
            break
        path = os.path.join(TIMELINE_DIR, rel)
        if not os.path.exists(path):
            continue
        try:
            grade = evidence_for_page(pool, path)
        except QuotaExhausted:
            break
        except RequestRejected as e:
            print(f"[evidence] {rel} rejected: {str(e)[:100]}")
            done_map[rel] = "error"
            continue
        if grade is None:
            print("[evidence] every source unreachable; stopping for this run")
            break
        done_map[rel] = grade
        done += 1
        print(f"[evidence] {rel}: grade {grade}")
        if save:
            save(done_map)
    return done


def write_status_page(events, grades):
    """content/00_Meta/Evidence_Status.md: how much of the site is backed by evidence."""
    from collections import Counter
    total = sum(1 for e in events if e.get("status") == "done")
    c = Counter(grades.values())
    lines = ["---", 'title: "Evidence status"', 'description: "How many AI-drafted pages have archive or scholarly evidence attached."',
             "---", "",
             f"_Updated {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC._", "",
             "| Grade | Meaning | Pages |", "|---|---|---|",
             f"| [[tags/evidence-a\\|A]] | Primary sources linked (archives, contemporary publications) | {c.get('A', 0)} |",
             f"| [[tags/evidence-b\\|B]] | Scholarship linked (articles, academic books) | {c.get('B', 0)} |",
             f"| [[tags/evidence-none\\|none]] | Searched, nothing relevant found yet | {c.get('none', 0)} |",
             f"| – | Not searched yet | {total - len(grades)} |", "",
             "Wikipedia is used only as a cross-check and never counts as evidence, because anyone can edit it: "
             "[[tags/wikipedia-checked|compared with Wikipedia]]; "
             "[[tags/wikipedia-differs|draft and Wikipedia differ]] (either may be wrong: these are the pages "
             "most worth checking against primary sources).", ""]
    path = os.path.join(PROJECT_ROOT, "content", "00_Meta", "Evidence_Status.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, "\n".join(lines))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gemini_pool import ModelPool
    import state
    from seed_history import load_plan, by_priority
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--minutes", type=float, default=30)
    args = ap.parse_args()
    plan = load_plan()
    grades = state.load("evidence")
    n = evidence_batch(ModelPool(), grades, by_priority(plan["events"]), time.time() + args.minutes * 60,
                       limit=args.limit, save=lambda d: state.save("evidence", d))
    write_status_page(plan["events"], grades)
    print(f"Evidence attached to {n} pages")
