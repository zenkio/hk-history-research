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
import random
import urllib.error
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
# Words that describe the event rather than name it. Left in, they narrow the search to works
# using the same word: run 31 found nothing for "Disastrous Shek Kip Mei Fire".
STOPWORDS |= set("""founding foundation opening establishment establish established restoration introduction
launch launched start beginning begins begin creation formation formal signing outbreak arrival
construction completion inauguration enactment passage proclamation implementation emergence
declared appointment devastating disastrous massive major historic landmark widespread systemic
extreme mandatory elite""".split())

JUDGE_PROMPT = """You are checking evidence for a page of a Hong Kong history website.

Page: {title} ({date})
Claims made on the page:
{claims}

Candidate sources found by search (id, type, year, title, note):
{candidates}

Keep a candidate ONLY if it is about THIS event: the same event, place and period. A work on
the general subject is not evidence for a specific event (a study of Chinese ancestor worship is
not evidence for one Hong Kong ancestral hall; a history of the Qing collapse is not evidence for
what happened in Hong Kong in 1911). When unsure, leave it out.

Claim 1 is the event itself. An archive record or contemporary publication whose title or note
shows it documents this event, or a scholarly work specifically about this event, supports claim 1
(and any other claim its title or note bears on). A work that only mentions the event in passing is
background.

For each kept candidate, judging only from its title and note:
- "relation": "supports" if it bears directly on one or more numbered claims and agrees with them;
  "contradicts" if it bears on a claim and disagrees (e.g. a different date, place or outcome);
  "background" if it is about this event but does not bear on any specific claim.
- "claims": the claim numbers it bears on (empty for background).
- "why": one sentence naming what in the title or note bears on the claim. Say no more than the
  title and note show.

Respond with ONLY this JSON:
{{"relevant": [{{"id": "c3", "relation": "supports", "claims": [1, 2], "why": "One short sentence"}}],
  "missing": "One sentence on what evidence is still needed, or empty"}}"""

COUNTED = ("supports", "contradicts")  # relations that earn a grade; "background" is listed only
AUDIT_SHARE = 0.05  # share of judged pages that a second model judges again, to measure agreement
_rng = random.Random()


def _get_json(url, accept_json=False):
    """GET JSON. A 429/503 waits for Retry-After (capped) and tries again: OpenAlex answered
    429 on 96 of 150 pages in run 27 when every request was sent without waiting."""
    headers = {"User-Agent": USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 2:
                raise
            ra = e.headers.get("Retry-After") or ""
            time.sleep(min(int(ra) if ra.isdigit() else 5 * (attempt + 1), 30))


def keywords(title):
    words = [w for w in re.findall(r"[\w'-]+", title) if w.lower() not in STOPWORDS and len(w) > 2]
    return " ".join(words[:8])


# ---- sources -----------------------------------------------------------

def openalex(query, year=None):
    params = {"search": f"{query} Hong Kong", "per-page": str(PER_SOURCE),
              "select": "id,doi,title,publication_year,type,authorships,primary_location,abstract_inverted_index"}
    # Since Feb 2026 OpenAlex allows only 100 credits a day without a key (a search costs 10),
    # and 100,000 with a free key from openalex.org/settings/api.
    key = (os.environ.get("OPENALEX_API_KEY") or "").strip()
    if key:
        params["api_key"] = key
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


def grade_of(kept):
    """A if a primary source supports or contradicts a claim, B if only scholarship does; background
    reading grades nothing (the 2026-09-28 audit found general-topic works graded as evidence)."""
    counted = [c for c in kept if c.get("relation") in COUNTED]
    return "A" if any(c["grade"] == "A" for c in counted) else ("B" if counted else "none")


def evidence_block(kept, missing, model):
    grade = grade_of(kept)
    today = datetime.now().strftime("%Y-%m-%d")
    how = (f"judged by {model} on {today}. Only sources that support or contradict a claim count towards the grade; "
           "they have not all been read in full, so individual claims above may still need checking." if kept else
           f"searched on {today}; nothing relevant found yet.")
    lines = ["## Evidence", "",
             f"> [!abstract] Evidence grade: **{grade}**",
             f"> Sources from the UK National Archives, Internet Archive (pre-{PRIMARY_BEFORE} publications) and "
             f"OpenAlex (scholarship), {how}", ""]
    counted = [c for c in kept if c.get("relation") in COUNTED]
    for label, g in (("Primary sources (grade A)", "A"), ("Scholarship (grade B)", "B")):
        items = [c for c in counted if c["grade"] == g]
        if items:
            lines += [f"### {label}", ""]
            for c in items:
                claims = ", ".join(map(str, c.get("claims") or []))
                what = (f"⚠ **contradicts** claim {claims}" if c["relation"] == "contradicts"
                        else f"supports claim {claims}" if claims else "supports")
                lines.append(f"- [{c['cite']}]({c['url']}) ({what}): {c.get('why', '')}")
            lines.append("")
    background = [c for c in kept if c.get("relation") not in COUNTED]
    if background:
        lines += ["### Background reading (does not count towards the grade)", ""]
        lines += [f"- [{c['cite']}]({c['url']}): {c.get('why', '')}" for c in background]
        lines.append("")
    if missing:
        lines += [f"**Still needed:** {missing}", ""]
    return grade, lines


def write_evidence(path, grade, lines, contradicts=False):
    with PAGE_LOCK:
        return _write_evidence_unlocked(path, grade, lines, contradicts)


def _write_evidence_unlocked(path, grade, lines, contradicts=False):
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
    text = re.sub(r'"evidence-(a|b|none|contradicts)", ', "", text)
    if contradicts:  # a source disagrees with the draft: a lead for the myths and disputes hub
        tag += ', "evidence-contradicts"'
    text = re.sub(r"^tags: \[", f"tags: [{tag}, ", text, count=1, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


SOURCE_FAILS_TO_REST = 3  # consecutive failures before a source is skipped for the rest of the run
_source_fails = {}


def gather(query):
    """Candidates from every source. A source that fails is skipped, not fatal; one that keeps
    failing is rested for the rest of the run (and still reported as failed for each page)."""
    found, failed = [], []
    for name, fn in SOURCES:
        if _source_fails.get(name, 0) >= SOURCE_FAILS_TO_REST:
            failed.append(name)
            continue
        try:
            got = fn(query)
            for c in got:
                c["source"] = name
            found += got
            _source_fails[name] = 0
        except Exception as e:
            failed.append(name)
            _source_fails[name] = _source_fails.get(name, 0) + 1
            rest = " - resting it for this run" if _source_fails[name] >= SOURCE_FAILS_TO_REST else ""
            print(f"  [evidence] {name} failed: {str(e)[:100]}{rest}")
        time.sleep(1.0)  # polite to free APIs
    return found, failed


def search_summary(query, candidates, failed, kept):
    """One log line per page: what each source returned and how many the AI kept, so a page
    graded "none" shows whether the search or the AI filter found nothing."""
    counts = [f"{name} {'failed' if name in failed else sum(c.get('source') == name for c in candidates)}"
              for name, _ in SOURCES]
    judged = "nothing to judge" if kept is None else f"AI kept {kept}"
    return f'  [evidence] "{query}": {", ".join(counts)}; {judged}'


def event_claims(title, date, claims):
    """The page's claims, led by the event itself. Without it an archive file named after the event
    could only be background (the judge found no detailed claim its title confirms), and a page with
    no claims list could never earn a grade."""
    return [f"{title} took place in Hong Kong ({date})"] + list(claims)


def evidence_for_page(pool, path):
    """Returns the grade written; None if nothing could be searched (stop this run); "retry" if a
    source failed and nothing was found, so the page is not wrongly recorded as searched."""
    _, title, date, claims = read_page(path)
    query = keywords(title)
    candidates, failed = gather(query)
    if len(failed) == len(SOURCES):
        return None
    if not candidates and failed:
        return "retry"
    if not candidates:
        print(search_summary(query, candidates, failed, None))
        grade, lines = evidence_block([], "", "search")
        write_evidence(path, grade, lines)
        return grade
    for i, c in enumerate(candidates, 1):
        c["id"] = f"c{i}"
    listing = "\n".join(f"{c['id']} | {c['kind']} | {c['year']} | {c['title'][:150]} | {c['note'][:220]}"
                        for c in candidates)
    claim_text = "\n".join(f"{i}. {c}" for i, c in enumerate(event_claims(title, date, claims), 1))
    prompt = JUDGE_PROMPT.format(title=title, date=date, claims=claim_text, candidates=listing)
    data, model, _ = pool.generate_json("evidence", prompt)
    kept = judged(data, candidates)
    print(search_summary(query, candidates, failed, len(kept)))
    grade, lines = evidence_block(kept, data.get("missing", "") if isinstance(data, dict) else "", model)
    if grade == "none" and failed:
        return "retry"  # a source we could not search may still hold evidence
    if _rng.random() < AUDIT_SHARE:
        audit(pool, path, prompt, candidates, kept, model)
    write_evidence(path, grade, lines, contradicts=any(c.get("relation") == "contradicts" for c in kept))
    return grade


def judged(data, candidates):
    """The candidates the model kept, each with relation, claims and why. A relation the model did not
    give, or "supports" with no claim named, is treated as background: it cannot raise the grade."""
    by_id = {c["id"]: dict(c) for c in candidates}
    kept = []
    for r in data.get("relevant", []) if isinstance(data, dict) else []:
        c = by_id.pop(str(r.get("id")), None)
        if not c:
            continue
        c["claims"] = [n for n in r.get("claims") or [] if isinstance(n, int)]
        c["why"] = r.get("why", "")
        relation = str(r.get("relation", "")).lower()
        c["relation"] = relation if relation in COUNTED and c["claims"] else "background"
        kept.append(c)
    return kept


def decisions(kept, candidates):
    """Per candidate: out / background / supports / contradicts, for comparing two judges."""
    got = {c["id"]: c["relation"] for c in kept}
    return [got.get(c["id"], "out") for c in candidates]


def audit(pool, path, prompt, candidates, kept, model):
    """Ask a second, different model the same question and record how far the two agree. The page
    keeps the first model's judgement; the agreement rate is shown on the Evidence status page."""
    import state
    others = [k for k in pool.routing.get("evidence", []) if k != model]
    try:
        data2, model2, _ = pool.generate_json("evidence", prompt, only=others)
    except Exception as e:
        print(f"  [evidence] audit skipped: {str(e)[:80]}")
        return None
    if model2 == model:
        return None
    first, second = decisions(kept, candidates), decisions(judged(data2, candidates), candidates)
    rec = {"page": os.path.relpath(path, TIMELINE_DIR), "date": datetime.now().strftime("%Y-%m-%d"),
           "models": [model, model2], "grades": [grade_of(kept), grade_of(judged(data2, candidates))],
           "candidates": len(candidates), "same": sum(a == b for a, b in zip(first, second))}
    log = state.load("evidence_audit")
    log.setdefault("audits", []).append(rec)
    state.save("evidence_audit", log)
    print(f"  [evidence] audit by {model2}: grade {rec['grades'][1]} vs {rec['grades'][0]}, "
          f"{rec['same']}/{rec['candidates']} candidates judged the same")
    return rec


MAX_RETRIES_PER_RUN = 20  # pages left for later before the batch gives up on a failing source
SEARCH_VERSION = 3  # 2: failed sources no longer mark a page as searched; 3: descriptive words dropped from queries


def reopen_unsearched(done_map):
    """Once per SEARCH_VERSION, forget "none" results: before version 2 a page was recorded as
    "no evidence" even when OpenAlex had refused the search, and before version 3 queries kept
    words like "Disastrous", so those are searched again. Pages with an A or B grade are kept."""
    import state
    meta = state.load("evidence_meta")
    if meta.get("search_version", 1) >= SEARCH_VERSION:
        return 0
    stale = [rel for rel, g in done_map.items() if g == "none"]
    for rel in stale:
        del done_map[rel]
    meta["search_version"] = SEARCH_VERSION
    state.save("evidence_meta", meta)
    print(f"[evidence] {len(stale)} pages recorded as 'none' will be searched again")
    return len(stale)


JUDGE_VERSION = 3  # 2: supports / contradicts / background; background no longer earns a grade
# 3: claim 1 is the event itself, so a record or study of this event counts again


def _to_rejudge(version, grade, text):
    """Whether a page should be judged again, given the JUDGE_VERSION last applied."""
    if version < 2 and grade in ("A", "B") and "\n## Evidence\n" in text:
        return True  # graded under the looser rule
    return version < 3 and grade == "none" and "\n### Background reading" in text  # kept, none could count


def reopen_for_rejudge(done_map):
    """Once per JUDGE_VERSION, judge again the pages the older rule may have got wrong (`_to_rejudge`).
    Pages whose grade came from Deep Research notes are left alone: re-judging them would
    overwrite a grade this engine did not give."""
    import state
    meta = state.load("evidence_meta")
    version = meta.get("judge_version", 1)
    if version >= JUDGE_VERSION:
        return 0
    reopened = []
    for rel, grade in list(done_map.items()):
        path = os.path.join(TIMELINE_DIR, rel)
        if grade not in ("A", "B", "none") or not os.path.exists(path):
            continue
        text = read_page(path)[0]
        if _to_rejudge(version, grade, text) and "\n## Research notes\n" not in text:
            del done_map[rel]
            reopened.append(rel)
    meta["judge_version"] = JUDGE_VERSION
    state.save("evidence_meta", meta)
    print(f"[evidence] {len(reopened)} pages will be judged again under the new rule")
    return len(reopened)


def evidence_batch(pool, done_map, events, deadline, limit=None, save=None):
    """Attach evidence to event pages in `events` order; progress in done_map (rel -> grade)."""
    reopened = reopen_unsearched(done_map) + reopen_for_rejudge(done_map)
    if reopened and save:
        save(done_map)
    done = retries = 0
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
        if grade == "retry":
            retries += 1
            print(f"[evidence] {rel}: nothing found while a source was down; retried in a later run")
            if retries >= MAX_RETRIES_PER_RUN:
                print("[evidence] a source keeps failing; stopping evidence for this run")
                break
            continue
        done_map[rel] = grade
        done += 1
        print(f"[evidence] {rel}: grade {grade}")
        if save:
            save(done_map)
    return done


def audit_summary(days=30):
    """Status-page lines: how often a second model agrees with the first on the last `days` of audits."""
    import state
    since = datetime.fromtimestamp(time.time() - days * 86400).strftime("%Y-%m-%d")
    recent = [a for a in state.load("evidence_audit").get("audits", []) if a["date"] >= since]
    if not recent:
        return []
    same_grade = sum(a["grades"][0] == a["grades"][1] for a in recent)
    same = sum(a["same"] for a in recent)
    total = sum(a["candidates"] for a in recent) or 1
    return ["## How reliable is the judging?", "",
            f"Every day about {AUDIT_SHARE:.0%} of pages are judged a second time by a different AI model. "
            f"Over the last {days} days ({len(recent)} pages), the two models gave the **same grade on "
            f"{same_grade / len(recent):.0%}** of pages and judged **{same / total:.0%} of search results** the same way "
            "(kept or not, and whether it supports, contradicts or is background). The target is 90% or more.", ""]


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
             "most worth checking against primary sources).", "",
             "Pages where a source [[tags/evidence-contradicts|contradicts the draft]] are leads for myths and disputes.", ""]
    lines += audit_summary()
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
