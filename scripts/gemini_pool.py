#!/usr/bin/env python3
"""Quota-aware Gemini model pool shared by the pipeline scripts.

Each free-tier model has its own requests-per-day (RPD) bucket, so for every
task ("role") the pool tries the models listed in models.json routing, in
order, and moves on only when a model is spent. It paces both requests per
minute and tokens per minute (the real limit on Gemma), persists usage in
quota_state.json so separate cron runs in one quota day share a budget, and
parks a model for the day on a real daily-quota 429 or when it does not exist.
"""
import os
import re
import json
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPTS_DIR, "models.json")
STATE_FILE = os.path.join(SCRIPTS_DIR, "quota_state.json")
EXPECTED_OUTPUT_TOKENS = 1500
TRANSIENT_TRIES = 4      # per request on large-quota models, for 503/500/timeouts
SCARCE_RPD = 50          # models this small move on after one overload error: Google still bills it
IDLE_CYCLES = 3          # full passes over the routing list before giving up on a transient outage
# Suffix tokens an API id may add to a configured name and still be the same model.
ALLOWED_EXTRA = re.compile(r"^(preview|latest|exp|it|a\d+b|\d+)$")


class QuotaExhausted(Exception):
    """No model serving the requested role has budget left today."""


def _is_daily_quota(msg):
    m = msg.lower()
    return "perday" in m or "per_day" in m or "per day" in m


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tokens(s):
    return [t for t in re.split(r"[^a-z0-9.]+", s.lower().replace("models/", "")) if t]


def _same_model(configured, candidate):
    """'gemini-3-flash' matches 'gemini-3-flash-preview'; 'gemma-4-26b-it' matches 'gemma-4-26b-a4b-it';
    but 'gemini-3-flash' never matches 'gemini-3-flash-lite' or '-image'."""
    want, have = _tokens(configured), _tokens(candidate)
    it = iter(have)
    if not all(any(t == h for h in it) for t in want):
        return False
    return all(ALLOWED_EXTRA.match(t) for t in have if t not in want)


def _is_transient(msg):
    return any(k in msg for k in ("503", "500", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED", "timed out", "overloaded"))


def _parse_json(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
        end = max(text.rfind("}"), text.rfind("]"))
        if not starts or end <= min(starts):
            raise
        return json.loads(text[min(starts):end + 1], strict=False)


def _sources(resp):
    """Web sources from a Google Search grounded response."""
    out = []
    try:
        chunks = resp.candidates[0].grounding_metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        return out
    for c in chunks:
        web = getattr(c, "web", None)
        if web and web.uri and web.uri not in {s["uri"] for s in out}:
            out.append({"title": web.title or web.uri, "uri": web.uri})
    return out


class ModelPool:
    def __init__(self):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            self.config = json.load(f)
        self.models = {m["display"]: m for m in self.config["models"]}
        self.routing = {k: v for k, v in self.config["routing"].items() if not k.startswith("_")}
        self.tz = ZoneInfo(self.config.get("quota_reset_timezone", "America/Los_Angeles"))
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.last_call = {}
        self.token_log = {}
        self.state = self._load_state()
        self._resolve_ids()

    # ---- setup -------------------------------------------------------
    def _resolve_ids(self):
        """Map AI Studio display names to real API ids, since ids change between releases."""
        try:
            available = [m for m in self.client.models.list()
                         if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"])]
        except Exception as e:
            print(f"  [pool] models.list failed ({str(e)[:80]}); using configured ids")
            available = []
        ids = [a.name.split("/")[-1] for a in available]
        for m in self.models.values():
            if m["id"] in ids or not ids:
                m["api_id"] = m["id"]
                continue
            hits = [a.name.split("/")[-1] for a in available
                    if _same_model(m["display"], getattr(a, "display_name", "") or "")
                    or _same_model(m["id"], a.name)]
            # Prefer stable ids over previews and dated snapshots.
            hits.sort(key=lambda n: ("preview" in n or "exp" in n, len(n)))
            m["api_id"] = hits[0] if hits else m["id"]
        self.state["resolved"] = {k: m["api_id"] for k, m in self.models.items()}
        # Kept in the committed state file so wrong ids can be fixed without a debug run.
        self.state["available"] = sorted(i for i in ids if i.startswith(("gemini", "gemma")))

    def _today(self):
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def _load_state(self):
        state = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        if state.get("day") != self._today():
            state = {"day": self._today(), "used": {}, "parked": {}}
        return state

    def save(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    # ---- budget ------------------------------------------------------
    def used(self, key):
        return self.state["used"].get(key, 0)

    def remaining(self, key, role):
        if key in self.state["parked"]:
            return 0
        left = self.models[key]["rpd"] - self.used(key)
        # Hold some budget on RSS-classifying models so ingestion later in the
        # day is never starved by bulk drafting.
        if role != "classify" and key in self.routing.get("classify", []):
            left -= self.config.get("reserve_for_ingestion", 0)
        return max(left, 0)

    def total_remaining(self, role):
        return sum(self.remaining(k, role) for k in self.routing.get(role, []))

    def summary(self):
        parts = []
        for key, m in self.models.items():
            if self.used(key) or key in self.state["parked"]:
                p = f"{key} {self.used(key)}/{m['rpd']}"
                if key in self.state["parked"]:
                    p += f" (parked: {self.state['parked'][key]})"
                parts.append(p)
        return ", ".join(parts) or "nothing used yet"

    def _park(self, key, reason):
        self.state["parked"][key] = reason
        self.save()
        print(f"  [pool] {key} parked for today: {reason}")

    def _pace(self, key, prompt):
        m = self.models[key]
        wait = self.last_call.get(key, 0) + 60.0 / m["rpm"] * 1.15 - time.time()
        if wait > 0:
            time.sleep(wait)
        # Tokens per minute: sliding 60s window of real usage.
        log = self.token_log.setdefault(key, deque())
        need = len(prompt) // 2 + EXPECTED_OUTPUT_TOKENS
        while True:
            now = time.time()
            while log and now - log[0][0] > 60:
                log.popleft()
            if not log or sum(t for _, t in log) + need <= m["tpm"]:
                break
            time.sleep(max(0.5, 60 - (now - log[0][0])))
        self.last_call[key] = time.time()

    def _record_tokens(self, key, resp, prompt):
        tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", None)
        self.token_log.setdefault(key, deque()).append((time.time(), tokens or len(prompt) // 2 + EXPECTED_OUTPUT_TOKENS))

    # ---- calls -------------------------------------------------------
    def generate_json(self, role, prompt, search=False):
        """Return (parsed_json, model_display_name, sources) from the best model with budget left.

        search=True enables Google Search grounding; sources then lists the web pages used.
        Transient server errors (503 "high demand" etc.) are retried with backoff and do not
        count against the daily budget; only when every model is out of budget, or still
        failing after IDLE_CYCLES passes, does this raise QuotaExhausted.
        """
        for cycle in range(IDLE_CYCLES):
            for key in self.routing.get(role, []):
                result = self._try_model(key, role, prompt, search)
                if result is not None:
                    return result
            if self.total_remaining(role) == 0:
                break
            wait = 60 * (cycle + 1)
            print(f"  [pool] all '{role}' models busy, waiting {wait}s before another pass")
            time.sleep(wait)
        raise QuotaExhausted(f"No budget left for role '{role}'. {self.summary()}")

    def _try_model(self, key, role, prompt, search):
        m = self.models[key]
        bad_json = transient = 0
        # AI Studio counts 503 "high demand" failures against RPD, so a 20-per-day
        # model must not spend its budget retrying an overload.
        max_transient = 1 if m["rpd"] <= SCARCE_RPD else TRANSIENT_TRIES
        while self.remaining(key, role) > 0 and bad_json < 3 and transient < max_transient:
            self._pace(key, prompt)
            self.state["used"][key] = self.used(key) + 1
            self.save()
            try:
                if search:
                    # JSON mode cannot be combined with tools; parse the text instead.
                    cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
                elif m["json_mode"]:
                    cfg = types.GenerateContentConfig(response_mime_type="application/json")
                else:
                    cfg = None
                resp = self.client.models.generate_content(model=m["api_id"], contents=prompt, config=cfg)
                self._record_tokens(key, resp, prompt)
                return _parse_json(resp.text), key, _sources(resp)
            except (json.JSONDecodeError, TypeError, ValueError):
                bad_json += 1
                print(f"  [pool] {key} returned invalid JSON, retrying")
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if _is_daily_quota(msg):
                        self._park(key, "daily quota hit")
                        return None
                    print(f"  [pool] {key} per-minute limit, backing off 60s")
                    time.sleep(60)
                elif _is_transient(msg):
                    transient += 1
                    if transient < max_transient:
                        time.sleep(15 * transient)
                elif "404" in msg or "NOT_FOUND" in msg or "not supported" in msg.lower():
                    self._park(key, f"unavailable as {m['api_id']}: {msg[:160]}")
                    return None
                else:
                    print(f"  [pool] {key} error: {msg[:200]}")
                    time.sleep(5)
                    transient += 1
        if transient >= max_transient:
            print(f"  [pool] {key} overloaded, trying the next model")
        return None
