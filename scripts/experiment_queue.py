#!/usr/bin/env python3
"""Pick the next owner-approved experiment job whose quota fits right now (owner request 2026-10-27: run
experiments automatically when quota allows, without Claude). The queue is experiments/queue.json in the
data repository; only jobs the owner approved are in it. Each job runs once: the workflow marks it
`dispatched` after starting the scoring run. Nothing is picked while another experiment run is active
(the caller passes --busy), and the same quota preflight as a manual run decides whether the job fits.
Output goes to $GITHUB_OUTPUT (job_id, mode, models, document, limit); the log carries job ids and
model names only.
"""
import argparse
import json
import os
import sys

from quota_preflight import ESTIMATE, FIRST_MODEL_ONLY, check

QUEUE = "experiments/queue.json"
REQUIRED = ("id", "approved_by", "approved_on")
# The workflows a job may start. The scoring workflow uses AI quota; the access check makes no AI call.
SCORING = "v2-2-model-scoring.yml"
ACCESS_CHECK = "source-access-check.yml"
EDITION_FINDER = "edition-finder.yml"
# Workflows that make no AI call, with the job field naming the data-repository file each one reads.
NO_AI = {ACCESS_CHECK: "candidates", EDITION_FINDER: "queries"}


def load(path=QUEUE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"jobs": []}


def next_job(queue):
    """The first pending job that names an owner approval; an unapproved or malformed entry is skipped."""
    for job in queue.get("jobs", []):
        if job.get("status", "pending") != "pending":
            continue
        if any(not job.get(k) for k in REQUIRED):
            continue
        if job.get("workflow") in NO_AI:
            if not job.get(NO_AI[job["workflow"]]):
                continue
        elif job.get("workflow", SCORING) != SCORING or job.get("mode") not in ESTIMATE or not job.get("models"):
            continue
        return job
    return None


def models_of(job):
    if job.get("workflow") in NO_AI:
        return []
    names = [m.strip() for m in job["models"].split(",") if m.strip()]
    return names[:1] if job["mode"] in FIRST_MODEL_ONLY else names


def mark(queue, job_id, status="dispatched"):
    for job in queue.get("jobs", []):
        if job.get("id") == job_id:
            job["status"] = status
            return True
    return False


def decide(queue, pool, busy):
    """(job, reason): the job to start, or None and why not."""
    job = next_job(queue)
    if not job:
        return None, "no approved pending job"
    if busy:
        return None, "another experiment run is active"
    if job.get("workflow") in NO_AI:
        return job, "no AI quota needed"
    problems = check(pool, models_of(job), ESTIMATE[job["mode"]])
    if problems:
        return None, f"quota does not fit job {job['id']}: " + "; ".join(problems)
    return job, "quota fits"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--busy", action="store_true", help="another experiment run is queued or running")
    parser.add_argument("--mark", help="mark this job id as dispatched and save the queue")
    args = parser.parse_args(argv)

    queue = load()
    if args.mark:
        if not mark(queue, args.mark):
            print(f"no job {args.mark}")
            return 1
        with open(QUEUE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"job {args.mark} marked dispatched")
        return 0

    from gemini_pool import ModelPool
    pending = next_job(queue)
    needs_pool = pending and not args.busy and pending.get("workflow") not in NO_AI
    job, reason = decide(queue, ModelPool() if needs_pool else None, args.busy)
    print(f"queue: {reason}")
    if job and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            for key, value in (("job_id", job["id"]), ("workflow", job.get("workflow", SCORING)),
                               ("mode", job.get("mode", "")), ("models", job.get("models", "")),
                               ("document", job.get("document", "")), ("limit", job.get("limit", 0)),
                               ("input", job.get(NO_AI.get(job.get("workflow"), ""), ""))):
                out.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
