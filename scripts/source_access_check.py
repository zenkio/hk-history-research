#!/usr/bin/env python3
"""Check which candidate sources the pipeline can actually read (first step of the Yearbook spot-check,
research/YEARBOOK_SPOTCHECK_DESIGN.md in the data repository).

For every candidate in the given file this fetches the page once and records the HTTP status, whether it
looks like a login, paywall or access-form page, whether rights wording (copyright, terms of use) appears
on it, and the Internet Archive's closest copy. Only metadata and a SHA-256 are written: pages are not
saved. A source the pipeline cannot read goes to the access-blocked list with what a helper (a person with
a library account, or another assistant) would need to supply; nothing is guessed. Makes no AI call.
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.error
from pathlib import Path

import source_snapshot as snap

LOGIN_CUES = re.compile(r"(log ?in|sign ?in|subscribe|subscription|members? only|paywall|captcha|access denied|"
                        r"登入|登錄|登录|會員|订阅|訂閱)", re.I)
RIGHTS_CUES = re.compile(r"(copyright|all rights reserved|terms (of use|and conditions)|reproduc|版權|版权|使用條款|使用条款)", re.I)
BLOCKED = ("login_or_paywall", "forbidden", "not_found", "error")


def classify(http_status, text):
    """(state, note) for one fetched page: reachable, or why it is blocked."""
    if http_status in (401, 402):
        return "login_or_paywall", f"HTTP {http_status}"
    if http_status == 403:
        return "forbidden", "HTTP 403 (blocked for this client)"
    if http_status == 404 or http_status == 410:
        return "not_found", f"HTTP {http_status}"
    if http_status and http_status >= 400:
        return "error", f"HTTP {http_status}"
    if text is None:
        return "reachable", "text not readable here (e.g. PDF without pypdf)"
    # A short page dominated by a login prompt is a gate; a long page that mentions "login" in a menu is not.
    if len(text) < 3000 and LOGIN_CUES.search(text):
        return "login_or_paywall", "short page with login or subscription wording"
    return "reachable", ""


def check_candidate(candidate, opener):
    record = {"id": candidate.get("id"), "name": candidate.get("name"), "url": candidate.get("url"),
              "for": candidate.get("for"), "checked_at": snap.now()}
    try:
        status, content_type, data, final_url = snap.fetch(candidate["url"], opener)
        text = snap.page_text(data, content_type)
        state, note = classify(status, text)
        record.update(state=state, note=note, http_status=status, final_url=final_url, content_type=content_type,
                      bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                      rights_wording_found=bool(text and RIGHTS_CUES.search(text)))
    except urllib.error.HTTPError as exc:
        state, note = classify(exc.code, None)
        record.update(state=state, note=note, http_status=exc.code)
    except Exception as exc:
        record.update(state="error", note=f"{type(exc).__name__}: {str(exc)[:200]}")
    record["wayback"] = snap.wayback(candidate["url"], opener)
    return record


def blocked_entry(record):
    """One line of the access-blocked work list for a helper."""
    needs = {"login_or_paywall": "a person or helper with an account or subscription to read it and paste the page text",
             "forbidden": "a helper whose access this site allows (browser, library network, another assistant)",
             "not_found": "the correct current address, or confirmation that it no longer exists",
             "error": "a retry from another network, or a helper to open it"}[record["state"]]
    archived = " An Internet Archive copy exists." if record.get("wayback") else ""
    return {"id": record["id"], "name": record["name"], "url": record["url"], "wanted_for": record.get("for"),
            "why_blocked": record.get("note") or record["state"], "needs": needs + "." + archived}


def run(candidates, opener):
    records = [check_candidate(c, opener) for c in candidates if c.get("url")]
    blocked = [blocked_entry(r) for r in records if r["state"] in BLOCKED]
    return records, blocked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    candidates = json.loads(args.candidates.read_text(encoding="utf-8")).get("candidates", [])
    import urllib.request
    records, blocked = run(candidates, urllib.request.urlopen)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("source-access.json", {"purpose": "reachability of candidate sources; pages are not saved",
                                                "results": records}),
                       ("access-blocked.json", {"purpose": "work list for helpers: sources the pipeline cannot read",
                                                "blocked": blocked})):
        (args.output_dir / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Counts only: names and URLs stay in the private output.
    print(f"source access | candidates={len(records)} | reachable={sum(r['state'] == 'reachable' for r in records)} "
          f"| blocked={len(blocked)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
