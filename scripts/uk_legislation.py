"""Bounded, rate-limited search of official UK legislation relevant to Hong Kong history.

The site permits legislation reuse under the Open Government Licence with attribution.
This adapter only searches legislation-like titles, reads one matching official text page,
and preserves the source passage for claim-specific judgement. It is not a general crawler.
"""
from html.parser import HTMLParser
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urljoin, urlsplit

HOST = "www.legislation.gov.uk"
BASE_URL = f"https://{HOST}"
USER_AGENT = "hk-history-research/1.0 (+https://github.com/zenkio/hk-history-research)"
MIN_REQUEST_INTERVAL_SECONDS = 5
MAX_RESPONSE_BYTES = 256 * 1024
MAX_PASSAGE_CHARS = 5000
MIN_PASSAGE_CHARS = 100

_LEGAL_QUERY = re.compile(
    r"\b(act|ordinance|bill|legislation|nationality|citizenship|immigration|"
    r"constitutional|law|council|election|decolonisation|decolonization)\b",
    re.I,
)
_GENERIC_TERMS = {"act", "ordinance", "bill", "legislation", "law", "council"}
_RESULT_PATH = re.compile(r"/[a-z]{2,10}/\d{4}/\d+$")
_last_request_at = None
_rate_lock = threading.Lock()


class _SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow legislation requests off the approved HTTPS host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname != HOST:
            raise urllib.error.HTTPError(
                req.full_url, code, "redirect outside approved legislation host", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _pace_request():
    """Respect the published five-second crawl delay, serialising concurrent callers."""
    global _last_request_at
    with _rate_lock:
        now = time.monotonic()
        if _last_request_at is not None:
            wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
            if wait > 0:
                time.sleep(wait)
        _last_request_at = time.monotonic()


def _fetch_html(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise ValueError("Only HTTPS URLs on legislation.gov.uk are permitted")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    _pace_request()
    opener = urllib.request.build_opener(_SameHostRedirectHandler())
    with opener.open(request, timeout=20) as response:
        status = getattr(response, "status", 200)
        if status < 200 or status >= 300:
            raise ValueError(f"Unexpected legislation HTTP status: {status}")
        if "html" not in response.headers.get("Content-Type", "").casefold():
            raise ValueError("Legislation endpoint returned a non-HTML response")
        if urlsplit(response.geturl()).hostname != HOST:
            raise ValueError("Legislation response left the approved host")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    return raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")


class _SearchLinkParser(HTMLParser):
    """Extract official legislation title links only; ignore external and non-legislation links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "a" and self._href is None:
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() != "a" or self._href is None:
            return
        href = self._href
        title = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        self._href = None
        self._parts = []
        if not href or not title:
            return
        url = urljoin(BASE_URL, href)
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname == HOST
            and _RESULT_PATH.fullmatch(parsed.path.rstrip("/"))
        ):
            self.links.append((title, f"{BASE_URL}{parsed.path.rstrip('/')}"))


class _VisibleTextParser(HTMLParser):
    """Prefer the legislation body container; otherwise use visible page text as a fallback."""

    SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "form", "button", "svg"}
    TARGET_IDS = {"viewLegContents", "viewLegContentsContainer", "legislation-content"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self._skip_depth = 0
        self._content_depth = None
        self._fallback = []
        self._content = []

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        values = dict(attrs)
        depth = len(self._stack) + 1
        if self._content_depth is None and values.get("id") in self.TARGET_IDS:
            self._content_depth = depth
        parent_skips = self._skip_depth > 0
        skip = parent_skips or tag in self.SKIP_TAGS
        self._stack.append((tag, skip))
        if skip:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        tag = tag.casefold()
        index = next((i for i in range(len(self._stack) - 1, -1, -1) if self._stack[i][0] == tag), None)
        if index is None:
            return
        removed = self._stack[index:]
        self._skip_depth -= sum(1 for _, skipped in removed if skipped)
        self._stack = self._stack[:index]
        if self._content_depth is not None and self._content_depth > len(self._stack):
            self._content_depth = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        self._fallback.append(data)
        if self._content_depth is not None and len(self._stack) >= self._content_depth:
            self._content.append(data)

    def text(self):
        target = " ".join(self._content)
        fallback = " ".join(self._fallback)
        raw = target if len(target.strip()) >= MIN_PASSAGE_CHARS else fallback
        return re.sub(r"\s+", " ", raw).strip()[:MAX_PASSAGE_CHARS]


def _parse_search_links(html):
    parser = _SearchLinkParser()
    parser.feed(html)
    return parser.links


def _extract_passage(html):
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser.text()


def _query_is_relevant(query):
    if not _LEGAL_QUERY.search(query):
        return False
    tokens = [token.casefold() for token in re.findall(r"[a-z0-9]+", query)]
    return any(token not in _GENERIC_TERMS and len(token) > 1 for token in tokens)


def search(query):
    """Search legislation by title and return at most one inspectable, rights-cleared passage."""
    if not isinstance(query, str) or not query.strip():
        return []
    query = re.sub(r"\s+", " ", query).strip()[:160]
    if not _query_is_relevant(query):
        return []

    search_url = f"{BASE_URL}/search?{urllib.parse.urlencode({'title': query})}"
    search_html = _fetch_html(search_url)
    links = _parse_search_links(search_html)
    if not links:
        return []

    query_tokens = {token.casefold() for token in re.findall(r"[a-z0-9]+", query)}
    ranked = sorted(
        links,
        key=lambda item: sum(
            token in {t.casefold() for t in re.findall(r"[a-z0-9]+", item[0])}
            for token in query_tokens
        ),
        reverse=True,
    )
    title, url = ranked[0]
    path_parts = [part for part in urlsplit(url).path.split("/") if part]
    year = next((part for part in path_parts if re.fullmatch(r"\d{4}", part)), "")
    html = _fetch_html(url)
    passage = _extract_passage(html)
    status = "inspectable_text" if len(passage) >= MIN_PASSAGE_CHARS else "metadata_only"
    reference = urlsplit(url).path.lstrip("/")
    attribution = "Contains public sector information licensed under the Open Government Licence v3.0."
    return [{
        "kind": "legislation",
        "grade": "A",
        "year": year or "unknown",
        "title": title,
        "url": url,
        "catalogue_reference": reference,
        "cite": f"*{title}*, legislation.gov.uk ({year or 'n.d.'}). {attribution}",
        "note": "Official UK legislation text. Check the displayed version and any item-specific contributor notice.",
        "passage": passage if status == "inspectable_text" else "",
        "passage_status": status,
        "rights_status": "open_government_licence" if status == "inspectable_text" else "not_verified",
        "locator": "Official legislation text as displayed at source",
    }]
