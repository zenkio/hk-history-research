"""Reference text from English Wikipedia for fact-checking (no API key).

Google Search grounding is not available on the free tier for the models we can
use (Gemini 2.5 is closed to new users), so fact-checks read Wikipedia instead:
search for the page's topic, fetch the top articles as plain text, and keep the
paragraphs that share the most words with the claims. The model then judges each
claim against that text only.

Wikipedia is anyone-can-edit, so agreeing with it proves nothing: it never raises a
page's evidence grade (A/B come only from archives and scholarship). Instead
cited_sources() pulls the books and papers the article cites, and checks each DOI/ISBN
against Crossref/Open Library, so readers (and the evidence engine) can follow a claim
to where Wikipedia got it, or see that it cites nothing.
"""
import re
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
ARTICLES = 2
MAX_CITES = 5
MIN_PARA_OVERLAP = 2  # a paragraph must share 2+ words with the page to be sent
EVENT_WORDS = set("founding foundation opening establishment restoration introduction launch start end "
                  "beginning creation formation signing outbreak arrival death birth first new construction "
                  "consecration declared assumes gathers completion inauguration enactment passage proclamation "
                  "devastating great sir governorship appointed prompts sparks moves".split())
MIN_CITE_OVERLAP = 2  # a cited work's title must share 2+ words with the page's claims
GENERIC = {"Hong Kong", "British Hong Kong", "History of Hong Kong", "China", "History of China",
           "Qing dynasty", "Kowloon", "New Territories", "Hong Kong Island"}
TRIES = 3
PAUSE = 1.0  # seconds between API calls
MAX_CHARS = 7000  # ~2K tokens: fits Gemma's 16K TPM with room for the claims
STOP = set("the a an of and or in on at to for by with from was were is are be been as that this "
           "which it its his her their into after before during hong kong".split())


def _api(**params):
    """GET the MediaWiki API. Wikimedia rate-limits by IP (CI runners share IPs), so a 429
    waits for its Retry-After (capped) and tries again, and calls are spaced out."""
    params.update(format="json", formatversion="2")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    for attempt in range(TRIES):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == TRIES - 1:
                raise
            ra = e.headers.get("Retry-After") or ""
            wait = min(int(ra) if ra.isdigit() else 30, 90)
            print(f"  [wikipedia] rate limited, waiting {wait}s")
            time.sleep(wait)


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def search(query, limit=ARTICLES):
    """Specific articles only: the overview articles match every query and cite everything."""
    hits = _api(action="query", list="search", srsearch=query, srlimit=str(limit + 4))["query"]["search"]
    return [h["title"] for h in hits
            if "(disambiguation)" not in h["title"] and h["title"] not in GENERIC
            and not re.match(r"(\d{3,4}s? in |List of |Timeline of )", h["title"])][:limit]


def article(title):
    pages = _api(action="query", prop="extracts", explaintext="1", redirects="1", titles=title)["query"]["pages"]
    return pages[0].get("extract", "") if pages else ""


def query_for(title, year=None):
    """Search words: the page title without generic event words, plus the year."""
    words = [w for w in re.findall(r"[\w'-]+", title) if w.lower() not in STOP | EVENT_WORDS]
    return " ".join(words + ([str(year)] if year else []))


def find_articles(title, year=None):
    """Articles named like the event. "Hong Kong" anchors the search (without it, "St John's
    Cathedral 1849" finds Helsinki Cathedral); the year is tried second because it dilutes the
    title words; the overview articles are filtered out in search()."""
    key = _words(title) - EVENT_WORDS
    first = None
    for query in (query_for(title) + " Hong Kong", query_for(title, year) + " Hong Kong"):
        found = search(query)
        first = first or found
        named = [t for t in found if _words(t) & key]
        if named:
            return named
    return (first or [])[:1]


def reference_text(title, claims, year=None):
    """(text, sources, titles): the most relevant Wikipedia paragraphs for these claims."""
    want = _words(title + " " + " ".join(claims))
    titles = find_articles(title, year)
    scored, sources = [], []
    for t in titles:
        body = article(t)
        # The first article is the best match; any other must at least be about Hong Kong
        # ("Malta Police Force" matches "police force" but says nothing about Hong Kong).
        if not body or (t != titles[0] and "Hong Kong" not in body):
            continue
        sources.append({"title": f"Wikipedia: {t}",
                        "uri": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_"))})
        for para in body.split("\n"):
            para = para.strip()
            if len(para) < 80 or para.startswith("="):
                continue
            scored.append((len(want & _words(para)), t, para))
    scored.sort(key=lambda s: -s[0])
    out, size, used = [], 0, set()
    for score, t, para in scored:
        if score < MIN_PARA_OVERLAP or size + len(para) > MAX_CHARS:
            continue
        out.append(f"[{t}] {para}")
        size += len(para)
        used.add(t)
    # List only the articles whose text was actually compared.
    sources = [s for s in sources if s["title"].removeprefix("Wikipedia: ") in used]
    return "\n\n".join(out), sources, [t for t in titles if t in used]


CITE_RE = re.compile(r"\{\{\s*cite[^{}]*\}\}", re.I)


def _field(tpl, name):
    m = re.search(rf"\|\s*{name}\s*=\s*([^|}}]+)", tpl, re.I)
    return m.group(1).strip() if m else ""


def cited_sources(titles, claims):
    """Books/papers the articles cite that are most on-topic, with DOI/ISBN checked:
    [{"title", "url", "kind", "ok", "note"}]."""
    from research_import import check_doi, check_isbn
    want = _words(" ".join(claims))
    cites = []
    for t in titles:
        try:
            wikitext = _api(action="parse", prop="wikitext", page=t)["parse"]["wikitext"]
        except Exception:
            continue
        for tpl in CITE_RE.findall(wikitext):
            title = _field(tpl, "title")
            doi, isbn = _field(tpl, "doi"), re.sub(r"[^\dXx]", "", _field(tpl, "isbn"))
            if title and (doi or isbn) and len(want & _words(title)) >= MIN_CITE_OVERLAP:
                cites.append((len(want & _words(title)), title, doi, isbn, tpl))
    cites.sort(key=lambda c: -c[0])
    out, seen = [], set()
    for score, title, doi, isbn, tpl in cites:
        if len(out) >= MAX_CITES or (doi or isbn) in seen:
            continue
        seen.add(doi or isbn)
        if doi:
            ok, note = check_doi(doi, tpl)
            out.append({"title": title, "url": f"https://doi.org/{doi}", "kind": "DOI", "ok": ok, "note": note})
        else:
            ok, note = check_isbn(isbn, tpl)
            if ok is False and note.startswith("ISBN is") and not re.search(r"[A-Za-z]{3}", title):
                ok = None  # Chinese title vs romanised catalogue title: cannot compare
            out.append({"title": title, "url": f"https://openlibrary.org/isbn/{isbn}", "kind": "ISBN", "ok": ok, "note": note})
    return out
