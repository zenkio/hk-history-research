#!/usr/bin/env python3
"""Record required GitHub Actions step failures in the persistent seed plan."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from state import atomic_write

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = PROJECT_ROOT / "scripts" / "seed_plan.json"


def mark_plan_failure(plan_path, outcomes, now=None):
    """Set last_run to partial_failure and preserve prior worker failure details."""
    plan_path = Path(plan_path)
    if not plan_path.is_file():
        raise FileNotFoundError(f"Seed plan not found: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    failed = []
    for item in outcomes.split(","):
        if "=" not in item:
            continue
        stage, outcome = (part.strip() for part in item.split("=", 1))
        if stage and outcome in {"failure", "timed_out"}:
            failed.append({"stage": stage, "error": f"GitHub Actions step outcome: {outcome}"})
    if not failed:
        return 0

    last_run = plan.get("last_run")
    if not isinstance(last_run, dict):
        last_run = {}
    prior = last_run.get("failures", [])
    if not isinstance(prior, list):
        prior = []
    existing = {(row.get("stage"), row.get("error")) for row in prior if isinstance(row, dict)}
    for row in failed:
        if (row["stage"], row["error"]) not in existing:
            prior.append(row)
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    last_run.update({
        "finished_at": timestamp,
        "status": "partial_failure",
        "failures": prior,
    })
    plan["last_run"] = last_run
    atomic_write(str(plan_path), json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(f"Recorded partial pipeline failure for {len(failed)} failed stage(s) in {plan_path.name}.")
    return len(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", required=True, help="comma-separated stage=outcome pairs from GitHub Actions")
    parser.add_argument("--plan-path", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args(argv)
    try:
        mark_plan_failure(args.plan_path, args.outcomes)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Could not persist partial pipeline failure state: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
