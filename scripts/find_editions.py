#!/usr/bin/env python3
"""List which editions of a publication the Internet Archive holds, year by year (step 1 of the Yearbook
spot-check, research/YEARBOOK_SPOTCHECK_DESIGN.md in the data repository).

Each query in the given file is searched in the Archive's public search (title words and a year range).
For every hit this records identifier, title, year, media type, the licence URL or rights note the item
carries and its details link; years with no hit are written to the access-blocked work list so a helper
(a person with a library account, or another assistant) can look elsewhere. Only metadata is written; no
item is downloaded and no AI call is made. Rights are recorded, not judged: an item is readable for
internal processing only under the project's rights rule.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import source_snapshot as snap

SEARCH = "https://archive.org/advancedsearch.php"
FIELDS = ("identifier", "title", "year", "mediatype", "licenseurl", "rights", "creator")


def search_url(query, first_year, last_year, rows=100):
    q = f"({query}) AND year:[{first_year} TO {last_year}]"
    params = [("q", q), ("rows", str(rows)), ("output", "json")] + [("fl[]", f) for f in FIELDS]
    return SEARCH + "?" + urllib.parse.urlencode(params)


def find(spec, opener):
    """(items, error) for one query spec {id, query, first_year, last_year}."""
    try:
        _, _, data, _ = snap.fetch(search_url(spec["query"], spec["first_year"], spec["last_year"]), opener)
        docs = json.loads(data).get("response", {}).get("docs", [])
    except Exception as exc:
        return [], f"{type(exc).__name__}: {str(exc)[:200]}"
    items = [{"identifier": d.get("identifier"), "title": d.get("title"), "year": str(d.get("year") or ""),
              "mediatype": d.get("mediatype"), "licenseurl": d.get("licenseurl"), "rights": d.get("rights"),
              "details": f"https://archive.org/details/{d.get('identifier')}"} for d in docs]
    return items, None


def years_missing(items, first_year, last_year):
    have = {i["year"][:4] for i in items}
    return [str(y) for y in range(first_year, last_year + 1) if str(y) not in have]


def run(specs, opener):
    results, blocked = [], []
    for spec in specs:
        items, error = find(spec, opener)
        missing = years_missing(items, spec["first_year"], spec["last_year"])
        results.append({"id": spec["id"], "query": spec["query"], "first_year": spec["first_year"],
                        "last_year": spec["last_year"], "error": error, "items": items, "years_missing": missing})
        if error or missing:
            blocked.append({"id": spec["id"], "name": spec.get("name", spec["id"]), "wanted_for": spec.get("for"),
                            "why_blocked": error or "no Internet Archive item found for these years: " + ", ".join(missing),
                            "needs": "a person or helper to look for these editions elsewhere (library, HKPL MMIS, "
                                     "publisher) and say where they can be read."})
    return results, blocked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queries", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    specs = json.loads(args.queries.read_text(encoding="utf-8")).get("queries", [])
    results, blocked = run(specs, urllib.request.urlopen)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "editions.json").write_text(json.dumps(
        {"purpose": "Internet Archive items per query and year; metadata only", "results": results},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "editions-blocked.json").write_text(json.dumps(
        {"purpose": "work list for helpers: editions not found on the Internet Archive", "blocked": blocked},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Counts only: titles stay in the private output.
    print(f"editions | queries={len(results)} | items={sum(len(r['items']) for r in results)} "
          f"| years missing={sum(len(r['years_missing']) for r in results)} "
          f"| errors={sum(bool(r['error']) for r in results)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
