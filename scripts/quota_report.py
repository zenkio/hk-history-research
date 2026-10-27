#!/usr/bin/env python3
"""Print how much of each experiment model's quota is left today and which run sizes fit (owner question
2026-10-27: are we sure the quota is enough?). Read-only: it makes no model call. The gateway's own
numbers (per-model rate, next free time) are printed by the pool as it starts; this adds one line per
model with the day's calls left and what each mode needs. Printed lines carry only model names and counts.
"""
from gemini_pool import ModelPool
from quota_preflight import ESTIMATE, RUN_MINUTES, minutes_needed
from score_extraction_models import ROLE


def report(pool):
    lines = []
    for name in pool.routing.get(ROLE, []):
        if name not in pool.models:
            continue
        left = pool.remaining(name, ROLE)
        fits = [mode for mode, need in sorted(ESTIMATE.items(), key=lambda kv: kv[1])
                if left >= need and minutes_needed(pool, name, need) <= RUN_MINUTES]
        slow = [mode for mode, need in ESTIMATE.items() if left >= need and mode not in fits]
        lines.append(f"{name} | {pool.models[name].get('provider', 'google')} | {left} calls left today | "
                     f"fits: {', '.join(fits) or 'nothing'}" + (f" | too slow for: {', '.join(slow)}" if slow else ""))
    return lines


def main():
    pool = ModelPool()
    for line in report(pool):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
