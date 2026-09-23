#!/usr/bin/env python3
"""Quota-aware Gemini model pool shared by the pipeline scripts.

Each free-tier model has its own requests-per-day (RPD) bucket, so the pool
drains models in the preference order listed in models.json for a given role
and moves on only when a model is spent. Usage is persisted in
quota_state.json so separate cron runs within the same quota day share one
budget. Limits in models.json are soft caps; a real daily-quota 429 from the
API parks the model until the next reset regardless of the configured number.
"""
import os
import re
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPTS_DIR, "models.json")
STATE_FILE = os.path.join(SCRIPTS_DIR, "quota_state.json")


class QuotaExhausted(Exception):
    """No model serving the requested role has budget left today."""


def _is_daily_quota(msg):
    m = msg.lower()
    return "perday" in m or "per_day" in m or "per day" in m or "requestsperday" in m


def _parse_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


class ModelPool:
    def __init__(self):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            self.config = json.load(f)
        self.models = self.config["models"]
        self.tz = ZoneInfo(self.config.get("quota_reset_timezone", "America/Los_Angeles"))
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.last_call = {}
        self.state = self._load_state()

    # ---- persistence -------------------------------------------------
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
    def used(self, name):
        return self.state["used"].get(name, 0)

    def remaining(self, model, role):
        if model["name"] in self.state["parked"]:
            return 0
        left = model["rpd"] - self.used(model["name"])
        # Keep some classify-capable budget back so RSS ingestion later in the
        # day is never starved by bulk drafting.
        if role != "classify" and "classify" in model["roles"]:
            left -= self.config.get("reserve_for_ingestion", 0)
        return max(left, 0)

    def total_remaining(self, role):
        return sum(self.remaining(m, role) for m in self.models if role in m["roles"])

    def summary(self):
        return ", ".join(
            f"{m['name']} {self.used(m['name'])}/{m['rpd']}"
            + (f" (parked: {self.state['parked'][m['name']]})" if m["name"] in self.state["parked"] else "")
            for m in self.models
        )

    def _park(self, name, reason):
        self.state["parked"][name] = reason
        self.save()
        print(f"  [pool] {name} parked for today: {reason}")

    def _pace(self, model):
        gap = 60.0 / model["rpm"] + 0.5
        wait = self.last_call.get(model["name"], 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last_call[model["name"]] = time.time()

    # ---- calls -------------------------------------------------------
    def generate_json(self, role, prompt):
        """Return (parsed_json, model_name) from the best model with budget left."""
        for model in self.models:
            if role not in model["roles"]:
                continue
            attempts = 0
            while self.remaining(model, role) > 0 and attempts < 3:
                attempts += 1
                self._pace(model)
                self.state["used"][model["name"]] = self.used(model["name"]) + 1
                self.save()
                try:
                    cfg = types.GenerateContentConfig(response_mime_type="application/json") if model["json_mode"] else None
                    resp = self.client.models.generate_content(model=model["name"], contents=prompt, config=cfg)
                    return _parse_json(resp.text), model["name"]
                except json.JSONDecodeError:
                    print(f"  [pool] {model['name']} returned invalid JSON, retrying")
                    continue
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        if _is_daily_quota(msg):
                            self._park(model["name"], "daily quota hit")
                            break
                        print(f"  [pool] {model['name']} per-minute limit, backing off 60s")
                        time.sleep(60)
                        continue
                    if "404" in msg or "NOT_FOUND" in msg or "not supported" in msg.lower():
                        self._park(model["name"], "model unavailable")
                        break
                    print(f"  [pool] {model['name']} error: {msg[:200]}")
                    time.sleep(5)
        raise QuotaExhausted(f"No budget left for role '{role}'. {self.summary()}")
