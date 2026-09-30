"""FreeJev (https://freejev.org): structured judgments, not text generation.

One call sends a `state` (text) and up to 16 questions; each question is a Choice (named answers),
Yes/No or Score, and the answer comes back with probabilities. Input tokens are charged (1 credit per
1,000; the owner has the 10,000 free signup credits), output is free. Used as an independent auditor
of the evidence judge (`evidence.jev_audit`): a different kind of model, so its agreement says more
than a second LLM from the same family.

Limits: one request at a time per account, 30 a minute; 402 = no credits left; 502/504 = upstream
failure, not charged. Inference runs remotely (OpenRouter), like our other judges: never send
licensed text (Trove) here.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

URL = "https://freejev.org/api/v1/decisions"
MAX_QUESTIONS = 16
RESERVE_CREDITS = 500  # stop before the balance runs out, so a manual test still has credits

_state = {"off": None, "remaining": None}  # why Jev is off for this run, last known balance


def available():
    return bool((os.environ.get("FREEJEV_API_KEY") or "").strip()) and not _state["off"]


def _off(reason):
    _state["off"] = reason
    print(f"  [jev] off for this run: {reason}")


def _post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['FREEJEV_API_KEY'].strip()}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def decide(state, questions):
    """Ask up to 16 questions about `state`; returns the raw `answers` dict, or None if Jev could not
    answer (the reason is logged, and Jev is switched off for the run when retrying cannot help)."""
    if not available():
        return None
    body = {"state": state, "questions": questions}
    for attempt in range(2):
        try:
            data = _post(body)
        except urllib.error.HTTPError as e:
            code = e.code
            if code == 402:
                _off("no credits left (402)")
            elif code in (401, 403):
                _off(f"key rejected ({code}); check the FREEJEV_API_KEY secret")
            elif code == 429 and attempt == 0:
                time.sleep(60)
                continue
            elif code in (502, 504) and attempt == 0:
                time.sleep(10)  # upstream failure: not charged, worth one retry
                continue
            else:
                print(f"  [jev] HTTP {code}; skipped")
            return None
        except Exception as e:
            print(f"  [jev] request failed: {str(e)[:80]}")
            return None
        usage = data.get("usage") or {}
        remaining = next((usage[k] for k in ("remaining_credits", "credits_remaining", "remaining")
                          if isinstance(usage.get(k), (int, float))), None)
        if remaining is not None:
            _state["remaining"] = remaining
            if remaining < RESERVE_CREDITS:
                _off(f"{remaining:.0f} credits left, keeping them in reserve")
        return data.get("answers") or {}
    return None


def choice_of(answer, labels):
    """(label, probability) from a Choice answer, whatever shape it comes in: a label, a dict naming
    the label ("choice"/"answer"/"label"/...), or a dict of probabilities by label. None if unreadable."""
    if isinstance(answer, str):
        return (answer, None) if answer in labels else None
    if not isinstance(answer, dict):
        return None
    probs = next((answer[k] for k in ("probabilities", "probs", "distribution", "scores")
                  if isinstance(answer.get(k), dict)), None)
    if probs is None and answer and all(k in labels for k in answer):
        probs = answer
    label = next((answer[k] for k in ("choice", "answer", "label", "selected", "value", "result")
                  if isinstance(answer.get(k), str) and answer[k] in labels), None)
    if probs:
        probs = {k: float(v) for k, v in probs.items() if k in labels and isinstance(v, (int, float))}
    if label is None and probs:
        label = max(probs, key=probs.get)
    if label is None:
        return None
    return label, (probs or {}).get(label)


def shape(answer):
    """Field names and types of an answer, for the log when it can't be read (never its content)."""
    if isinstance(answer, dict):
        return "{" + ", ".join(f"{k}: {type(v).__name__}" for k, v in list(answer.items())[:8]) + "}"
    return type(answer).__name__
