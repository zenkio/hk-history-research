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
OPENROUTER_KEY_NAMES = ("OPENROUTER_API_KEY", "OPEN_ROUTER_KEY_RESEARCHER")
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# The owner's AI gateway (zenkio/ai-gateway): it picks a free model for a task, from its own keys.
GATEWAY_URL = "https://aigateway.zenkio.uk"
GATEWAY_TOKEN_NAME = "AI_GATEWAY_TOKEN"
# Cloudflare in front of the gateway refuses Python's default user agent (error 1010).
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
# Free-list entries that are not general text models.
OPENROUTER_SKIP = re.compile(r"(vl|vision|coder|math|embed|guard|audio|image|ocr)", re.I)
EXPECTED_OUTPUT_TOKENS = 1500
# A YouTube video at low media resolution costs roughly 100 tokens per second.
VIDEO_TOKEN_ESTIMATE = 150_000
IMAGE_TOKEN_ESTIMATE = 1_500
TRANSIENT_TRIES = 4      # per request on large-quota models, for 503/500/timeouts
SCARCE_RPD = 50          # models this small move on after one overload error: Google still bills it
IDLE_CYCLES = 3
COOLDOWN_SECONDS = 600   # skip a model this long after it exhausts its overload retries
# OpenRouter's free models are rate-limited upstream, often for many minutes: waiting 60 s and
# retrying cost run 15 ~38 minutes of the research worker. Rest the model and let the next one
# in the routing (Gemma) take the call instead.
RATE_LIMIT_COOLDOWN = 300
# The gateway says when its models are free again (nextFreeAt, Retry-After, details.busy): a call
# waits for that up to this long, and a longer wait rests the entry until then.
GATEWAY_MAX_WAIT = 120
# OpenRouter's daily free-model limit: 50 calls, or 1,000 once the account has bought at least
# 10 credits (lifetime). models.json assumed 50, leaving 950 calls a day unused.
OPENROUTER_FREE_TIER_RPD = 50
OPENROUTER_CREDITS_RPD = 1000
# Suffix tokens an API id may add to a configured name and still be the same model.
ALLOWED_EXTRA = re.compile(r"^(preview|latest|exp|it|a\d+b|\d+)$")


class GatewayBusy(Exception):
    """The gateway answered 429 and said until when (Retry-After) and which models are busy."""
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


def _parse_time(text):
    """ISO time (the gateway's freeAt) -> epoch seconds, None when absent or unreadable."""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _positive(value):
    """A number the gateway really sent (JSON number or header text); null, junk and zero mean
    unknown, never a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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


def _is_auth_error(msg):
    return bool(re.match(r"(401|403)\b", msg)) or any(
        k in msg for k in ("UNAUTHENTICATED", "PERMISSION_DENIED", "API_KEY_INVALID", "Missing Authentication"))


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
        self.last_call = {}
        self.token_log = {}
        self.no_media = set()  # models found this run to reject image/video input
        self.unavailable = set()  # models not usable in this run only (missing key, no free match)
        self.google_off = None  # why Google (Gemini and Gemma) is not called in this run
        key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        self.client = genai.Client(api_key=key) if key else None
        self.cooldown = {}  # model -> time until which it is skipped after repeated overloads
        # Thread safety: seed_history runs several workers on one pool. `lock` guards the
        # quota state; one lock per model serialises pacing so RPM/TPM hold across threads.
        self.lock = threading.RLock()
        self.model_locks = {}
        self.state = self._load_state()
        if self.client is None:
            self._google_off("no GEMINI_API_KEY")
        else:
            self._resolve_ids()
        self._resolve_openrouter()
        self.gateway_token = (os.environ.get(GATEWAY_TOKEN_NAME) or "").strip()
        # What the gateway says about its own rate, per entry: min_interval_s, concurrency,
        # next_free_at (epoch), retry_until (epoch), busy {model: epoch}. models.json's rpm is only
        # the upper bound on the rate and the fallback while the gateway has said nothing.
        self.gateway_live = {}
        self.gateway_slots = {}
        self.gateway_seen = []  # (time, status, advertised min interval) per call, for the report
        if not self.gateway_token:
            self.unavailable |= {k for k, m in self.models.items() if m.get("provider") == "gateway"}
        else:
            self._read_gateway_capacity()

    def _read_gateway_capacity(self):
        """GET /v1/quota for each gateway entry's task: the real rate, read once at the start."""
        for key, m in self.models.items():
            if m.get("provider") != "gateway" or key in self.unavailable:
                continue
            needs = m.get("needs") or {}
            query = f"task={m.get('task', 'general')}" + (f"&accuracy={needs['accuracy']}" if needs.get("accuracy") else "")
            req = urllib.request.Request(f"{GATEWAY_URL}/v1/quota?{query}", headers={
                "Authorization": f"Bearer {self.gateway_token}", "User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    capacity = json.load(r).get("capacity") or {}
            except Exception as e:
                print(f"  [pool] {key}: gateway capacity unreadable ({type(e).__name__}); using the configured rate")
                capacity = {}
            self._note_gateway_pace(key, capacity.get("minIntervalMs"), capacity.get("concurrency"),
                                    capacity.get("nextFreeAt") if not capacity.get("freeNow") else None)
            live = self.gateway_live.get(key, {})
            self.gateway_slots[key] = threading.Semaphore(int(live.get("concurrency") or 1))
            print(f"  [pool] {key}: gateway says {capacity.get('perMinute')} a minute, min interval "
                  f"{capacity.get('minIntervalMs')} ms, concurrency {capacity.get('concurrency')}, "
                  f"free now {capacity.get('freeNow')}")

    def _note_gateway_pace(self, key, min_interval_ms, concurrency, next_free_at):
        """Keep what the gateway just said; a missing value keeps the earlier one, never becomes 0."""
        with self.lock:
            live = self.gateway_live.setdefault(key, {"busy": {}})
            interval = _positive(min_interval_ms)
            if interval is not None:
                live["min_interval_s"] = interval / 1000
            if _positive(concurrency) is not None:
                live["concurrency"] = int(_positive(concurrency))
            live["next_free_at"] = _parse_time(next_free_at) if next_free_at else None

    def gateway_wait(self, key):
        """Seconds until the gateway said this entry may be asked again, None if it said nothing."""
        until = self.gateway_live.get(key, {}).get("retry_until")
        return max(until - time.time(), 0) if until else None

    def gateway_summary(self):
        """One line for the log: what the gateway advertised against what happened."""
        if not self.gateway_seen:
            return ""
        intervals = [i for _, _, i in self.gateway_seen if i]
        stamps = [t for t, status, _ in self.gateway_seen if status == 200]
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        busy = sum(status == 429 for _, status, _ in self.gateway_seen)
        return (f"gateway: {len(self.gateway_seen)} calls, {busy} busy answers; advertised min interval "
                f"{min(intervals):.1f}-{max(intervals):.1f}s; " if intervals else
                f"gateway: {len(self.gateway_seen)} calls, {busy} busy answers; no pace advertised; ") + \
            (f"mean gap between answers {sum(gaps) / len(gaps):.1f}s" if gaps else "no gaps to measure")

    def _google_off(self, reason):
        """Stop calling Google (Gemini and Gemma) for the rest of the run. When Google rejected the key
        on 2026-09-30, every run still sent it a model list and a call per model: one refusal or a
        missing key now means no further Google calls at all."""
        if self.google_off:
            return
        self.google_off = reason
        self.unavailable |= {k for k, m in self.models.items() if m.get("provider", "google") == "google"}
        print(f"  [pool] Google models off for this run: {reason}")

    # ---- setup -------------------------------------------------------
    def _resolve_ids(self):
        """Map AI Studio display names to real API ids, since ids change between releases."""
        try:
            available = [m for m in self.client.models.list()
                         if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"])]
        except Exception as e:
            if _is_auth_error(str(e)):
                for m in self.models.values():
                    if m.get("provider", "google") == "google":
                        m.setdefault("api_id", m["id"])
                self._google_off(f"the key was rejected ({str(e)[:60]})")
                return
            print(f"  [pool] models.list failed ({str(e)[:80]}); using configured ids")
            available = []
        ids = [a.name.split("/")[-1] for a in available]
        for m in self.models.values():
            if m.get("provider") in ("openrouter", "gateway"):
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
        # Keys are tried in this order; one that OpenRouter rejects (401) is dropped for the run.
        # A pasted secret can carry a space or newline, so values are stripped.
        self.or_keys = [(name, os.environ[name].strip()) for name in OPENROUTER_KEY_NAMES
                        if (os.environ.get(name) or "").strip()]
        self.or_key_name, self.or_key = self.or_keys[0] if self.or_keys else (None, "")
        if self.or_keys:
            print(f"  [pool] OpenRouter keys available: {', '.join(n for n, _ in self.or_keys)}; using {self.or_key_name}")
        if self.or_key:
            self._read_openrouter_limit(entries)
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
            # "avoid" keeps a family out (the v2.1 comparison model must not be Nemotron);
            # "*" as the last pick takes the largest free model left when no preference matches.
            avoid = [a.lower() for a in m.get("avoid", [])]
            usable = [d["id"] for d in free
                      if d["id"] not in taken and not any(a in d["id"].lower() for a in avoid)]
            hit = next((i for pref in m.get("pick", []) for i in self._wildcard_order(usable, pref)
                        if pref == "*" or pref.lower() in i.lower()), None)
            m["api_id"] = hit
            if "*" in m.get("pick", []):
                # Run 38183882474 fell through to unusable previews; the log shows what was on offer.
                print(f"  [pool] {m['display']} picked {hit}; free now: {', '.join(d['id'] for d in free[:40])}")
            if hit:
                taken.add(hit)
            else:
                # Not parked for the day: a later step may have the key, and the free list changes.
                self.unavailable.add(m["display"])
                print(f"  [pool] {m['display']} skipped this run: "
                      + ("no OpenRouter key (" + " / ".join(OPENROUTER_KEY_NAMES) + ")" if not self.or_key
                         else f"no free model matching {m.get('pick')} (free now: {', '.join(d['id'] for d in free[:15]) or 'none'})"))
            self.state.setdefault("resolved", {})[m["display"]] = hit
        self.state["openrouter_free"] = [d["id"] for d in free]
        self.or_free, self.or_refused = [d["id"] for d in free], set()

    @staticmethod
    def _wildcard_order(ids, pref):
        """For "*", previews come last: they answered 400s and 403s in run 38183882474."""
        if pref != "*":
            return ids
        return sorted(ids, key=lambda i: "preview" in i.lower())

    def _repick_openrouter(self, m, msg):
        """For an entry ending its picks with "*": move to the next free model after a refusal."""
        if "*" not in m.get("pick", []):
            return False
        self.or_refused.add(m["api_id"])
        taken = {e.get("api_id") for e in self.models.values() if e.get("provider") == "openrouter"}
        avoid = [a.lower() for a in m.get("avoid", [])]
        nxt = next((i for i in self._wildcard_order(getattr(self, "or_free", []), "*") if i not in taken and i not in self.or_refused
                    and not any(a in i.lower() for a in avoid)), None)
        if not nxt:
            return False
        print(f"  [pool] {m['display']}: {m['api_id']} refused ({msg[:80]}); trying {nxt}")
        m["api_id"] = nxt
        return True

    def _read_openrouter_limit(self, entries):
        """Ask OpenRouter which daily limit this account has; keep the smaller one if it can't say."""
        cfg = self.config.setdefault("providers", {}).setdefault("openrouter", {"rpd": OPENROUTER_FREE_TIER_RPD})
        try:
            req = urllib.request.Request(f"{OPENROUTER_URL}/key", headers={"Authorization": f"Bearer {self.or_key}"})
            with urllib.request.urlopen(req, timeout=20) as r:
                free_tier = json.load(r).get("data", {}).get("is_free_tier")
        except Exception as e:
            print(f"  [pool] OpenRouter limit check failed ({str(e)[:60]}); assuming {cfg['rpd']} calls a day")
            return
        if free_tier is None:
            return
        limit = OPENROUTER_FREE_TIER_RPD if free_tier else OPENROUTER_CREDITS_RPD
        cfg["rpd"] = limit
        for m in entries:
            m["rpd"] = limit
        print(f"  [pool] OpenRouter daily limit: {limit} calls ({'free tier' if free_tier else 'credits bought'})")

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
        interval = 60.0 / m["rpm"] * 1.15
        live_gap = self.gateway_live.get(key, {}).get("min_interval_s") if m.get("provider") == "gateway" else None
        if live_gap:
            # The gateway's measured gap replaces the 15% margin, and never beats models.json's rate.
            interval = max(live_gap, 60.0 / m["rpm"])
        wait = self.last_call.get(key, 0) + interval - time.time()
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

    def _next_openrouter_key(self):
        """Drop the OpenRouter key that was just rejected and switch to the next one, if any."""
        with self.lock:
            rejected = self.or_key_name
            self.or_keys = [(n, v) for n, v in self.or_keys if n != rejected]
            if not self.or_keys:
                print(f"  [pool] OpenRouter rejected {rejected}; no other key left")
                return False
            self.or_key_name, self.or_key = self.or_keys[0]
            print(f"  [pool] OpenRouter rejected {rejected}; switching to {self.or_key_name}")
            return True

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

    def _call_gateway(self, m, prompt):
        """One llm.generate call through the AI gateway. The entry names a task and needs, never a
        model unless it pins "models"; the models that answered are kept in m["api_id"]. The
        gateway's own pace (headers, busy list, Retry-After) steers the next call."""
        key = next(k for k, v in self.models.items() if v is m)
        live = self.gateway_live.setdefault(key, {"busy": {}})
        now = time.time()
        free_at = live.get("next_free_at")
        if free_at and free_at > now:
            if free_at - now > GATEWAY_MAX_WAIT:
                live["retry_until"] = free_at
                raise GatewayBusy(f"429 gateway quota_exhausted: nothing free until {int(free_at - now)}s from now",
                                  free_at - now)
            print(f"  [pool] {key}: gateway has nothing free for {int(free_at - now)}s; waiting")
            time.sleep(free_at - now)
        options = {"task": m.get("task", "general"), "needs": m.get("needs", {})}
        if m.get("models"):
            options["models"] = m["models"]
        busy = [name for name, until in live["busy"].items() if until > time.time()]
        if busy:
            options["exclude"] = busy  # rest exactly the models the gateway named, use the others
        body = json.dumps({"capability": "llm.generate", "input": {"prompt": prompt},
                           "options": options}).encode()
        req = urllib.request.Request(f"{GATEWAY_URL}/v1/run", data=body, headers={
            "Authorization": f"Bearer {self.gateway_token}", "Content-Type": "application/json",
            "User-Agent": USER_AGENT})
        try:
            with self.gateway_slots.setdefault(key, threading.Semaphore(1)):
                with urllib.request.urlopen(req, timeout=300) as r:
                    headers = getattr(r, "headers", None) or {}
                    data = json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                err = json.loads(raw).get("error") or {}
            except ValueError:
                err = {}
            code = err.get("code", "")
            headers = e.headers or {}
            self._note_gateway_pace(key, headers.get("X-Gateway-Min-Interval-Ms"), None,
                                    headers.get("X-Gateway-Next-Free-At"))
            self.gateway_seen.append((time.time(), e.code, live.get("min_interval_s")))
            # The gateway's codes, mapped onto the messages _try_model already handles.
            if code in ("quota_exhausted", "all_models_failed", "rate_limited"):
                retry_after = _positive(headers.get("Retry-After"))
                for entry in (err.get("details") or {}).get("busy") or []:
                    until = _parse_time(entry.get("freeAt"))
                    if entry.get("model") and until:
                        live["busy"][entry["model"]] = until
                if retry_after:
                    live["retry_until"] = time.time() + retry_after
                raise GatewayBusy(f"429 gateway {code}: {err.get('message', '')[:200]}", retry_after)
            raise Exception(f"{e.code} gateway {code}: {(err.get('message') or raw)[:200]}")
        # A free answer carries the live pace; nextFreeAt appears only when nothing is free.
        capacity = (data.get("quota") or {}).get("capacity") or {}
        self._note_gateway_pace(
            key, headers.get("X-Gateway-Min-Interval-Ms") or capacity.get("minIntervalMs"), capacity.get("concurrency"),
            headers.get("X-Gateway-Next-Free-At") or (capacity.get("nextFreeAt") if not capacity.get("freeNow") else None))
        live.pop("retry_until", None)
        self.gateway_seen.append((time.time(), 200, live.get("min_interval_s")))
        usage = data.get("usage") or {}
        if usage.get("billing", "free") != "free" or usage.get("costUsd"):
            # "400" makes _try_model raise RequestRejected: no paid call is ever retried.
            raise Exception(f"400 gateway billed a paid model ({usage.get('modelId')}); free models only")
        served = usage.get("modelId") or usage.get("model") or ""
        with self.lock:
            seen = [x for x in (m.get("api_id") or "").split(", ") if x]
            if served and served not in seen:
                m["api_id"] = ", ".join(seen + [served])
        tokens = usage.get("tokens") or {}
        return (data.get("output") or {}).get("text") or "", [], \
            (tokens.get("input") or 0) + (tokens.get("output") or 0) or None

    def _try_model(self, key, role, prompt, search, parse, media=None):
        m = self.models[key]
        if self.cooldown.get(key, 0) > time.time():
            return None  # resting after rate limits or overloads earlier in this call chain
        bad_json = transient = rate_limited = 0
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
                elif self._provider(key) == "gateway":
                    text, sources, tokens = self._call_gateway(m, prompt)
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
                if isinstance(e, GatewayBusy) and not _is_daily_quota(msg):
                    # Not before the time the gateway named (Retry-After), else the usual rest.
                    rest = e.retry_after or RATE_LIMIT_COOLDOWN
                    self.cooldown[key] = time.time() + rest
                    print(f"  [pool] {key} busy at the gateway; resting it {int(rest)}s as it said")
                    return None
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if _is_daily_quota(msg):
                        # Park this model only. The same words come from the account's allowance and
                        # from one upstream model's own limit; stopping every OpenRouter model on one
                        # model's 429 left Medium with a single call in run 39152869221. If the
                        # account really is spent, each other model gets the same answer and parks
                        # in turn. Our own count (`_count`) still ends the provider at its daily cap.
                        self._park(key, "daily quota hit")
                        print(f"  [pool] {key} 429 said: {' '.join(msg.split())[:200]}")
                        return None
                    rate_limited += 1
                    if self._provider(key) == "openrouter" or rate_limited >= 2:
                        self.cooldown[key] = time.time() + RATE_LIMIT_COOLDOWN
                        print(f"  [pool] {key} per-minute limit; resting it {RATE_LIMIT_COOLDOWN // 60} min, "
                              "the next model takes over")
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
                elif self._provider(key) == "openrouter" and msg.startswith("403"):
                    # OpenRouter answers a bad key with 401; a 403 refuses this model only (e.g.
                    # "only available on ..."). Run 38182972425 dropped the account's only key on one.
                    if self._repick_openrouter(m, msg):
                        continue
                    print(f"  [pool] {key} refused {m['api_id']} ({msg[:120]}); skipped for this run")
                    self.unavailable.add(key)
                    return None
                elif _is_auth_error(msg):
                    if self._provider(key) == "openrouter" and self._next_openrouter_key():
                        continue  # retry this call with the next key
                    if self._provider(key) == "google":
                        self._google_off(f"{key} rejected the key ({msg[:60]})")
                        return None
                    # A bad or missing key will not fix itself mid-run: skip the model, keep the quota.
                    print(f"  [pool] {key} rejected the API key ({msg[:80]}); skipped for this run. "
                          "Check the repository secret for spaces or line breaks.")
                    self.unavailable.add(key)
                    return None
                elif "400" in msg or "INVALID_ARGUMENT" in msg:
                    # A free model whose provider fails every request (run 38183882474) is
                    # replaced when the entry may pick any free model; otherwise the request is bad.
                    if (self._provider(key) == "openrouter" and "Provider returned error" in msg
                            and self._repick_openrouter(m, msg)):
                        continue
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
