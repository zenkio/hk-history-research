#!/usr/bin/env python3
"""What a consolidated page costs in AI calls and tokens (owner 2026-11-04), from data/consolidated_usage.json.

Numbers only, no page text. Tokens are estimates (characters / 4). `--price-in` / `--price-out` are dollars per million
tokens of a paid model to compare with: they are inputs, nothing here knows any provider's prices.

Usage (data checkout): usage_report.py [--price-in 0.5 --price-out 1.5] [--daily-calls 300]
"""
import argparse
import json
import sys
from pathlib import Path

import run_control as rc


def report(usage, price_in=None, price_out=None, daily_calls=rc.DEFAULT_DAILY_CALLS, root=Path(".")):
    pages = usage.get("pages", {})
    per_page = {}
    for page, steps in pages.items():
        tot = {"calls": 0, "failed": 0, "in": 0, "out": 0}
        for s in steps.values():
            for k in tot:
                tot[k] += s.get(k, 0)
        per_page[page] = tot
    # a page counts as complete once it has the step that comes last
    done = [p for p, s in pages.items() if "kidread" in s]
    basis = done or list(per_page)
    n = max(1, len(basis))
    avg = {k: sum(per_page[p][k] for p in basis) / n for k in ("calls", "failed", "in", "out")}
    out = {"pages_measured": len(per_page), "pages_complete": len(done), "average_per_page": {k: round(v) for k, v in avg.items()},
           "per_page": per_page,
           "per_step_average": {}, "pages_per_day_at_budget": round(daily_calls / avg["calls"], 1) if avg["calls"] else None}
    steps = {}
    for p in basis:
        for st, v in pages[p].items():
            d = steps.setdefault(st, {"calls": 0, "in": 0, "out": 0})
            for k in d:
                d[k] += v.get(k, 0)
    out["per_step_average"] = {st: {k: round(v / n) for k, v in d.items()} for st, d in steps.items()}
    if out["pages_per_day_at_budget"]:
        out["days_for_120_pages_at_budget"] = round(120 / out["pages_per_day_at_budget"], 1)
    if price_in is not None and price_out is not None:
        out["paid_cost_per_page_usd"] = round((avg["in"] * price_in + avg["out"] * price_out) / 1e6, 4)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-in", type=float)
    ap.add_argument("--price-out", type=float)
    ap.add_argument("--daily-calls", type=int, default=rc.DEFAULT_DAILY_CALLS)
    args = ap.parse_args(argv)
    usage = rc._load(Path(".") / rc.USAGE, {"days": {}, "pages": {}})
    print(json.dumps(report(usage, args.price_in, args.price_out, args.daily_calls), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
