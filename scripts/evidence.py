#!/usr/bin/env python3
"""Evidence engine: attach graded evidence to AI-drafted pages.

For each event page (1841 onward first), the page's title and claims are searched in
three free sources that need no API key:

  A  Hong Kong Government Records Service: Hong Kong archival catalogue metadata.
  A  UK National Archives Discovery: catalogue entries of primary records
     (e.g. CO 129, Hong Kong original correspondence).
  A  Internet Archive: books and official publications printed before 1950.
  B  OpenAlex: scholarly articles and books (with DOI and abstract).

GRS and National Archives search results are catalogue metadata, not inspected passages.

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
from datetime import datetime, timezone

from gemini_pool import QuotaExhausted, RequestRejected
import jev
from state import PAGE_LOCK, atomic_write
from grs_catalogue import GRS_SEARCH_URL, parse_grs_catalogue_results

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
RESEARCH_RECORDS_DIR = os.path.join(PROJECT_ROOT, "research", "records")
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

Candidate sources found by search (id, type, year, institution, authority level, title, note, inspectable passage):
{candidates}

Use the passage field as the deciding evidence whenever it contains inspected source text or an academic abstract.
The title, note, institution and authority level are metadata, not historical evidence. Do NOT use them to infer facts
or to support/contradict a claim when the passage does not establish that fact. Very short fragments without enough
context (fewer than 30 characters) must be background, not support/contradiction/partial. Authority is a provenance signal, not a verdict: a high-authority source still needs a claim-specific passage, and conflicting inspectable
passages must remain visible rather than being silently resolved by source rank.

If passage_status is not one of inspectable_text, inspectable_abstract, or inspectable_record, the passage is empty, or the passage is not about the numbered claim,
the candidate cannot support or contradict that claim. At most classify it as background, or exclude it.
Never infer the contents of an archive record from its catalogue description or title.
Distinguish related but different historical stages and legal concepts: military landing/occupation, treaty cession, and declaration or establishment of a colony are not interchangeable. A passage describing a later treaty cession does not by itself contradict an earlier occupation date. If the passage's terminology is ambiguous, classify it as partial or background and explain the distinction rather than inferring a contradiction.

For each candidate, compare the actual passage with the numbered claims. Record only claims that the
passage directly addresses, and state what the passage establishes. If the passage is ambiguous or only
partly supports a claim, explain the limitation rather than overstating the evidence.

Claim 1 is the event itself. It is supported only when the inspected passage directly documents this event
or establishes that it happened; a matching title or catalogue entry alone is not enough.

For each kept candidate:
- "relation": "supports" if the passage directly supports one or more numbered claims;
  "contradicts" if the passage directly conflicts with a claim; "partial" if it directly establishes
  only part of a claim; "background" if it is relevant but does not establish or conflict with a claim.
- "claims": the claim numbers directly addressed by the passage (empty for background).
- "why": one short sentence describing the passage itself and the limit of what it proves.
If no passage directly bears on a claim, do not label it supports, contradicts, or partial.
Respond with ONLY this JSON:
{{"relevant": [{{"id": "c3", "relation": "supports", "claims": [1, 2], "why": "One short sentence"}}],
  "missing": "One sentence on what evidence is still needed, or empty"}}"""

RANK = {"none": 0, "B": 1, "A": 2}
RELATIONS = ("supports", "contradicts", "partial")
MIN_INSPECTABLE_PASSAGE_LENGTH = 30
COUNTED = ("supports",)  # only direct supporting evidence can raise the evidence grade
AUDIT_SHARE = 0.05  # baseline share for second-model passage audits
PRIORITY_AUDIT_SHARE = 0.25  # higher sampling rate for weak-source/numeric/date-risk claims
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


def frontmatter_aliases(text):
    """Read explicitly declared Chinese titles and aliases without guessing alternate names."""
    match = re.match(r"\A---\s*\n(.*?)\n---", text, re.S)
    if not match:
        return []
    frontmatter = match.group(1)
    aliases = []
    for key in ("title_zh", "aliases", "historical_names", "alternative_names"):
        field = re.search(rf"(?m)^{key}:\s*(.*?)\s*$", frontmatter)
        if not field:
            continue
        value = field.group(1).strip()
        if value.startswith("[") and value.endswith("]"):
            values = re.findall(r"""['"]([^'"]+)['"]""", value)
            if not values:
                values = [item.strip().strip("'\" ") for item in value[1:-1].split(",")]
        else:
            values = [value.strip("'\" ")]
        for item in values:
            if item and item not in aliases:
                aliases.append(item)
    return aliases


def claim_search_queries(title, claims, aliases=()):
    """Build one title query plus a distinct query for every explicit claim."""
    queries = []
    for text in [title, *aliases, *claims]:
        query = keywords(text)
        if query and query.casefold() not in {q.casefold() for q in queries}:
            queries.append(query)
    return queries


def reserve_openalex_search():
    """Reserve one anonymous OpenAlex search from its documented 10-search daily allowance."""
    if (os.environ.get("OPENALEX_API_KEY") or "").strip():
        return True
    import state
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget = state.load("source_budget")
    if budget.get("date") != today:
        budget = {"date": today, "openalex_searches": 0}
    if int(budget.get("openalex_searches", 0)) >= 10:
        return False
    budget["openalex_searches"] = int(budget.get("openalex_searches", 0)) + 1
    state.save("source_budget", budget)
    return True


def gather_claim_candidates(queries):
    """Search each query, deduplicate URLs, and bound the prompt size per source."""
    combined, seen, successful_sources, queried_sources = [], set(), set(), set()
    max_per_source = 12
    has_openalex_key = bool((os.environ.get("OPENALEX_API_KEY") or "").strip())
    use_openalex = reserve_openalex_search()
    for query_index, query in enumerate(queries):
        # OpenAlex's anonymous allowance is only 10 searches/day. Search it once per page
        # without a key; claim-specific queries still run against the archive adapter(s).
        selected_sources = SOURCES
        if (query_index > 0 or not use_openalex) and not has_openalex_key:
            selected_sources = [(name, fn) for name, fn in SOURCES if name != "OpenAlex"]
        queried_sources.update(name for name, _ in selected_sources)
        candidates, failed = gather(query, sources=selected_sources)
        successful_sources.update(name for name, _ in selected_sources if name not in failed)
        per_query_counts = {}
        for candidate in candidates:
            source = candidate.get("source", "")
            url = candidate.get("url") or candidate.get("doi") or candidate.get("title")
            key = (source, str(url).casefold())
            if not url or key in seen or per_query_counts.get(source, 0) >= max(1, max_per_source // max(1, len(queries))):
                continue
            if sum(1 for item in combined if item.get("source") == source) >= max_per_source:
                continue
            seen.add(key)
            combined.append(candidate)
            per_query_counts[source] = per_query_counts.get(source, 0) + 1
    failed = [name for name in queried_sources if name not in successful_sources]
    return combined, failed


# ---- sources -----------------------------------------------------------

def openalex(query, year=None):
    params = {"search": f"{query} Hong Kong", "per-page": str(PER_SOURCE), "select": "id,doi,title,publication_year,type,authorships,primary_location,abstract_inverted_index"}
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
                    "catalogue_reference": w.get("doi") or w.get("id"),
                    "cite": f"{authors} ({w.get('publication_year')}). *{w['title']}*." + (f" {venue}." if venue else ""),
                    "note": abstract or venue,
                    "passage": abstract, "passage_status": "inspectable_abstract" if abstract else "metadata_only", "locator": "Abstract (OpenAlex work record)"})
    return out


def national_archives(query):
    params = {"sps.searchQuery": f"{query} Hong Kong", "sps.resultsPageSize": str(PER_SOURCE),
              "sps.heldByCode": "TNA"}
    data = _get_json("https://discovery.nationalarchives.gov.uk/API/search/records?" + urllib.parse.urlencode(params),
                     accept_json=True)
    # Discovery's documented JSON examples use PascalCase, while older responses/mocks
    # have appeared lower-camel. Accept both rather than silently returning zero records.
    records = data.get("records") or data.get("Records") or []
    out = []
    for record in records:
        ref = record.get("reference") or record.get("Reference") or record.get("CitableReference") or ""
        desc = (record.get("description") or record.get("Description") or
                record.get("title") or record.get("Title") or record.get("Content") or "")
        desc = re.sub(r"<[^>]+>", "", str(desc))
        covering_dates = record.get("coveringDates") or record.get("CoveringDates") or ""
        identifier = record.get("id") or record.get("Id")
        if not ref or not identifier:
            continue
        out.append({"kind": "archive record", "grade": "A", "year": covering_dates,
                    "title": f"{ref}: {desc[:160]}",
                    "url": f"https://discovery.nationalarchives.gov.uk/details/r/{identifier}",
                    "cite": f"The National Archives (UK), {ref}, {covering_dates}. {desc[:200]}",
                    "catalogue_reference": ref,
                    "note": desc[:300], "passage": "", "passage_status": "metadata_only", "locator": f"National Archives catalogue record {ref}"})
    return out

GRS_MAX_BYTES = 1_000_000


def grs_catalogue(query):
    """Search the official GRS online catalogue; return catalogue metadata only."""
    params = urllib.parse.urlencode({"q": query})
    url = GRS_SEARCH_URL + "?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(GRS_MAX_BYTES + 1)
    truncated = len(raw) > GRS_MAX_BYTES
    html = raw[:GRS_MAX_BYTES].decode("utf-8", errors="replace")
    if "search results" not in html.casefold():
        raise ValueError("GRS catalogue returned an unexpected HTML page")
    results = parse_grs_catalogue_results(html, query)
    if truncated and not results:
        raise ValueError("GRS catalogue response exceeded the byte limit before any record links could be inspected")
    return results


def internet_archive_ai_processing_allowed(metadata):
    """Default-deny OCR processing unless item metadata explicitly marks it public domain/CC0."""
    values = []
    for container in (metadata.get("metadata") or {}, metadata):
        if not isinstance(container, dict):
            continue
        for key in ("licenseurl", "license", "rights", "rightsstatement"):
            value = container.get(key)
            if isinstance(value, list):
                values.extend(value)
            elif value:
                values.append(value)
    normalized = " ".join(str(value).casefold() for value in values if value)
    return (
        "creativecommons.org/publicdomain/mark" in normalized
        or "creativecommons.org/publicdomain/zero" in normalized
        or ("public domain" in normalized
            and "not public domain" not in normalized
            and "not in the public domain" not in normalized)
    )

def internet_archive_text(identifier, max_chars=5000):
    """Fetch a real Internet Archive OCR text file; return None for metadata/errors."""
    try:
        metadata = _get_json(f"https://archive.org/metadata/{urllib.parse.quote(identifier, safe='')}")
        if not internet_archive_ai_processing_allowed(metadata):
            return None  # no explicit public-domain/CC0 rights signal: metadata-only discovery
        files = metadata.get("files") or []
        names = [item.get("name", "") for item in files if item.get("name")]
        # Internet Archive's usual OCR output. Do not treat item descriptions or PDFs as text.
        candidates = [n for n in names if n.lower().endswith("_djvu.txt")]
        if not candidates:
            return None
        name = candidates[0]
        url = "https://archive.org/download/" + urllib.parse.quote(identifier, safe="") + "/" + urllib.parse.quote(name, safe="/")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(100_001)
        text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 300 or re.search(r"(?i)<!doctype html|<html|access denied|item not available", text[:1000]):
            return None
        return text[:max_chars]
    except (OSError, ValueError, KeyError, urllib.error.URLError, TimeoutError):
        return None


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
        identifier = d.get("identifier", "")
        passage = internet_archive_text(identifier) if identifier else None
        out.append({"kind": "digitised publication", "grade": "B", "year": d.get("year"),
                    "title": d.get("title", identifier), "url": f"https://archive.org/details/{identifier}",
                    "catalogue_reference": identifier,
                    "cite": f"{creator + ', ' if creator else ''}*{d.get('title', identifier)}* ({d.get('year', 'n.d.')}), Internet Archive.",
                    "note": re.sub(r"<[^>]+>", "", desc)[:300],
                    "passage": passage or "", "passage_status": "inspectable_text" if passage else "metadata_only", "locator": f"Internet Archive OCR text for {identifier}"})
    return out


# The registry is the single source of truth for adapter metadata and ordering. Keep the
# legacy tuple interface so existing evidence batching and tests remain backward compatible.
from source_registry import build_default_registry

SOURCE_REGISTRY = build_default_registry()
SOURCES = SOURCE_REGISTRY.adapters()


# ---- page handling -----------------------------------------------------

def read_page(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm = text.split("---", 2)[1] if text.startswith("---") else ""
    get = lambda k: (re.search(rf'^{k}: *"?(.*?)"?$', fm, re.M) or [None, ""])[1]
    claim_section = re.search(r"(?ms)^## Claims to verify\s*\n(.*?)(?=^## |\Z)", text)
    claims = re.findall(r"^- (?:\[\s*\]|❔)\s+(.+)$", claim_section.group(1), re.M) if claim_section else []
    claims += [c for c in re.findall(r"^- [✅❌❔] \*\*\w+\*\*: (.+?)\.(?: |$)", text, re.M)]
    return text, get("title"), get("date") or get("year"), claims


def grade_of(kept):
    """Grade supporting evidence only. Contradictions are important, but are not support."""
    counted = [c for c in kept if c.get("relation") == "supports"]
    return "A" if any(c["grade"] == "A" for c in counted) else ("B" if counted else "none")


def record_grade_change(path, before, after, contradiction_found=False):
    """Persist every evidence-grade change, including a complete search with zero results."""
    if before not in RANK or before == after:
        return
    import state
    meta = state.load("evidence_meta")
    meta.setdefault("grade_changes", []).append({
        "page": os.path.relpath(path, TIMELINE_DIR),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "from": before,
        "to": after,
        "reason": "rejudged evidence",
        "contradiction_found": bool(contradiction_found),
    })
    state.save("evidence_meta", meta)
    print(f"[evidence] {os.path.basename(path)}: grade changed {before} -> {after}; change recorded")


def evidence_block(kept, missing, model):
    grade = grade_of(kept)
    today = datetime.now().strftime("%Y-%m-%d")
    how = (f"judged by {model} on {today}. This is source coverage, not a verification verdict: only sources "
           "judged to support a claim count towards coverage; contradictions are listed separately and block "
           "treating the affected claim as settled. Sources have not all been read in full, so individual claims "
           "still need checking." if kept else
           f"searched on {today}; no relevant evidence was found. This is not proof that the draft is true or false.")
    lines = ["## Evidence", "",
             f"> [!abstract] Evidence coverage: **{grade}** (not a verification verdict)",
             f"> Sources from the UK National Archives, Internet Archive (pre-{PRIMARY_BEFORE} publications) and "
             f"OpenAlex (scholarship), {how}", ""]
    supporting = [c for c in kept if c.get("relation") == "supports"]
    for label, g in (("Primary-source coverage (A)", "A"), ("Scholarship coverage (B)", "B")):
        items = [c for c in supporting if c["grade"] == g]
        if items:
            lines += [f"### {label}", ""]
            for c in items:
                claims = ", ".join(map(str, c.get("claims") or []))
                lines.append(f"- [{c['cite']}]({c['url']}) (supports claim {claims}): {c.get('why', '')}")
            lines.append("")
    contradicting = [c for c in kept if c.get("relation") == "contradicts"]
    if contradicting:
        lines += ["### Contradictory evidence (does not count as support)", ""]
        lines += [f"- [{c['cite']}]({c['url']}) (⚠ contradicts claim {', '.join(map(str, c.get('claims') or []))}): {c.get('why', '')}"
                  for c in contradicting]
        lines.append("")
    partial = [c for c in kept if c.get("relation") == "partial"]
    if partial:
        lines += ["### Partially supporting evidence (does not count towards coverage)", ""]
        lines += [f"- [{c['cite']}]({c['url']}) (partially supports claim {', '.join(map(str, c.get('claims') or []))}): {c.get('why', '')}"
                  for c in partial]
        lines.append("")
    background = [c for c in kept if c.get("relation") == "background"]
    if background:
        lines += ["### Background reading (does not count towards coverage)", ""]
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
    atomic_write(path, text)


SOURCE_FAILS_TO_REST = 3  # consecutive failures before a source is skipped for the rest of the run
_source_fails = {}


def gather(query, sources=None):
    """Candidates from every source. A source that fails is skipped, not fatal; one that keeps
    failing is rested for the rest of the run (and still reported as failed for each page)."""
    found, failed = [], []
    for name, fn in (SOURCES if sources is None else sources):
        if _source_fails.get(name, 0) >= SOURCE_FAILS_TO_REST:
            failed.append(name)
            continue
        try:
            registered = SOURCE_REGISTRY.definition_for_name(name)
            if registered is not None and registered.search is fn:
                result = SOURCE_REGISTRY.search(query, source_ids=[registered.source_id])
                failure = next((item for item in result["failures"] if item["source_id"] == registered.source_id), None)
                if failure:
                    raise RuntimeError(f"{failure['error_type']}: {failure['error']}")
                got = result["candidates"]
                for candidate in got:
                    candidate["source"] = name
            else:
                # Keep test injection and third-party adapters backward compatible.
                got = fn(query)
                for candidate in got:
                    candidate["source"] = name
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
    """Lead with the event/date claim without assuming every event happened in Hong Kong."""
    event_claim = f"{title} occurred in {date}." if date else f"{title} occurred."
    return [event_claim] + list(claims)

def evidence_for_page(pool, path):
    """Returns the grade written; None if nothing could be searched (stop this run); "retry" if a
    source failed and nothing was found, so the page is not wrongly recorded as searched."""
    text, title, date, claims = read_page(path)
    queries = claim_search_queries(title, claims, frontmatter_aliases(text))
    candidates, failed = gather_claim_candidates(queries)
    query = "; ".join(queries)
    if len(failed) == len(SOURCES):
        return None
    if failed and "\n## Evidence\n" in text:
        return "retry"  # judged before: a partial search must not replace a full one
    if not candidates and failed:
        return "retry"
    if not candidates:
        print(search_summary(query, candidates, failed, None))
        grade, lines = evidence_block([], "", "search")
        before = (re.search(r"(?m)^evidence_grade: (\w+)", text) or [None, None])[1]
        record_grade_change(path, before, grade)
        from research_record_store import persist_page_judgement
        persisted = persist_page_judgement(
            path, TIMELINE_DIR, title, date, claims, [], None, JUDGE_VERSION,
            records_dir=RESEARCH_RECORDS_DIR,
        )
        print(f"[evidence] structured records: {persisted}")
        write_evidence(path, grade, lines)
        return grade
    data, model, prompt, kept = judge(pool, title, date, claims, candidates)
    print(search_summary(query, candidates, failed, len(kept)))
    rec = None
    if jev.available() and _jev_count[0] < JEV_PAGES_PER_RUN and _rng.random() < JEV_SHARE:
        _jev_count[0] += 1
        rec = jev_audit(path, title, date, claims, candidates, kept, model)
        if rec and rec.get("disputes"):
            kept = second_look(pool, title, date, claims, candidates, kept, rec["disputes"])
    priority_reasons = audit_priority_reasons(title, date, claims, kept)
    if rec and any(d.get("judge") in RELATIONS or d.get("jev") in RELATIONS for d in rec.get("disputes", [])):
        priority_reasons.append("model disagreement on a relevant candidate")
    if should_run_full_audit(priority_reasons, _rng.random()):
        audit(pool, path, prompt, candidates, kept, model,
              claim_count=len(event_claims(title, date, claims)), priority_reasons=priority_reasons)
    grade, lines = evidence_block(kept, data.get("missing", "") if isinstance(data, dict) else "", model)
    if grade == "none" and failed:
        return "retry"  # a source we could not search may still hold evidence
    before = (re.search(r"(?m)^evidence_grade: (\w+)", text) or [None, None])[1]
    # Preserve the audit trail, but never let a stale grade override the current judgement.
    record_grade_change(
        path, before, grade,
        contradiction_found=any(c.get("relation") == "contradicts" for c in kept),
    )
    from research_record_store import persist_page_judgement
    persisted = persist_page_judgement(
        path, TIMELINE_DIR, title, date, claims, kept, model, JUDGE_VERSION,
        records_dir=RESEARCH_RECORDS_DIR,
    )
    print(f"[evidence] structured records: {persisted}")
    write_evidence(path, grade, lines, contradicts=any(c.get("relation") == "contradicts" for c in kept))
    return grade


def judge(pool, title, date, claims, candidates):
    """Number the candidates and have the evidence role judge them: (data, model, prompt, kept)."""
    for i, c in enumerate(candidates, 1):
        c["id"] = f"c{i}"
    listing = "\n".join(
        f"{c['id']} | {c['kind']} | year: {c['year']} | institution: {c.get('institution', '')} "
        f"| authority_level: {c.get('authority_level', '')} | source_type: {c.get('source_type', '')} "
        f"| title: {c['title'][:150]} | note: {c['note'][:180]} "
        f"| passage_status: {c.get('passage_status', 'metadata_only')} "
        f"| passage: {c.get('passage', '')[:1200]}"
        for c in candidates)
    claim_text = "\n".join(f"{i}. {claim}" for i, claim in enumerate(event_claims(title, date, claims), 1))
    prompt = JUDGE_PROMPT.format(title=title, date=date, claims=claim_text, candidates=listing)
    data, model, _ = pool.generate_json("evidence", prompt)
    if not isinstance(data, dict) or not isinstance(data.get("relevant"), list):
        raise ValueError("Evidence judge returned an invalid response: 'relevant' must be a list")
    candidate_ids = {candidate["id"] for candidate in candidates}
    for item in data["relevant"]:
        if not isinstance(item, dict) or str(item.get("id", "")) not in candidate_ids:
            raise ValueError("Evidence judge returned a malformed item or unknown candidate id")
    claim_count = len(event_claims(title, date, claims))
    return data, model, prompt, judged(data, candidates, claim_count=claim_count)


def judged(data, candidates, claim_count=None):
    """Keep a judgement only when it names valid claims and explains its decision.

    Invalid claim numbers, missing rationales, and uninspectable passages fail closed to
    background; they must not raise evidence coverage or create an unsupported contradiction.
    """
    by_id = {c["id"]: dict(c) for c in candidates}
    kept = []
    relevant = data.get("relevant", []) if isinstance(data, dict) else []
    if not isinstance(relevant, list):
        return kept
    for r in relevant:
        if not isinstance(r, dict):
            continue
        c = by_id.pop(str(r.get("id", "")), None)
        if not c:
            continue
        raw_claims = r.get("claims")
        if not isinstance(raw_claims, list):
            raw_claims = []
        valid_claims = []
        for number in raw_claims:
            if isinstance(number, int) and not isinstance(number, bool) and number >= 1:
                if claim_count is None or number <= claim_count:
                    if number not in valid_claims:
                        valid_claims.append(number)
        c["claims"] = valid_claims
        why = r.get("why", "")
        c["why"] = why.strip() if isinstance(why, str) else ""
        relation = str(r.get("relation", "")).lower()
        # Fail closed: only an inspected passage may support or contradict a claim.
        passage_text = str(c.get("passage", "")).strip()
        passage_status_valid = c.get("passage_status") in {"inspectable_text", "inspectable_abstract", "inspectable_record"}
        has_passage = passage_status_valid and len(passage_text) >= MIN_INSPECTABLE_PASSAGE_LENGTH
        valid_judgement = relation in RELATIONS and c["claims"] and bool(c["why"]) and has_passage
        c["relation"] = relation if valid_judgement else "background"
        if relation in RELATIONS and not has_passage:
            if passage_status_valid and passage_text and len(passage_text) < MIN_INSPECTABLE_PASSAGE_LENGTH:
                c["why"] = "Inspected passage is too short to establish this claim; treated as background."
            else:
                c["why"] = "Source passage not inspected; metadata alone cannot establish this claim."
        elif relation in RELATIONS and not valid_judgement:
            c["why"] = "Judgement lacks a valid claim reference or explanatory rationale; treated as background."
        kept.append(c)
    return kept


def decisions(kept, candidates):
    """Per candidate: out / background / supports / contradicts, for comparing two judges."""
    got = {c["id"]: c["relation"] for c in kept}
    return [got.get(c["id"], "out") for c in candidates]




def audit_priority_reasons(title, date, claims, kept):
    """Return reasons to sample a page for a second-model passage audit."""
    claim_text = " ".join([str(title or ""), str(date or "")] + [str(item) for item in (claims or [])])
    reasons = []
    relations = {str(item.get("relation", "")).lower() for item in kept if isinstance(item, dict)}
    if "contradicts" in relations:
        reasons.append("contradiction present")
    if "partial" in relations:
        reasons.append("partial evidence present")
    if re.search(r"\b(?:killed|deaths?|casualties|injured|wounded|fatalities|percent(?:age)?|million|billion|exactly|at least|more than|less than|only|first|largest|smallest|never|all|sole)\b", claim_text, re.I) and re.search(r"\d", claim_text):
        reasons.append("high-impact number or absolute claim")
    claim_years = set(re.findall(r"\b(?:18|19|20)\d{2}\b", " ".join(str(item) for item in (claims or []))))
    if claim_years:
        for item in kept:
            if item.get("relation") not in {"supports", "partial"}:
                continue
            passage_years = set(re.findall(r"\b(?:18|19|20)\d{2}\b", str(item.get("passage") or "")))
            if passage_years and not (claim_years & passage_years):
                reasons.append("claim/passage year mismatch")
                break
    if any(
        str(item.get("authority_level", "")).strip().lower() in {"unknown", "low"}
        and item.get("relation") in RELATIONS
        for item in kept
    ):
        reasons.append("weak or unknown source authority")
    return list(dict.fromkeys(reasons))


def should_run_full_audit(priority_reasons, random_value, baseline_share=None, priority_share=None):
    """Always audit contradictions/partial evidence; sample other risks at 25%, baseline at 5%."""
    reasons = set(priority_reasons or ())
    baseline_share = AUDIT_SHARE if baseline_share is None else baseline_share
    priority_share = PRIORITY_AUDIT_SHARE if priority_share is None else priority_share
    if reasons & {"contradiction present", "partial evidence present"}:
        return True
    if reasons:
        return random_value < priority_share
    return random_value < baseline_share

def audit(pool, path, prompt, candidates, kept, model, claim_count=None, priority_reasons=None):
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
    first, second = decisions(kept, candidates), decisions(judged(data2, candidates, claim_count=claim_count), candidates)
    rec = {"page": os.path.relpath(path, TIMELINE_DIR), "date": datetime.now().strftime("%Y-%m-%d"),
           "models": [model, model2], "grades": [grade_of(kept), grade_of(judged(data2, candidates, claim_count=claim_count))],
           "candidates": len(candidates), "same": sum(a == b for a, b in zip(first, second)),
           "priority_reasons": list(priority_reasons or [])}
    log = state.load("evidence_audit")
    log.setdefault("audits", []).append(rec)
    state.save("evidence_audit", log)
    print(f"  [evidence] audit by {model2}: grade {rec['grades'][1]} vs {rec['grades'][0]}, "
          f"{rec['same']}/{rec['candidates']} candidates judged the same"
          + (f"; priority: {', '.join(rec['priority_reasons'])}" if rec["priority_reasons"] else ""))
    return rec



# FreeJev as a tip-off for the evidence judge (owner, 2026-10-02). A trial on 144 pages found Jev a
# poor judge on its own (on pages with evidence it agreed with the judge on half the results and
# dropped real evidence the judge kept), but its reason answers single out the judge's own mistakes:
# Jev never changes a page itself; where it disagrees with reasons that hold together, the evidence
# judge looks again at that one result (`second_look`) and its second decision stands. About 3
# credits a page, from the owner's free credits; Jev stops itself below jev.RESERVE_CREDITS.
JEV_SHARE = 1.0
JEV_PAGES_PER_RUN = 150  # as many as the evidence batch judges in a run (EVIDENCE_PAGES_PER_RUN)
_jev_count = [0]
JEV_CRITERIA = {
    "out": "Not about this event: a different event, place or period, or only the general subject.",
    "background": "About this event, but bears on none of the numbered claims.",
    "supports": "Bears on a numbered claim and agrees with it. A record or study of this event supports claim 1.",
    "partial": "Directly supports only part of a numbered claim; do not treat the whole claim as established.",
    "contradicts": "Bears on a numbered claim and disagrees with it (a different date, place or outcome).",
}

# Jev gives labels, never reasons, so where it and the evidence judge disagree it answers these
# multiple-choice questions about the result (owner, 2026-10-01). "about" names the usual ways a
# result goes wrong (the 2022 study of a biopic counted for Anita Mui's death; an 1893 proposal for
# a 1914 exhibition). key: (question, {answer: (meaning for Jev, short phrase for the log)})
JEV_REASONS = {
    "about": ("What is search result {id} about?", {
        "event": ("This event itself.", "about this event"),
        "moment": ("The same person, place or organisation, but a different moment or episode.",
                   "same subject, different moment"),
        "forerunner": ("A plan, proposal, cause or forerunner of the event, not the event itself.",
                       "a plan or forerunner, not the event"),
        "general": ("Only the general subject or period.", "only the general subject"),
        "unrelated": ("Something unrelated; any match with the page is only a shared word.", "unrelated"),
    }),
    "shows": ("What can search result {id} show about this event?", {
        "happened": ("That the event happened: a record, report or study of it.", "shows the event happened"),
        "detail": ("A detail of the event: its date, place, people, numbers or outcome.", "shows a detail of it"),
        "mention": ("Nothing beyond a passing mention of the event or its subject.", "only mentions it"),
        "nothing": ("Nothing about the event.", "shows nothing about it"),
    }),
}
# The third question checks the evidence judge's own decision. Its words go only into this question,
# never into the text Jev reads for the other questions, so they cannot sway those answers.
JEV_CHECK_KEPT = {
    "right": ("Yes: the reason is true and makes the result evidence for this event.", "the judge is right"),
    "overstated": ("Partly: the result says less than the reason claims.", "the judge overstates it"),
    "wrong": ("No: the reason is wrong or does not make the result evidence for this event.", "the judge is wrong"),
}
JEV_CHECK_OUT = {
    "right": ("Yes: the result is not evidence for this event.", "the judge is right"),
    "wrong": ("No: the result supports or contradicts a claim about this event.", "the judge is wrong"),
}


def _check_question(c, judge_label, judge_why):
    if judge_label == "out":
        return (f"The evidence judge left search result {c['id']} out as not evidence for this event. Is that right?",
                JEV_CHECK_OUT)
    return (f"The evidence judge counted search result {c['id']} as '{judge_label}', because: "
            f"\"{judge_why or 'no reason given'}\". Is that right?", JEV_CHECK_KEPT)


def jev_audit(path, title, date, claims, candidates, kept, model, trial=False, phase=None):
    """Judge the same search results with Jev and record the agreement in evidence_audit.json ("jev")."""
    import state
    claim_text = "\n".join(f"{i}. {c}" for i, c in enumerate(event_claims(title, date, claims), 1))
    labels, probs = {}, []
    for start in range(0, len(candidates), jev.MAX_QUESTIONS):
        chunk = candidates[start:start + jev.MAX_QUESTIONS]
        page = _jev_state(title, date, claim_text, chunk)
        questions = {c["id"]: {"type": "choice", "criteria": JEV_CRITERIA,
                               "instructions": f"Judging only from its title and note, how does search result {c['id']} relate to this page?"}
                     for c in chunk}
        answers = jev.decide(page, questions)
        if answers is None:
            return None
        for c in chunk:
            got = jev.choice_of(answers.get(c["id"]), JEV_CRITERIA)
            if got is None:
                print(f"  [jev] unreadable answer for {c['id']}: {jev.shape(answers.get(c['id']))}")
                return None
            labels[c["id"]], p = got
            if p is not None:
                probs.append(p)
    jev_kept = [dict(c, relation=labels[c["id"]]) for c in candidates if labels[c["id"]] != "out"]
    first, second = decisions(kept, candidates), [labels[c["id"]] for c in candidates]
    rec = {"page": os.path.relpath(path, TIMELINE_DIR), "date": datetime.now().strftime("%Y-%m-%d"),
           "models": [model, "Jev"], "grades": [grade_of(kept), grade_of(jev_kept)],
           "candidates": len(candidates), "same": sum(a == b for a, b in zip(first, second)),
           "mean_probability": round(sum(probs) / len(probs), 3) if probs else None,
           "labels": [[a, b] for a, b in zip(first, second)]}
    if trial:
        rec["trial"] = trial
    if phase:
        rec["phase"] = phase
    disputed = [(c, a, b) for c, a, b in zip(candidates, first, second) if a != b]
    if disputed:
        why = {c["id"]: c.get("why", "") for c in kept}
        reasons = jev_reasons(title, date, claim_text, [(c, a, why.get(c["id"], "")) for c, a, _ in disputed])
        rec["disputes"] = [{"title": c["title"][:150], "url": c["url"], "kind": c["kind"], "year": c["year"],
                            "judge": a, "judge_why": why.get(c["id"], ""), "jev": b,
                            "jev_why": reasons.get(c["id"], {})} for c, a, b in disputed]
    log = state.load("evidence_audit")
    log.setdefault("jev", []).append(rec)
    state.save("evidence_audit", log)
    print(f"  [jev] audit: grade {rec['grades'][1]} vs {rec['grades'][0]}, {rec['same']}/{rec['candidates']} "
          f"results judged the same" + (f", mean confidence {rec['mean_probability']:.2f}" if probs else ""))
    for d in rec.get("disputes", []):
        print(f"    [jev] dispute: {d['title'][:80]} ({d['year']}): judge {d['judge']}: "
              f"{d['judge_why'] or 'no reason given (the judge explains only results it keeps)'} | "
              f"Jev {d['jev']}: {reason_text(d['jev_why']) or 'no reasons'}")
    return rec


def _jev_state(title, date, claim_text, results):
    return (f"Page of a Hong Kong history website: {title} ({date})\nClaims:\n{claim_text}\n\n"
            "Search results (id | type | year | title | note):\n"
            + "\n".join(f"{c['id']} | {c['kind']} | {c['year']} | {c['title'][:150]} | {c['note'][:220]}" for c in results))


def jev_reasons(title, date, claim_text, disputed):
    """disputed: (result, judge's label, judge's reason). Returns id -> {question: answer} for the
    JEV_REASONS questions and "check" (is the judge right?); results Jev could not answer are left out."""
    per_call = jev.MAX_QUESTIONS // (len(JEV_REASONS) + 1)
    out = {}
    for start in range(0, len(disputed), per_call):
        chunk = disputed[start:start + per_call]
        asked = {}
        for c, label, why in chunk:
            for key, (q, answers) in JEV_REASONS.items():
                asked[f"{c['id']}_{key}"] = (c["id"], key, q.format(id=c["id"]), answers)
            q, answers = _check_question(c, label, why)
            asked[f"{c['id']}_check"] = (c["id"], "check", q, answers)
        questions = {qid: {"type": "choice", "instructions": q, "criteria": {a: m for a, (m, _) in answers.items()}}
                     for qid, (_, _, q, answers) in asked.items()}
        answers = jev.decide(_jev_state(title, date, claim_text, [c for c, _, _ in chunk]), questions)
        if not answers:
            break
        for qid, (cid, key, _, options) in asked.items():
            hit = jev.choice_of(answers.get(qid), options)
            if hit:
                out.setdefault(cid, {})[key] = hit[0]
    return out


def reason_text(why):
    """Jev's answers to the reason questions as a short phrase for logs and reports."""
    phrases = {**{k: opts for k, (_, opts) in JEV_REASONS.items()}, "check": {**JEV_CHECK_OUT, **JEV_CHECK_KEPT}}
    return "; ".join(phrases[k][a][1] for k, a in why.items() if k in phrases and a in phrases[k])


def worth_second_look(d):
    """A dispute where Jev's own reasons back its label (trial, 2026-10-02: this kept every case where
    Jev caught a real error of the judge and dropped almost every case where Jev was wrong)."""
    why = d.get("jev_why") or {}
    if d["jev"] in RELATIONS and d["judge"] not in RELATIONS:  # evidence the judge may have missed
        return why.get("about") == "event" and why.get("shows") in ("happened", "detail")
    if d["judge"] in RELATIONS and d["jev"] not in RELATIONS:  # evidence the judge may have over-counted
        return (why.get("about") in ("moment", "forerunner", "general", "unrelated")
                and why.get("shows") in ("mention", "nothing") and why.get("check") in ("wrong", "overstated"))
    return False


def second_look(pool, title, date, claims, candidates, kept, disputes):
    """Have the evidence judge look again, on its own, at each result `worth_second_look`; its second
    decision replaces the first. Returns the new kept list (in search order); the outcomes are added
    to the latest Jev record."""
    import state
    by_url = {c["url"]: c for c in candidates}
    decided = {c["url"]: c for c in kept}
    outcomes = []
    for d in disputes:
        c = by_url.get(d["url"])
        if not c or not worth_second_look(d):
            continue
        try:
            _, _, _, again = judge(pool, title, date, claims, [dict(c)])
        except Exception as e:
            print(f"    [evidence] second look failed ({str(e)[:80]}); the first decision stands")
            continue
        if again:
            decided[c["url"]] = dict(again[0], id=c["id"])
        else:
            decided.pop(c["url"], None)
        second = again[0]["relation"] if again else "out"
        outcomes.append({"url": c["url"], "judge": d["judge"], "jev": d["jev"], "second": second})
        print(f"    [evidence] second look: {c['title'][:70]} ({c['year']}): judge {d['judge']}, Jev {d['jev']}"
              f" -> {second}")
    if outcomes:
        log = state.load("evidence_audit")
        if log.get("jev"):
            log["jev"][-1]["second_look"] = outcomes
            state.save("evidence_audit", log)
    return [decided[c["url"]] for c in candidates if c["url"] in decided]


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


JUDGE_VERSION = 10  # 10: short passages fail closed; partial evidence and authority metadata are distinct
# 9: partial evidence is distinct; source authority is context, not proof
# 8: neutral event/date claim; no implicit Hong Kong location assertion
# 6: only inspectable source passages may support or contradict claims
# 2: supports / contradicts / background; background no longer earns a grade
# 3: claim 1 is the event itself, so a record or study of this event counts
# 4: Jev's tip-offs and the judge's second look (owner, 2026-10-02), on the core eras
JEV_REVIEW_FROM = "05-opium-war"  # seed_history.CORE_ERA_START: 1841 on


def _to_rejudge(version, grade, text, rel=""):
    """Whether a page should be judged again, given the JUDGE_VERSION last applied."""
    if version < 2 and grade in ("A", "B") and "\n## Evidence\n" in text:
        return True  # graded under the looser rule
    if version < 3 and grade == "none" and "\n### Background reading" in text:
        return True  # kept, none could count
    if version < 5 and grade in ("A", "B") and "\n## Evidence\n" in text:
        return True  # prior grades counted contradictions as support; recompute under support-only grading
    if version < 10 and grade in ("A", "B", "none") and "\n## Evidence\n" in text:
        return True  # version 10: short passages fail closed; partial and authority rules apply
    return version < 4 and "/" in rel and rel.split("/")[0] >= JEV_REVIEW_FROM and "\n## Evidence\n" in text


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
        if _to_rejudge(version, grade, text, rel) and "\n## Research notes\n" not in text:
            del done_map[rel]
            reopened.append(rel)
            meta.setdefault("rejudged_from", {})[rel] = grade  # to report what the new round changed
    meta["judge_version"] = JUDGE_VERSION
    state.save("evidence_meta", meta)
    print(f"[evidence] {len(reopened)} pages will be judged again under the new rule")
    return len(reopened)


def evidence_batch(pool, done_map, events, deadline, limit=None, save=None):
    """Attach evidence to event pages in `events` order; progress in done_map (rel -> grade)."""
    # Older runs wrote the literal "error" sentinel into done_map after a rejected
    # judgement. Membership means completed, so remove those legacy entries to let them retry.
    legacy_errors = [rel for rel, grade in done_map.items() if grade == "error"]
    for rel in legacy_errors:
        del done_map[rel]
    if legacy_errors:
        print(f"[evidence] {len(legacy_errors)} pages with legacy error markers will be retried")
    reopened = len(legacy_errors) + reopen_unsearched(done_map) + reopen_for_rejudge(done_map)
    if reopened and save:
        save(done_map)
    done = retries = 0
    failures = []
    blocking_failures = []
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
            # Do not put an error sentinel in done_map: membership there means "finished" and
            # would permanently suppress retries on later runs.
            message = f"{rel}: evidence judgement rejected: {str(e)[:100]}"
            print(f"[evidence] {message}; leaving page pending for retry")
            failures.append(message)
            blocking_failures.append(message)
            continue
        if grade is None:
            message = f"{rel}: every evidence source was unreachable; page remains pending"
            print(f"[evidence] {message}")
            failures.append(message)
            blocking_failures.append(message)
            break
        if grade == "retry":
            retries += 1
            message = f"{rel}: retrieval was incomplete; page remains pending for a later run"
            print(f"[evidence] {message}")
            failures.append(message)
            if retries >= MAX_RETRIES_PER_RUN:
                print("[evidence] transient source failures reached the per-run limit; remaining pages stay pending")
                break
            continue
        done_map[rel] = grade
        done += 1
        print(f"[evidence] {rel}: grade {grade}")
        if save:
            save(done_map)
    if blocking_failures:
        # Provider/model failures are blocking: the run must not be recorded as wholly successful.
        raise RuntimeError(
            f"Evidence batch had {len(blocking_failures)} blocking failure(s): "
            + "; ".join(blocking_failures[:5])
        )
    if failures:
        # Retrieval gaps are recoverable: pages were deliberately not marked complete and will be
        # retried on a later run. Do not turn routine upstream 429/502 outages into a red pipeline.
        print(f"[evidence] warning: {len(failures)} page(s) remain pending after incomplete retrieval; "
              "successful work is saved and these pages will be retried on a later run")
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
    lines = ["---", 'title: "Evidence coverage"', 'description: "Source coverage on AI-drafted history pages; this is not a claim-verification score."',
             "---", "",
             f"_Updated {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC._", "",
             "**Important:** A/B/none measure source coverage, not historical correctness. AI-drafted pages remain hypotheses; a linked source or high coverage level does not verify every statement.", "",
             "| Coverage | Meaning | Pages |", "|---|---|---|",
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
