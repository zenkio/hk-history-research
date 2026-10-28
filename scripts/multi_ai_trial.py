#!/usr/bin/env python3
"""Multi-AI draft trial: several different free models each write their own factual draft of the same
Hong Kong history event, so the drafts can be compared (owner direction 2026-10-28).

Every call goes to the owner's AI gateway (`POST /v1/run`, `llm.generate`) with one model pinned
(`options.models`), temperature 0 and a seed, and a large `maxOutputTokens` (the gateway default of 2,048
cuts a page off). The gateway reports what it really did in `choice`: `temperatureApplied` (a number,
"ignored" or "unknown"), `seedApplied` and `finishReason`; these are stored with every answer.

Also a repeat test: the same event and model asked several times, to see how often temperature 0 plus a
seed gives identical text.

The drafts are AI hypotheses: they never touch `content/`, they are written to an output folder only, and
the log prints counts only (the repository is public, the events and answers are private). Free models
only: a billed answer stops the run. Needs AI_GATEWAY_TOKEN.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY_URL = "https://aigateway.zenkio.uk"
# Cloudflare in front of the gateway refuses Python's default user agent (error 1010).
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
MAX_OUTPUT_TOKENS = 6000
DEFAULT_SEED = 20261028
# OpenRouter's free pool allows 8 calls a minute per model; stay under it.
MIN_GAP_PER_MODEL_S = 9
MAX_RATE_WAIT_S = 120

SYSTEM = ("You are a careful historian of Hong Kong, China and Britain. Write plainly and factually. "
          "Give only what you are confident of; where unsure, say 'uncertain' and do not guess dates, "
          "numbers or names. Do not invent sources or quotations.")


class QuotaExhausted(Exception):
    pass


def prompt_for(event):
    year = f" (about {event['year']})" if event.get("year") else ""
    return (f"Event: {event['title']}{year}\n\n"
            "Write a factual draft for a history timeline, with these headings:\n"
            "1. What happened: when, where, who, in short.\n"
            "2. Background: why it happened.\n"
            "3. Hong Kong at this time.\n"
            "4. China at this time.\n"
            "5. Britain at this time (what Britain needed or wanted, if relevant).\n"
            "6. Consequences.\n"
            "7. Uncertain or disputed points.\n"
            "Keep it under 700 words.")


def request_body(event, model, seed):
    return {"capability": "llm.generate",
            "input": {"system": SYSTEM, "prompt": prompt_for(event)},
            "options": {"task": "general", "models": [model], "temperature": 0, "seed": seed,
                        "maxOutputTokens": MAX_OUTPUT_TOKENS}}


def post_gateway(body, token, key):
    """One call. Returns the parsed answer; raises QuotaExhausted, or Exception with the gateway's code."""
    req = urllib.request.Request(f"{GATEWAY_URL}/v1/run", data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": USER_AGENT, "Idempotency-Key": key})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                err = json.loads(raw).get("error") or {}
            except ValueError:
                err = {}
            code = err.get("code", "")
            if code == "quota_exhausted":
                raise QuotaExhausted(code)
            if code == "rate_limited" and attempt == 1:
                wait = min(float(e.headers.get("Retry-After") or 30), MAX_RATE_WAIT_S)
                time.sleep(wait)
                continue
            raise Exception(f"{e.code} {code} {(err.get('message') or '')[:400]}".strip())
    raise Exception("rate_limited twice")


def record_of(event, model, data):
    """What is stored for one answer: the text plus what the gateway says it really did."""
    choice = data.get("choice") or {}
    usage = data.get("usage") or {}
    if usage.get("billing", "free") != "free" or usage.get("costUsd"):
        raise QuotaExhausted("paid answer refused; free models only")
    text = (data.get("output") or {}).get("text") or ""
    return {"event": event["id"], "asked_model": model, "answered_model": usage.get("modelId") or usage.get("model"),
            "temperature_applied": choice.get("temperatureApplied"), "seed_applied": choice.get("seedApplied"),
            "finish_reason": choice.get("finishReason"), "words": len(text.split()),
            "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}


def run_trial(events, models, seed, post, repeat_event=None, repeats=0, sleep=time.sleep):
    """Draft every event with every pinned model, then the repeat test. `post(body, key)` makes one call."""
    records, failures, last_call = [], [], {}

    def ask(event, model, key):
        gap = MIN_GAP_PER_MODEL_S - (time.time() - last_call.get(model, 0))
        if gap > 0:
            sleep(gap)
        last_call[model] = time.time()
        return record_of(event, model, post(request_body(event, model, seed), key))

    for event in events:
        for model in models:
            try:
                records.append(ask(event, model, f"draft-{event['id']}-{model}-{seed}"))
            except QuotaExhausted:
                failures.append({"event": event["id"], "model": model, "error": "quota_exhausted"})
                return records, [], failures
            except Exception as exc:
                failures.append({"event": event["id"], "model": model, "error": str(exc)[:450]})
    repeat = []
    target = next((e for e in events if e["id"] == repeat_event), None)
    if target and repeats > 1:
        for model in models:
            hashes = []
            for i in range(repeats):
                try:
                    # a new idempotency key each time, or the gateway would replay the first answer
                    hashes.append(ask(target, model, f"repeat-{target['id']}-{model}-{seed}-{i}")["sha256"])
                except QuotaExhausted:
                    failures.append({"event": target["id"], "model": model, "error": "quota_exhausted"})
                    break
                except Exception as exc:
                    failures.append({"event": target["id"], "model": model, "error": str(exc)[:450]})
            if hashes:
                repeat.append({"model": model, "calls": len(hashes), "distinct_answers": len(set(hashes))})
    return records, repeat, failures


def summarise(records, repeat, failures):
    """Counts only (this goes to a public log)."""
    lines = [f"answers: {len(records)}, failures: {len(failures)}"]
    for model in sorted({r["asked_model"] for r in records}):
        rows = [r for r in records if r["asked_model"] == model]
        applied = {}
        for r in rows:
            applied[str(r["temperature_applied"])] = applied.get(str(r["temperature_applied"]), 0) + 1
        truncated = sum(1 for r in rows if r["finish_reason"] == "length")
        lines.append(f"{model}: {len(rows)} answers, temperature_applied {applied}, truncated {truncated}")
    errors = {}
    for f in failures:
        errors[f["error"]] = errors.get(f["error"], 0) + 1
    for error, count in sorted(errors.items()):
        lines.append(f"failure x{count}: {error}")
    for row in repeat:
        lines.append(f"repeat {row['model']}: {row['calls']} calls, {row['distinct_answers']} distinct answers")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("events", help="JSON file: a list of {id, title, year}")
    ap.add_argument("--models", required=True, help="comma-separated gateway model names (pinned, one per answer)")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--repeat-event", default=None)
    ap.add_argument("--repeats", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="only the first N events (0 = all)")
    args = ap.parse_args(argv)
    token = (os.environ.get("AI_GATEWAY_TOKEN") or "").strip()
    if not token:
        print("AI_GATEWAY_TOKEN is not set; nothing was run")
        return 1
    events = json.loads(Path(args.events).read_text(encoding="utf-8"))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.limit:
        events = events[:args.limit]
    if not events or not models:
        print("no events or no models")
        return 1
    records, repeat, failures = run_trial(events, models, args.seed, lambda body, key: post_gateway(body, token, key),
                                          args.repeat_event, args.repeats)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "drafts.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"repeat": repeat, "failures": failures}, indent=1), encoding="utf-8")
    print(summarise(records, repeat, failures))
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
