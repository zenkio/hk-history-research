#!/usr/bin/env python3
"""Independent model review of a design document (owner rule 2026-10-26: Claude must not be the only judge
of the source weighting scheme).

Each listed model reads the document alone and answers with a verdict, the rules it thinks are wrong or
risky, and what it would change. The models never see each other's answers, and the review is a list of
objections to weigh, not a verdict on the history: agreement between models is not evidence. The document
and the answers are private research data: output goes to the private experiment branch, printed lines
carry only model names and counts.
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from score_extraction_models import ROLE, OutOfTime, open_for_trial, trial_ask

VERDICTS = ("sound", "needs_changes", "unsound")
MAX_PROBLEMS = 8


def prompt_for(document):
    return ("You are an independent reviewer of a design for weighting historical sources (reliability weights that vary "
            "by topic and period, challenges between sources, and a per-claim confidence). Review it critically: find "
            "rules that are wrong, circular, easy to game, or that would give false confidence, and numbers with no "
            "justification. Do not praise it.\n\n"
            f"DOCUMENT:\n{document}\n\n"
            'Answer with one JSON object only: {"verdict": "sound|needs_changes|unsound", "problems": '
            '[{"rule": "which rule or section", "issue": "what is wrong", "change": "what you would do instead"}]} '
            f"with at most {MAX_PROBLEMS} problems, most serious first.")


def parse_review(text):
    """{verdict, problems} from a model's reply, or None when it cannot be read."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        verdict = data["verdict"]
        raw = data["problems"]
    except (ValueError, KeyError, TypeError):
        return None
    if verdict not in VERDICTS or not isinstance(raw, list):
        return None
    problems = [{k: str(p.get(k, "")) for k in ("rule", "issue", "change")}
                for p in raw if isinstance(p, dict) and p.get("issue")]
    return {"verdict": verdict, "problems": problems[:MAX_PROBLEMS]}


def review(asks, document, on_progress=None):
    """{model: review or None}; the models answer side by side and a partial result is kept."""
    prompt = prompt_for(document)
    results = {}

    def one(ask):
        try:
            text = ask(prompt)
        except OutOfTime:
            print("a model ran out of time or quota before it answered")
            return None
        got = parse_review(text)
        if got is None:  # lengths only: the reply may quote the private document
            print(f"a reply could not be read ({len(text or '')} characters)")
        return got

    with ThreadPoolExecutor(max_workers=len(asks) or 1) as workers:
        futures = {workers.submit(one, ask): model for model, ask in asks.items()}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            if on_progress:
                on_progress(results)
    return results


def summarise(results):
    answered = {m: r for m, r in results.items() if r}
    counts = {v: sum(1 for r in answered.values() if r["verdict"] == v) for v in VERDICTS}
    return {"models_asked": len(results), "models_answered": len(answered), "verdicts": counts,
            "problems_listed": sum(len(r["problems"]) for r in answered.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=None)
    args = parser.parse_args(argv)

    from gemini_pool import ModelPool, QuotaExhausted, RequestRejected
    document = args.document.read_text(encoding="utf-8")
    pool = ModelPool()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    asks = {}
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        if name not in pool.routing.get(ROLE, []) or pool.remaining(name, ROLE) == 0:
            print(f"{name} | unavailable in this run")
            continue
        open_for_trial(pool, name)
        asks[name] = trial_ask(pool, name, deadline, [], [], max_rests=1)

    def guarded(ask):
        def run(prompt):
            try:
                return ask(prompt)
            except (QuotaExhausted, RequestRejected):
                raise OutOfTime() from None
        return run

    def save(results):
        args.output.write_text(json.dumps({
            "purpose": "independent model review of a design document; models did not see each other's answers",
            "document": args.document.name, "reviews": results, "summary": summarise(results)}, indent=1), encoding="utf-8")

    results = review({m: guarded(a) for m, a in asks.items()}, document, on_progress=save)
    save(results)
    summary = summarise(results)
    print(f"reviewed with {summary['models_asked']} models | answered {summary['models_answered']} | "
          f"verdicts {summary['verdicts']} | problems {summary['problems_listed']}")
    return 0 if summary["models_answered"] else 2


if __name__ == "__main__":
    sys.exit(main())
