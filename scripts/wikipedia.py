"""Reference text from English Wikipedia for fact-checking (no API key).

Google Search grounding is not available on the free tier for the models we can
use (Gemini 2.5 is closed to new users), so fact-checks read Wikipedia instead:
search for the page's topic, fetch the top articles as plain text, and keep the
paragraphs that share the most words with the claims. The model then judges each
claim against that text only. Wikipedia is a grade C (reference) source.
"""
import re
import json
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
ARTICLES = 2
MAX_CHARS = 7000  # ~2K tokens: fits Gemma's 16K TPM with room for the claims
STOP = set("the a an of and or in on at to for by with from was were is are be been as that this "
           "which it its his her their into after before during hong kong".split())


def _api(**params):
    params.update(format="json", formatversion="2")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def search(query, limit=ARTICLES):
    hits = _api(action="query", list="search", srsearch=query, srlimit=str(limit + 2))["query"]["search"]
    return [h["title"] for h in hits if "(disambiguation)" not in h["title"]][:limit]


def article(title):
    pages = _api(action="query", prop="extracts", explaintext="1", redirects="1", titles=title)["query"]["pages"]
    return pages[0].get("extract", "") if pages else ""


def reference_text(title, claims):
    """(text, sources): the most relevant Wikipedia paragraphs for these claims, with their articles."""
    want = _words(title + " " + " ".join(claims))
    scored, sources = [], []
    titles = search(f"{title} Hong Kong")
    for t in titles:
        body = article(t)
        if not body:
            continue
        sources.append({"title": f"Wikipedia: {t}",
                        "uri": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_"))})
        for para in body.split("\n"):
            para = para.strip()
            if len(para) < 80 or para.startswith("="):
                continue
            scored.append((len(want & _words(para)), t, para))
    scored.sort(key=lambda s: -s[0])
    out, size = [], 0
    for score, t, para in scored:
        if score == 0 or size + len(para) > MAX_CHARS:
            continue
        out.append(f"[{t}] {para}")
        size += len(para)
    return "\n\n".join(out), sources
