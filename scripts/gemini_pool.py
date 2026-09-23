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


class QuotaExhausted(Exception):
    """No model serving the requested role has budget left today."""


def _is_daily_quota(msg):
    m = msg.lower()
    return "perday" in m or "per_day" in m or "per day" in m


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _parse_json(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
        end = max(text.rfind("}"), text.rfind("]"))
        if not starts or end <= min(starts):
            raise
        return json.loads(text[min(starts):end + 1])


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
        for m in self.models.values():
            want = {_norm(m["display"]), _norm(m["id"])}
            hits = [a.name.split("/")[-1] for a in available
                    if _norm(getattr(a, "display_name", "") or "") in want
                    or _norm(a.name.split("/")[-1]) in want]
            # Prefer stable ids over previews and dated snapshots.
            hits.sort(key=lambda n: ("preview" in n or "exp" in n, len(n)))
            m["api_id"] = hits[0] if hits else m["id"]
        self.state["resolved"] = {k: m["api_id"] for k, m in self.models.items()}

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
        wait = self.last_call.get(key, 0) + 60.0 / m["rpm"] + 0.5 - time.time()
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
        """
        for key in self.routing.get(role, []):
            m = self.models[key]
            attempts = 0
            while self.remaining(key, role) > 0 and attempts < 3:
                attempts += 1
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
                    print(f"  [pool] {key} returned invalid JSON, retrying")
                    continue
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        if _is_daily_quota(msg):
                            self._park(key, "daily quota hit")
                            break
                        print(f"  [pool] {key} per-minute limit, backing off 60s")
                        time.sleep(60)
                        continue
                    if "404" in msg or "NOT_FOUND" in msg or "not supported" in msg.lower():
                        self._park(key, f"unavailable as {m['api_id']}")
                        break
                    print(f"  [pool] {key} error: {msg[:200]}")
                    time.sleep(5)
        raise QuotaExhausted(f"No budget left for role '{role}'. {self.summary()}")
