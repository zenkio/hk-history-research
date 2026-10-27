#!/usr/bin/env python3
"""Refuse to start an experiment run whose models cannot get through it (owner rule 2026-10-21).

Run 48 (a source review) started at 23:50 UTC with OpenRouter's day already spent, so only the gateway
answered and the run measured nothing. Before any run, each requested model must be available (key
present, not parked), have enough calls left for the mode, and, for OpenRouter and the gateway, the
provider must report it is free now. OpenRouter does not tell a free account how many calls it has used,
so the check reads the AI gateway's own count of the account's calls (GET /v1/quota, "dead: free daily
allowance used"); without a gateway token the OpenRouter day cannot be checked and the run is refused
unless --allow-unchecked is given. Printed lines carry only model names and counts.
"""
import argparse
import sys
from datetime import datetime, timezone

from score_extraction_models import ROLE

# Rough calls one model makes in a run of each mode (the whole answer key is 49 sentences).
ESTIMATE = {"review": 40, "document": 3, "score": 520, "consensus": 520, "links": 120, "extract": 150, "verify": 150}
FIRST_MODEL_ONLY = ("extract", "verify")
RUN_MINUTES = 90  # the scoring job stops its work at 100 minutes and saves what is done
GATEWAY_WAIT_LIMIT = 120  # seconds; a gateway free again sooner than this is fine (the pool waits for it)


def _seconds_until(text):
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when - datetime.now(timezone.utc)).total_seconds()


def openrouter_spent(pool):
    """The time OpenRouter's free allowance is back, if the gateway reports the account's day as used up."""
    for quota in pool.gateway_quota.values():
        for x in quota.get("models", []):
            reason = str(x.get("freeAtReason") or "")
            if str(x.get("rpmSource") or "").startswith("openrouter") and reason.startswith("dead") and "allowance" in reason:
                return x.get("freeAt") or "later"
    return None


def gateway_problem(pool, name):
    quota = pool.gateway_quota.get(name)
    if not quota:
        return "gateway quota unreadable"
    models = quota.get("models", [])
    if models and all(str(x.get("freeAtReason") or "").startswith("dead") for x in models if x.get("freeAt")) \
            and all(x.get("freeAt") for x in models):
        return f"every gateway model is used up until {min(str(x['freeAt']) for x in models)}"
    capacity = quota.get("capacity") or {}
    if capacity.get("freeNow") == 0:
        wait = _seconds_until(capacity.get("nextFreeAt"))
        if wait is not None and wait > GATEWAY_WAIT_LIMIT:
            return f"gateway not free for {int(wait)} s"
    return None


def minutes_needed(pool, name, need):
    """Minutes `need` calls take at the model's own pace: the gateway's reported minimum gap, else models.json rpm."""
    quota = pool.gateway_quota.get(name) or {}
    gap_ms = (quota.get("capacity") or {}).get("minIntervalMs")
    if gap_ms:
        return need * gap_ms / 60000
    rpm = pool.models.get(name, {}).get("rpm")
    return need / rpm if rpm else 0


def pace_notes(pool, models, need):
    """One line per model that cannot make all its calls inside the run, with the share it can make.
    Not a stop: the scoring modes save partial results, but the owner is told before the run (2026-10-27)."""
    notes = []
    for name in models:
        slow = minutes_needed(pool, name, need)
        if slow > RUN_MINUTES:
            notes.append(f"{name}: {need} calls need about {int(slow)} minutes at its pace; "
                         f"about {int(100 * RUN_MINUTES / slow)}% will be done in the {RUN_MINUTES}-minute run")
    return notes


def check(pool, models, need, allow_unchecked=False):
    """Problems that stop the run, one line each; an empty list means every model can start."""
    problems = []
    or_back = openrouter_spent(pool)
    has_gateway_data = bool(pool.gateway_quota)
    for name in models:
        if name not in pool.models:
            problems.append(f"{name}: not in models.json")
            continue
        if name not in pool.routing.get(ROLE, []):
            problems.append(f"{name}: not in routing role {ROLE}")
            continue
        provider = pool.models[name].get("provider")
        left = pool.remaining(name, ROLE)
        if left == 0:
            problems.append(f"{name}: unavailable (no key, rejected key or parked)")
        elif left < need and provider != "gateway":
            problems.append(f"{name}: {left} calls left today, the run needs about {need}")
        if provider == "openrouter":
            if or_back is not None:
                problems.append(f"{name}: OpenRouter's free allowance is used up until {or_back}")
            elif not has_gateway_data and not allow_unchecked:
                problems.append(f"{name}: OpenRouter's day cannot be checked without the gateway token")
        elif provider == "gateway":
            reason = gateway_problem(pool, name)
            if reason:
                problems.append(f"{name}: {reason}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", required=True, choices=sorted(ESTIMATE))
    parser.add_argument("--models", required=True)
    parser.add_argument("--spares", default="")
    parser.add_argument("--allow-unchecked", action="store_true")
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool
    names = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.mode in FIRST_MODEL_ONLY:
        names = names[:1]
    spares = [m.strip() for m in args.spares.split(",") if m.strip()]
    need = ESTIMATE[args.mode]
    pool = ModelPool()
    problems = check(pool, names + spares, need, args.allow_unchecked)
    # a spare only has to be usable if some listed model is not; report it but do not stop for it
    stopping = [p for p in problems if p.split(":")[0] in names]
    for p in problems:
        print(("STOP " if p in stopping else "note ") + p)
    for line in pace_notes(pool, names, need):
        print("slow " + line)
    if stopping:
        print(f"quota check failed for {len(stopping)} of {len(names)} models; not starting the run")
        return 1
    print(f"quota check passed for {len(names)} models (about {need} calls each)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
