#!/usr/bin/env python3
"""Quota-aware Gemini model pool shared by the pipeline scripts.

Each free-tier model has its own requests-per-day (RPD) bucket, so for every
task ("role") the pool tries the models listed in models.json routing, in
order, and moves on only when a model is spent. It paces both requests per
minute and tokens per minute (the real limit on Gemma), persists usage in
quota_state.json so separate cron runs in one quota day share a budget, and
parks a model for the day on a real daily-quota 429 or when it does not exist.

Models with "provider": "openrouter" are called through OpenRouter's
OpenAI-compatible API (key in OPENROUTER_API_KEY). Their ids are picked at
startup from OpenRouter's current ":free" list, since free models come and go,
and they share one provider-wide daily limit.
"""
import os
import re
import json
import time
import threading
import urllib.request
import urllib.error
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
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Free-list entries that are not general text models.
OPENROUTER_SKIP = re.compile(r"(vl|vision|coder|math|embed|guard|audio|image|ocr)", re.I)
EXPECTED_OUTPUT_TOKENS = 1500
# A YouTube video at low media resolution costs roughly 100 tokens per second.
VIDEO_TOKEN_ESTIMATE = 150_000
IMAGE_TOKEN_ESTIMATE = 1_500
TRANSIENT_TRIES = 4      # per request on large-quota models, for 503/500/timeouts
SCARCE_RPD = 50          # models this small move on after one overload error: Google still bills it
IDLE_CYCLES = 3
COOLDOWN_SECONDS = 600   # skip a model this long after it exhausts its overload retries          # full passes over the routing list before giving up on a transient outage
# Suffix tokens an API id may add to a configured name and still be the same model.
ALLOWED_EXTRA = re.compile(r"^(preview|latest|exp|it|a\d+b|\d+)$")


class QuotaExhausted(Exception):
    """No model serving the requested role has budget left today."""


class RequestRejected(Exception):
    """The request itself is invalid (e.g. a private video); retrying or switching models won't help."""


def _is_daily_quota(msg):
    m = msg.lower()
    return "perday" in m or "per_day" in m or "per day" in m or "per-day" in m


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
        self.no_media = set()  # models found this run to reject image/video input
        self.unavailable = set()  # models not usable in this run only (missing key, no free match)
        self.cooldown = {}  # model -> time until which it is skipped after repeated overloads
        # Thread safety: seed_history runs several workers on one pool. `lock` guards the
        # quota state; one lock per model serialises pacing so RPM/TPM hold across threads.
        self.lock = threading.RLock()
        self.model_locks = {}
        self.state = self._load_state()
        self._resolve_ids()
        self._resolve_openrouter()

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
            if m.get("provider") == "openrouter":
                continue
            if m["id"] in ids or not ids:
                m["api_id"] = m["id"]
                continue
            hits = [a.name.split("/")[-1] for a in available
                    if _same_model(m["display"], getattr(a, "display_name", "") or "")
                    or _same_model(m["id"], a.name)]
            # Prefer stable ids over previews and dated snapshots.
            hits.sort(key=lambda n: ("preview" in n or "exp" in n, len(n)))
            m["api_id"] = hits[0] if hits else m["id"]
        self.state["resolved"] = {k: m.get("api_id") for k, m in self.models.items()}
        # Kept in the committed state file so wrong ids can be fixed without a debug run.
        self.state["available"] = sorted(i for i in ids if i.startswith(("gemini", "gemma")))

    def _resolve_openrouter(self):
        """Pick a current ':free' model for each OpenRouter entry from its 'pick' preferences."""
        entries = [m for m in self.models.values() if m.get("provider") == "openrouter"]
        if not entries:
            return
        self.or_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()  # a pasted secret can carry a space or newline
        free = []
        if self.or_key:
            try:
                with urllib.request.urlopen(f"{OPENROUTER_URL}/models", timeout=30) as r:
                    data = json.load(r).get("data", [])
                free = [d for d in data if d["id"].endswith(":free") and not OPENROUTER_SKIP.search(d["id"])]
                free.sort(key=lambda d: -(d.get("context_length") or 0))
            except Exception as e:
                print(f"  [pool] OpenRouter model list failed: {str(e)[:80]}")
        taken = set()
        for m in entries:
            hit = next((d["id"] for pref in m.get("pick", []) for d in free
                        if pref.lower() in d["id"].lower() and d["id"] not in taken), None)
            m["api_id"] = hit
            if hit:
                taken.add(hit)
            else:
                # Not parked for the day: a later step may have the key, and the free list changes.
                self.unavailable.add(m["display"])
                print(f"  [pool] {m['display']} skipped this run: "
                      + ("no OPENROUTER_API_KEY" if not self.or_key else f"no free model matching {m.get('pick')}"))
            self.state.setdefault("resolved", {})[m["display"]] = hit
        self.state["openrouter_free"] = [d["id"] for d in free]

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
        with self.lock:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp, STATE_FILE)

    # ---- budget ------------------------------------------------------
    def used(self, key):
        return self.state["used"].get(key, 0)

    def _provider(self, key):
        return self.models[key].get("provider", "google")

    def _provider_used(self, provider):
        """Provider-wide daily count (OpenRouter's free limit is per account, reset at UTC midnight)."""
        cfg = self.config.get("providers", {}).get(provider)
        if not cfg:
            return None, None
        day = datetime.now(ZoneInfo(cfg.get("reset_timezone", "UTC"))).strftime("%Y-%m-%d")
        rec = self.state.setdefault("provider_used", {}).get(provider)
        if not rec or rec.get("day") != day:
            rec = {"day": day, "count": 0}
            self.state["provider_used"][provider] = rec
        return rec, cfg["rpd"]

    def _count(self, key):
        with self.lock:
            self.state["used"][key] = self.used(key) + 1
            rec, _ = self._provider_used(self._provider(key))
            if rec is not None:
                rec["count"] += 1
            self.save()

    def remaining(self, key, role):
        with self.lock:
            return self._remaining(key, role)

    def _remaining(self, key, role):
        if key in self.state["parked"] or key in self.unavailable:
            return 0
        left = self.models[key]["rpd"] - self.used(key)
        rec, cap = self._provider_used(self._provider(key))
        if rec is not None:
            left = min(left, cap - rec["count"])
        # Hold some budget on RSS-classifying models so ingestion later in the
        # day is never starved by bulk drafting.
        if role != "classify" and key in self.routing.get("classify", []):
            left -= self.config.get("reserve_for_ingestion", 0)
        return max(left, 0)

    def total_remaining(self, role):
        return sum(self.remaining(k, role) for k in self.routing.get(role, []))

    def summary(self):
        with self.lock:
            return self._summary()

    def _summary(self):
        parts = []
        for key, m in self.models.items():
            if self.used(key) or key in self.state["parked"]:
                p = f"{key} {self.used(key)}/{m['rpd']}"
                if key in self.state["parked"]:
                    p += f" (parked: {self.state['parked'][key]})"
                parts.append(p)
        return ", ".join(parts) or "nothing used yet"

    def _park(self, key, reason):
        with self.lock:
            self.state["parked"][key] = reason
            self.save()
        print(f"  [pool] {key} parked for today: {reason}")

    def _pace(self, key, prompt, extra=0):
        with self.lock:
            model_lock = self.model_locks.setdefault(key, threading.Lock())
        with model_lock:
            self._pace_locked(key, prompt, extra)

    def _pace_locked(self, key, prompt, extra):
        m = self.models[key]
        wait = self.last_call.get(key, 0) + 60.0 / m["rpm"] * 1.15 - time.time()
        if wait > 0:
            time.sleep(wait)
        # Tokens per minute: sliding 60s window of real usage.
        with self.lock:
            log = self.token_log.setdefault(key, deque())
        need = min(len(prompt) // 2 + EXPECTED_OUTPUT_TOKENS + extra, m["tpm"])
        while True:
            with self.lock:
                now = time.time()
                while log and now - log[0][0] > 60:
                    log.popleft()
                if not log or sum(t for _, t in log) + need <= m["tpm"]:
                    break
                oldest = log[0][0]
            time.sleep(max(0.5, 60 - (now - oldest)))
        self.last_call[key] = time.time()

    # ---- calls -------------------------------------------------------
    def generate_json(self, role, prompt, search=False, only=None, media=None):
        """Return (parsed_json, model_display_name, sources) from the best model with budget left.

        search=True enables Google Search grounding; sources then lists the web pages used.
        only restricts the role's routing to these model names.
        media is a list the model sees along with the prompt: public URLs (e.g. YouTube) and/or
        (bytes, mime_type) images; only Google models accept it.
        Transient server errors (503 "high demand" etc.) are retried with backoff; only when
        every model is out of budget, or still failing after IDLE_CYCLES passes, does this
        raise QuotaExhausted.
        """
        return self._generate(role, prompt, _parse_json, search, only, media)

    def generate_text(self, role, prompt, parse, only=None):
        """Like generate_json, but `parse(text)` turns the raw reply into a result (raise ValueError to retry)."""
        return self._generate(role, prompt, parse, False, only, None)

    def _generate(self, role, prompt, parse, search, only, media):
        keys = [k for k in self.routing.get(role, [])
                if (only is None or k in only) and self.cooldown.get(k, 0) < time.time()
                and not (media and (self._provider(k) != "google" or k in self.no_media))]
        for cycle in range(IDLE_CYCLES):
            for key in keys:
                result = self._try_model(key, role, prompt, search, parse, media)
                if result is not None:
                    return result
            if sum(self.remaining(k, role) for k in keys) == 0:
                break
            wait = 60 * (cycle + 1)
            print(f"  [pool] all '{role}' models busy, waiting {wait}s before another pass")
            time.sleep(wait)
        raise QuotaExhausted(f"No budget left for role '{role}'. {self.summary()}")

    def _call_google(self, m, prompt, search, want_json, media=None):
        if media:
            has_video = any(isinstance(x, str) for x in media)
            cfg = types.GenerateContentConfig(
                response_mime_type="application/json" if want_json and m["json_mode"] else None,
                # Low resolution keeps long videos within TPM; photos need detail (signs, dates).
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW if has_video else None)
            contents = [types.Part(file_data=types.FileData(file_uri=x)) if isinstance(x, str)
                        else types.Part.from_bytes(data=x[0], mime_type=x[1]) for x in media]
            contents.append(types.Part(text=prompt))
            resp = self.client.models.generate_content(model=m["api_id"], contents=contents, config=cfg)
            tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", None)
            return resp.text, [], tokens
        if search:
            # JSON mode cannot be combined with tools; parse the text instead.
            cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        elif m["json_mode"] and want_json:
            cfg = types.GenerateContentConfig(response_mime_type="application/json")
        else:
            cfg = None
        resp = self.client.models.generate_content(model=m["api_id"], contents=prompt, config=cfg)
        tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", None)
        return resp.text, _sources(resp), tokens

    def _call_openrouter(self, m, prompt):
        body = json.dumps({"model": m["api_id"], "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(f"{OPENROUTER_URL}/chat/completions", data=body, headers={
            "Authorization": f"Bearer {self.or_key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/zenkio/hk-history-research", "X-Title": "HK History Research"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise Exception(f"{e.code} {e.read().decode(errors='replace')[:300]}")
        if "error" in data:
            raise Exception(f"{data['error'].get('code', '')} {data['error'].get('message', '')}")
        text = data["choices"][0]["message"].get("content") or ""
        return text, [], (data.get("usage") or {}).get("total_tokens")

    def _try_model(self, key, role, prompt, search, parse, media=None):
        m = self.models[key]
        bad_json = transient = 0
        # AI Studio counts 503 "high demand" failures against RPD, so a 20-per-day
        # model must not spend its budget retrying an overload.
        max_transient = 1 if m["rpd"] <= SCARCE_RPD else TRANSIENT_TRIES
        while self.remaining(key, role) > 0 and bad_json < 3 and transient < max_transient:
            self._pace(key, prompt, extra=sum(VIDEO_TOKEN_ESTIMATE if isinstance(x, str) else IMAGE_TOKEN_ESTIMATE
                                              for x in media or []))
            self._count(key)
            try:
                if self._provider(key) == "openrouter":
                    text, sources, tokens = self._call_openrouter(m, prompt)
                else:
                    text, sources, tokens = self._call_google(m, prompt, search, parse is _parse_json, media)
                with self.lock:
                    self.token_log.setdefault(key, deque()).append(
                    (time.time(), tokens or len(prompt) // 2 + EXPECTED_OUTPUT_TOKENS))
                return parse(text), key, sources
            except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
                bad_json += 1
                print(f"  [pool] {key} returned an unusable reply, retrying")
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if _is_daily_quota(msg):
                        self._park(key, "daily quota hit")
                        rec, cap = self._provider_used(self._provider(key))
                        if rec is not None:
                            # OpenRouter's free limit is account-wide: stop every model on it.
                            rec["count"] = cap
                            self.save()
                        return None
                    print(f"  [pool] {key} per-minute limit, backing off 60s")
                    time.sleep(60)
                elif _is_transient(msg) or "502" in msg or "timed out" in msg.lower():
                    transient += 1
                    if transient < max_transient:
                        time.sleep(15 * transient)
                elif media and re.search(r"modalit|image input|does not support (image|video)", msg, re.I):
                    # This model can't see images/video; another in the routing may.
                    print(f"  [pool] {key} cannot take this media; skipping it for media this run")
                    self.no_media.add(key)
                    return None
                elif re.match(r"(401|403)\b", msg) or "Missing Authentication" in msg or "API_KEY_INVALID" in msg:
                    # A bad or missing key will not fix itself mid-run: skip the model, keep the quota.
                    print(f"  [pool] {key} rejected the API key ({msg[:80]}); skipped for this run. "
                          "Check the repository secret for spaces or line breaks.")
                    self.unavailable.add(key)
                    return None
                elif "400" in msg or "INVALID_ARGUMENT" in msg:
                    raise RequestRejected(msg[:300])
                elif "404" in msg or "NOT_FOUND" in msg or "not supported" in msg.lower():
                    self._park(key, f"unavailable as {m['api_id']}: {msg[:160]}")
                    return None
                else:
                    print(f"  [pool] {key} error: {msg[:200]}")
                    time.sleep(5)
                    transient += 1
        if transient >= max_transient:
            # A model that keeps answering "overloaded" costs minutes per call in backoff;
            # rest it so the next model in the routing does the work meanwhile.
            self.cooldown[key] = time.time() + COOLDOWN_SECONDS
            print(f"  [pool] {key} overloaded, trying the next model")
        return None
