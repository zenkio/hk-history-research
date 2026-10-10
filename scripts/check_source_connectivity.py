#!/usr/bin/env python3
"""Probe public source API endpoints from the current runtime without retaining source content.

This is a connectivity/schema smoke test, not a historical search and not permission to
send retrieved material to an AI service. Use --strict in CI/manual workflow to fail if
any endpoint is unreachable or returns an unexpected response shape.
"""
import argparse
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from grs_catalogue import parse_grs_catalogue_results

USER_AGENT = "hk-history-research-source-probe/1.0"
MAX_BYTES = 64 * 1024
PROBES = [
    {
        "name": "Hong Kong Public Libraries MMIS legacy hostname", "required": False,
        "url": "https://mmis.hkpl.gov.hk/",
        "format": "html",
        "shape": "Multimedia Information System",
    },
    {
        "name": "HKPL Digital Collection (current MMIS successor)", "required": False,
        "url": "https://sls.hkpl.gov.hk/digital-collection/en/",
        "format": "html",
        "shape": "Digital Collection",
    },
    {
        "name": "HKU Scholars Hub OAI-PMH", "required": False,
        "url": "https://hub.hku.hk/oai/request?verb=Identify",
        "format": "xml",
        "shape": "OAI-PMH",
    },
    {
        "name": "Hong Kong Government Records Service catalogue", "required": False,
        "url": "https://search.grs.gov.hk/en/search.xhtml?q=Hong%20Kong",
        "format": "html",
        "shape": "Search Results",
    },
    {
        "name": "HKUL DigitalRepository OAI-PMH candidate endpoint", "required": False,
        "url": "https://digitalrepository.lib.hku.hk/oai2?verb=Identify",
        "format": "xml",
        "shape": "OAI-PMH",
    },
    {
        "name": "HK Historical Laws Omeka API", "required": False,
        "url": "https://oelawhk.lib.hku.hk/api/items?per_page=1",
        "format": "json",
        "shape": "list",
    },
    {
        "name": "LegCo Hansard open data", "required": False,
        "url": "https://app.legco.gov.hk/OpenData/HansardDB/Hansard?$top=1&$format=json",
        "format": "json",
        "shape": "value",
    },
    {
        "name": "UK National Archives Discovery API", "required": True,
        "url": "https://discovery.nationalarchives.gov.uk/API/search/records?sps.searchQuery=Hong%20Kong&sps.resultsPageSize=1&sps.heldByCode=TNA",
        "format": "json",
        "shape": "records",
    },
]


def inspect_response(probe, status, content_type, body):
    if status < 200 or status >= 300:
        return False, f"HTTP {status}"
    if not body:
        return False, "empty response"
    try:
        if probe["format"] == "xml":
            root = ET.fromstring(body)
            ok = probe["shape"] in root.tag
        elif probe["format"] == "html":
            decoded = body.decode("utf-8", errors="replace")
            page = decoded.casefold()
            ok = "<html" in page and probe["shape"].casefold() in page
            if not ok:
                title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, flags=re.I | re.S)
                title = re.sub(r"<[^>]+>", " ", title_match.group(1)).strip()[:120] if title_match else "no title tag"
                return False, f"unexpected HTML response shape; title={title!r}"
        else:
            data = json.loads(body.decode("utf-8"))
            if probe["shape"] == "list":
                ok = isinstance(data, list)
            else:
                ok = isinstance(data, dict) and any(str(key).casefold() == probe["shape"].casefold() for key in data)
        if not ok:
            return False, f"unexpected {probe['format'].upper()} response shape"
    except (ValueError, ET.ParseError, UnicodeError) as exc:
        return False, f"invalid {probe['format'].upper()} response: {type(exc).__name__}"
    return True, f"HTTP {status}; {content_type or 'content type unknown'}; {len(body)} bytes"


def inspect_bounded_response(probe_spec, status, content_type, body):
    """Validate response shape within the byte budget; HTML probes need only a bounded sample."""
    if len(body) > MAX_BYTES:
        if probe_spec.get("format") == "html":
            ok, detail = inspect_response(probe_spec, status, content_type, body[:MAX_BYTES])
            if ok:
                return True, f"{detail}; inspected first {MAX_BYTES} bytes only (response truncated)"
        return False, f"response exceeded {MAX_BYTES} byte safety limit"
    return inspect_response(probe_spec, status, content_type, body)


def probe(probe_spec, timeout=15):
    request = urllib.request.Request(
        probe_spec["url"],
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            ok, detail = inspect_bounded_response(
                probe_spec,
                getattr(response, "status", 200),
                response.headers.get("Content-Type", ""),
                body,
            )
            if probe_spec.get("name") == "Hong Kong Government Records Service catalogue" and ok:
                sample = body[:MAX_BYTES].decode("utf-8", errors="replace")
                candidates = parse_grs_catalogue_results(sample, "Hong Kong")
                count = len(candidates)
                if count == 0:
                    return False, f"{detail}; parser found 0 metadata-only record links in bounded sample"
                return True, f"{detail}; parser found {count} metadata-only record link(s) in bounded sample"
            return ok, detail
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any required probe fails")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args(argv)
    required_total = sum(1 for item in PROBES if item.get("required", True))
    required_failures = optional_failures = required_passes = optional_passes = 0
    for item in PROBES:
        ok, detail = probe(item, timeout=args.timeout)
        required = item.get("required", True)
        status = "PASS" if ok else ("FAIL" if required else "WARN")
        print(f'{status} | {item["name"]} | {detail}')
        if required:
            required_passes += int(ok)
            required_failures += int(not ok)
        else:
            optional_passes += int(ok)
            optional_failures += int(not ok)
    print(f"Required endpoints: {required_passes}/{required_total} passed")
    print(f"Optional probes: {optional_passes}/{len(PROBES) - required_total} passed; {optional_failures} warning(s)")
    return 1 if args.strict and required_failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
