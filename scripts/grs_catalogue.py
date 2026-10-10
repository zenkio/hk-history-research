"""Parser for metadata-only links in the Government Records Service catalogue.

This module uses only the Python standard library so the source adapter and the
connectivity probe exercise exactly the same HTML parsing logic.
"""
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

GRS_SEARCH_URL = "https://search.grs.gov.hk/en/search.xhtml"
DEFAULT_LIMIT = 6


class _GRSCatalogueParser(HTMLParser):
    """Extract record-detail links only; never treats catalogue metadata as a passage."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._active = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self._active is not None:
            return
        href = dict(attrs).get("href", "")
        if "eid=" in href and ("redirect.xhtml" in href or "arcview.xhtml" in href):
            self._active = {"href": href, "text": []}

    def handle_data(self, data):
        if self._active is not None:
            self._active["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._active is None:
            return
        href = self._active["href"]
        title = re.sub(r"\\s+", " ", " ".join(self._active["text"])).strip()
        self._active = None
        if title and href:
            self.results.append({"title": title, "href": href})


def parse_grs_catalogue_results(html, query, limit=DEFAULT_LIMIT):
    """Return deduplicated GRS record-link candidates as metadata-only items."""
    parser = _GRSCatalogueParser()
    parser.feed(html)
    results, seen = [], set()
    for row in parser.results:
        href = urljoin(GRS_SEARCH_URL, row["href"])
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        eid = (params.get("eid") or [""])[0]
        if not eid:
            continue
        record_query = (params.get("q") or [query])[0]
        locator = (params.get("ls") or [f"q={record_query}"])[0]
        detail_url = GRS_SEARCH_URL.replace("/search.xhtml", "/arcview.xhtml") + "?" + urlencode({
            "q": record_query, "eid": eid, "ls": locator,
        })
        if detail_url in seen:
            continue
        seen.add(detail_url)
        title = row["title"][:500]
        results.append({
            "kind": "archive record",
            "grade": "A",
            "year": None,
            "title": title,
            "url": detail_url,
            "cite": f"Government Records Service, {title}.",
            "catalogue_reference": None,
            "note": "Online catalogue result only. Record title and catalogue metadata are not an inspected historical passage.",
            "passage": "",
            "passage_status": "metadata_only",
            "locator": "Government Records Service online catalogue record (metadata only)",
        })
        if len(results) >= max(1, limit):
            break
    return results
