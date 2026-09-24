#!/usr/bin/env python3
"""Draft a complete Hong Kong history skeleton from model knowledge.

RSS feeds only yield a handful of articles a day, which leaves most of the
free Gemini quota unused. This script spends the leftover quota writing a
chronological backbone, from prehistory to the present, that sourced material
can later confirm, correct, or replace. Every page it writes is marked as an
unverified AI draft.

Work is resumable and tracked in scripts/seed_plan.json:
  1. outline  - list the key events of each era    (role "outline", 16 calls)
  2. overview - write an overview page per era     (role "outline", 16 calls)
  3. draft    - write one page per event           (role "draft", ~400 calls)
  4. entity   - write a page per person and place mentioned by the events,
                most-mentioned first               (role "draft", ~1000+ calls)
  5. deepen   - ask each era for events it still misses, MAX_ROUNDS times
                (role "outline"), which feeds steps 3 and 4 again
Separately, every run first attaches archive/scholarly evidence to a slice of
drafted pages (evidence.py), spends the "verify" budget fact-checking drafted
event pages against Wikipedia (wikipedia.py), which adds reference links, then
the OpenRouter free budget on Traditional Chinese versions (translate.py),
then looks for Wikimedia Commons photos for a slice of event pages (photos.py).
Once the plan is complete, spare Gemma capacity continues the translations.

Usage: python3 scripts/seed_history.py [--max-calls N] [--minutes M] [--no-commit]
"""
import os
import re
import sys
import json
import time
import argparse
import threading
import traceback
import subprocess
from datetime import datetime

from gemini_pool import ModelPool, QuotaExhausted
from textutil import make_summary
from translate import translate_batch
from photos import photos_batch
from evidence import evidence_batch, write_status_page
from research_import import import_inbox
import state
import wikipedia
from state import PAGE_LOCK

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
PLAN_FILE = os.path.join(PROJECT_ROOT, "scripts", "seed_plan.json")
ENTITY_DIR = os.path.join(PROJECT_ROOT, "content", "02_Entities")
MAX_ROUNDS = 5
# Project focus (see BACKLOG.md): 1841 to today. Earlier eras stay as background:
# no more deepening, and they go last for verification and photos.
CORE_ERA_START = "05-opium-war"
# Readers can use the browser's built-in translation; AI translation is off so the
# OpenRouter and Gemma budgets go to research and verification instead.
TRANSLATE_WITH_AI = False
# Upper bounds per run; in practice the run's time budget stops the workers first.
PHOTO_EVENTS_PER_RUN = 60
VERIFY_PAGES_PER_RUN = 80  # Gemma: ~30 s a page, leaves time for drafting
EVIDENCE_PAGES_PER_RUN = 150
COMMIT_EVERY = 25  # push partial progress so a killed job loses little and the site fills in gradually

ERAS = [
    ("01-prehistory", "Prehistory and early settlement", "to 214 BCE"),
    ("02-qin-to-tang", "Imperial frontier: Qin to Tang", "214 BCE-960"),
    ("03-song-and-yuan", "Song and Yuan: salt, pearls and clans", "960-1368"),
    ("04-ming-and-qing", "Ming and Qing coast: pirates, the Great Clearance, forts", "1368-1800"),
    ("05-opium-war", "Canton trade and the First Opium War", "1800-1842"),
    ("06-early-colony", "The early colony", "1842-1860"),
    ("07-victorian-colony", "Kowloon and the Victorian colony", "1860-1898"),
    ("08-new-territories", "The New Territories lease and the early 20th century", "1898-1918"),
    ("09-interwar", "Interwar Hong Kong: strikes, boycotts and growth", "1919-1941"),
    ("10-japanese-occupation", "Battle of Hong Kong and the Japanese occupation", "1941-1945"),
    ("11-postwar-refugees", "Postwar recovery, refugees and industrialisation", "1945-1966"),
    ("12-riots-and-reform", "Riots and the MacLehose reforms", "1966-1982"),
    ("13-transition", "Sino-British negotiations and the transition", "1982-1997"),
    ("14-early-hksar", "The early HKSAR", "1997-2008"),
    ("15-contention", "Political contention and protest", "2008-2020"),
    ("16-national-security-era", "The National Security Law era", "2020-present"),
]
ERA_BY_SLUG = {slug: (name, span) for slug, name, span in ERAS}

STYLE = """Write as a neutral historian. Where interpretations differ (British colonial,
Qing/Beijing, local Hong Kong and New Territories communities, later scholarship),
present them side by side instead of choosing one. Give Chinese names in
traditional characters in parentheses after the English, e.g. Tuen Mun (屯門).
Only state facts you are confident are widely accepted; phrase uncertain points
as uncertain. Do not invent quotations, statistics, or citations."""

OUTLINE_PROMPT = """You are planning a chronological history of Hong Kong.

Era: {name} ({span})

List the {count} most important events, developments, people-centred episodes
or turning points of this era for understanding Hong Kong's history. Cover
politics, economy, society, culture and daily life, not only wars and treaties.
Order them chronologically.
{existing}
Respond with ONLY this JSON:
{{"events": [{{"title": "Short English title, max 10 words",
               "year": 1841,
               "date": "YYYY or YYYY-MM-DD if a specific date is well established, or a range like 1941/1945",
               "summary": "One sentence on what happened and why it matters"}}]}}
Use negative numbers for BCE years."""

OVERVIEW_PROMPT = """You are writing the overview page for one era of a Hong Kong history website.

Era: {name} ({span})
Events covered on separate pages: {titles}

{style}

Respond with ONLY this JSON:
{{"title": "Era title",
  "summary": "Two sentences on the era",
  "body": "600-900 words of markdown. Use ## headings (Overview, Key themes, How it shaped Hong Kong). Use **bold** for key names and dates.",
  "perspectives": [{{"viewpoint": "Whose view", "text": "2-3 sentences"}}],
  "tags": ["lowercase-hyphenated", "max-6"]}}"""

EVENT_PROMPT = """You are writing one page of a chronological Hong Kong history website.

Era: {name} ({span})
Event: {title}
Approximate date: {date}
Planning note: {summary}

{style}

Respond with ONLY this JSON:
{{"title": "{title}",
  "title_zh": "Traditional Chinese title",
  "summary": "One or two sentences",
  "body": "350-600 words of markdown with ## headings: Background, What happened, Significance. Use **bold** for key names and dates.",
  "perspectives": [{{"viewpoint": "Whose view", "text": "2-3 sentences"}}],
  "people": ["Name (中文名)"],
  "places": ["Place (中文名)"],
  "tags": ["lowercase-hyphenated-topic", "max-6"],
  "claims_to_verify": ["Specific factual claims on this page a researcher should check against primary sources"]}}"""

ENTITY_PROMPT = """You are writing a reference page for a Hong Kong history website.

{kind}: {name}
Mentioned in these pages: {context}

{style}
If you do not know reliable facts about this {kind_lower}, say so briefly rather than guessing.

Respond with ONLY this JSON:
{{"title": "English name",
  "title_zh": "Traditional Chinese name",
  "summary": "One sentence on who or what this is and why it matters to Hong Kong",
  "body": "200-400 words of markdown with ## headings. Focus on the connection to Hong Kong. Use **bold** for key names and dates.",
  "timeline": [{{"year": "YYYY", "event": "One line"}}],
  "tags": ["lowercase-hyphenated", "max-5"]}}"""

VERIFY_PROMPT = """You are fact-checking a draft page of a Hong Kong history website.
Check each claim below against the reference text only (extracts from Wikipedia).
"supported": the text states it. "contradicted": the text states something different
(give the correct fact). "unclear": the text does not cover it. Do not use outside knowledge.

Page title: {title}
Claims:
{claims}

Reference text:
{reference}

Respond with ONLY a JSON object, no other text:
{{"verdicts": [{{"claim": "the claim", "status": "supported | contradicted | unclear", "note": "One sentence: what the sources say, with the correct fact if contradicted"}}]}}"""


# ---- plan state ------------------------------------------------------

def load_plan():
    if os.path.exists(PLAN_FILE):
        with open(PLAN_FILE, encoding="utf-8") as f:
            plan = json.load(f)
    else:
        plan = {"eras": {}, "events": []}
    plan.setdefault("entities", {})
    # Worker progress lives in scripts/state/<name>.json so parallel threads never share a file.
    for key in ("photos", "evidence"):
        if key in plan:
            merged = {**plan.pop(key), **state.load(key)}
            state.save(key, merged)
    for slug, _, _ in ERAS:
        plan["eras"].setdefault(slug, {"outlined": False, "overview": False, "rounds": 0})
    return plan


def save_plan(plan):
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)


def make_slug(text, max_len=70):
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:max_len]
    return slug or "event"


def era_events(plan, era):
    return [e for e in plan["events"] if e["era"] == era]


def add_events(plan, era, events):
    known = {make_slug(e["title"]) for e in plan["events"]}
    added = 0
    for ev in events:
        title = str(ev.get("title", "")).strip()
        if not title or make_slug(title) in known:
            continue
        try:
            year = int(ev.get("year"))
        except (TypeError, ValueError):
            year = None
        plan["events"].append({
            "era": era,
            "title": title,
            "year": year,
            "date": str(ev.get("date", "")),
            "summary": str(ev.get("summary", "")),
            "status": "pending",
        })
        known.add(make_slug(title))
        added += 1
    return added


def entity_key(name):
    """'Charles Elliot (義律)' -> 'charles-elliot'; falls back to the Chinese if there is no English."""
    english = re.sub(r"[（(].*?[)）]", "", name).strip()
    return make_slug(english or name, 60)


def entity_link(kind, name):
    folder = "People" if kind == "person" else "Places"
    return f"[[02_Entities/{folder}/{entity_key(name)}|{name}]]"


def register_entities(plan, ev, data):
    for kind, field in (("person", "people"), ("place", "places")):
        for name in data.get(field, []) or []:
            name = str(name).strip()
            key = f"{kind}:{entity_key(name)}"
            if not name or key.endswith(":event"):
                continue
            ent = plan["entities"].setdefault(key, {"name": name, "kind": kind, "mentions": [], "status": "pending"})
            if ev["title"] not in ent["mentions"]:
                ent["mentions"].append(ev["title"])


# ---- page writing ----------------------------------------------------

def yaml_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', "'").replace("\n", " ") + '"'


def frontmatter_date(ev):
    """Only emit a YAML date for CE years Quartz can parse; ancient events rely on the title/year field."""
    d = ev.get("date", "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d
    year = ev.get("year")
    if isinstance(year, int) and 1000 <= year <= 9999:
        return f"{year}-01-01"
    return None


def year_prefix(year):
    if not isinstance(year, int):
        return "xxxx"
    return f"{year:04d}" if year >= 0 else "0000"


def render_perspectives(items):
    if not items:
        return []
    out = ["", "## Perspectives", ""]
    for p in items:
        out.append(f"- **{p.get('viewpoint', 'View')}**: {p.get('text', '')}")
    return out


def write_page(path, meta, body_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["---"] + [f"{k}: {v}" for k, v in meta.items() if v is not None] + ["---", ""]
    lines += [
        "> [!warning] AI draft",
        "> Written from general knowledge by an AI model, without cited sources. "
        "Treat it as a starting outline and verify claims before relying on them.",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines + body_lines).rstrip() + "\n")


def tag_list(tags):
    clean = sorted({make_slug(str(t), 40) for t in tags if str(t).strip()})
    return "[" + ", ".join(f'"{t}"' for t in clean) + "]"


def write_event_page(era, ev, data, model):
    name, _ = ERA_BY_SLUG[era]
    slug = make_slug(ev["title"])
    rel = os.path.join(era, f"{year_prefix(ev.get('year'))}-{slug}.md")
    tags = list(data.get("tags", [])) + ["ai-draft", era[3:]]
    if isinstance(ev.get("year"), int) and ev["year"] > 0:
        tags.append(str(ev["year"]))
    body = [data.get("body", "").strip()]
    body += render_perspectives(data.get("perspectives"))
    if data.get("people") or data.get("places"):
        body += ["", "## People and places", ""]
        body += [f"- {entity_link('person', x)}" for x in data.get("people", [])]
        body += [f"- {entity_link('place', x)}" for x in data.get("places", [])]
    if data.get("claims_to_verify"):
        body += ["", "## Claims to verify", ""]
        body += [f"- [ ] {c}" for c in data["claims_to_verify"]]
    body += ["", f"Part of: [[01_Timeline/{era}/index|{name}]]"]
    meta = {
        "title": yaml_str(ev["title"]),
        "title_zh": yaml_str(data["title_zh"]) if data.get("title_zh") else None,
        "date": frontmatter_date(ev),
        "year": ev.get("year"),
        "era": yaml_str(name),
        "tags": tag_list(tags),
        "summary": yaml_str(data.get("summary", ev.get("summary", ""))),
        "description": yaml_str(make_summary(data.get("summary") or ev.get("summary", ""))),
        "confidence": "ai-draft",
        "draft_model": model,
        "ingested": datetime.now().strftime("%Y-%m-%d"),
    }
    write_page(os.path.join(TIMELINE_DIR, rel), meta, body)
    return rel


def write_overview_page(era, data, model):
    name, span = ERA_BY_SLUG[era]
    body = [data.get("body", "").strip()] + render_perspectives(data.get("perspectives"))
    meta = {
        "title": yaml_str(f"{era[:2]} · {name} ({span})"),
        "tags": tag_list(list(data.get("tags", [])) + ["ai-draft", "era-overview"]),
        "summary": yaml_str(data.get("summary", "")),
        "description": yaml_str(make_summary(data.get("summary", ""))),
        "confidence": "ai-draft",
        "draft_model": model,
        "ingested": datetime.now().strftime("%Y-%m-%d"),
    }
    rel = os.path.join(era, "index.md")
    write_page(os.path.join(TIMELINE_DIR, rel), meta, body)
    return rel


def write_entity_page(ent, data, model):
    folder = "People" if ent["kind"] == "person" else "Places"
    rel = os.path.join(folder, f"{entity_key(ent['name'])}.md")
    body = [data.get("body", "").strip()]
    if data.get("timeline"):
        body += ["", "## Timeline", ""]
        body += [f"- **{t.get('year', '')}**: {t.get('event', '')}" for t in data["timeline"]]
    body += ["", "## Mentioned in", ""] + [f"- {t}" for t in ent["mentions"]]
    meta = {
        "title": yaml_str(ent["name"]),
        "title_zh": yaml_str(data["title_zh"]) if data.get("title_zh") else None,
        "tags": tag_list(list(data.get("tags", [])) + ["ai-draft", ent["kind"]]),
        "summary": yaml_str(data.get("summary", "")),
        "description": yaml_str(make_summary(data.get("summary", ""))),
        "confidence": "ai-draft",
        "draft_model": model,
        "ingested": datetime.now().strftime("%Y-%m-%d"),
    }
    write_page(os.path.join(ENTITY_DIR, rel), meta, body)
    return rel


def apply_verification(path, verdicts, sources, model):
    with PAGE_LOCK:
        return _apply_verification_unlocked(path, verdicts, sources, model)


def _apply_verification_unlocked(path, verdicts, sources, model):
    """Replace the page's claim checklist with fact-check results and web sources."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    icon = {"supported": "✅", "contradicted": "❌", "unclear": "❔"}
    lines = ["## Fact check", "",
             f"Checked by {model} against the Wikipedia articles below (grade C, reference) on "
             f"{datetime.now().strftime('%Y-%m-%d')}. \"Unclear\" means Wikipedia does not cover the claim; "
             "it still needs a primary or scholarly source.", ""]
    for v in verdicts:
        status = str(v.get("status", "unclear")).strip().lower()
        lines.append(f"- {icon.get(status, '❔')} **{status}**: {v.get('claim', '')}. {v.get('note', '')}".rstrip())
    if sources:
        lines += ["", "## Sources", ""] + [f"- [{s['title']}]({s['uri']})" for s in sources]
    block = "\n".join(lines) + "\n\n"
    text = re.sub(r"## Claims to verify\n.*?(?=Part of: )", lambda _: block, text, count=1, flags=re.DOTALL)
    contradicted = any(str(v.get("status", "")).lower() == "contradicted" for v in verdicts)
    text = text.replace("confidence: ai-draft\n", "confidence: ai-draft-checked\n", 1)
    extra = '"fact-checked"' + (', "needs-correction"' if contradicted else "")
    text = re.sub(r"^tags: \[", lambda _: f"tags: [{extra}, ", text, count=1, flags=re.MULTILINE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return contradicted


def verify_pages(pool, plan, deadline, limit=VERIFY_PAGES_PER_RUN):
    """Fact-check the highest-priority unchecked drafts against Wikipedia."""
    checked = 0
    for ev in by_priority(plan["events"]):
        if time.time() > deadline or checked >= limit or pool.total_remaining("verify") == 0:
            break
        if ev["status"] != "done" or ev.get("verified"):
            continue
        path = os.path.join(TIMELINE_DIR, ev["file"])
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            claims = re.findall(r"^- \[ \] (.+)$", f.read(), flags=re.MULTILINE)
        if not claims:
            ev["verified"] = "no-claims"
            continue
        try:
            reference, sources = wikipedia.reference_text(ev["title"], claims)
        except Exception as e:
            print(f"[verify] Wikipedia unreachable ({e}); stopping fact-checks for this run")
            break
        if not reference:
            ev["verified"] = "no-reference"
            save_plan(plan)
            continue
        try:
            data, model, _ = pool.generate_json("verify", VERIFY_PROMPT.format(
                title=ev["title"], claims="\n".join(f"- {c}" for c in claims), reference=reference))
        except QuotaExhausted:
            break
        verdicts = data.get("verdicts", []) if isinstance(data, dict) else []
        if not verdicts:
            continue
        bad = apply_verification(path, verdicts, sources, model)
        ev["verified"] = datetime.now().strftime("%Y-%m-%d")
        save_plan(plan)
        checked += 1
        print(f"[verify] {ev['file']}: {len(verdicts)} claims, {len(sources)} sources"
              + (" - NEEDS CORRECTION" if bad else "") + f" ({model})")
    return checked


# ---- steps -----------------------------------------------------------

def outline(pool, plan, era, count, exclude=None):
    name, span = ERA_BY_SLUG[era]
    existing = ""
    if exclude:
        existing = ("\nThese events are already covered, so list DIFFERENT ones "
                    "(gaps, social history, lesser-known episodes):\n- " + "\n- ".join(exclude) + "\n")
    data, model, _ = pool.generate_json("outline", OUTLINE_PROMPT.format(
        name=name, span=span, count=count, existing=existing))
    events = data.get("events", data) if isinstance(data, dict) else data
    added = add_events(plan, era, events if isinstance(events, list) else [])
    print(f"[outline] {era}: +{added} events ({model})")
    return added


def is_core(era):
    return era >= CORE_ERA_START


def by_priority(events):
    """Core-period events first, plan order otherwise."""
    return sorted(events, key=lambda e: not is_core(e["era"]))


def next_task(plan):
    for slug, _, _ in ERAS:
        if not plan["eras"][slug]["outlined"]:
            return ("outline", slug)
    for slug, _, _ in ERAS:
        if not plan["eras"][slug]["overview"]:
            return ("overview", slug)
    pending = by_priority(e for e in plan["events"] if e["status"] == "pending")
    if pending:
        return ("draft", pending[0])
    ents = [e for e in plan["entities"].values() if e["status"] == "pending"]
    if ents:
        return ("entity", max(ents, key=lambda e: len(e["mentions"])))
    # Everything drafted: deepen the thinnest era that still has rounds left.
    candidates = [s for s, _, _ in ERAS if is_core(s) and plan["eras"][s]["rounds"] < MAX_ROUNDS]
    if candidates:
        return ("deepen", min(candidates, key=lambda s: len(era_events(plan, s))))
    return None


def research_worker(pool, events, deadline):
    """OpenRouter + free archive APIs (+ Gemma): Deep Research import, then evidence grades."""
    grades = state.load("evidence")
    import_inbox(events, grades)
    state.save("evidence", grades)
    n = evidence_batch(pool, grades, events, deadline, limit=EVIDENCE_PAGES_PER_RUN,
                       save=lambda d: state.save("evidence", d))
    write_status_page(events, grades)
    return n


def photos_worker(pool, events, deadline):
    """Gemma vision + Wikimedia Commons: photos for event pages."""
    return photos_batch(pool, state.load("photos"), events, deadline, limit=PHOTO_EVENTS_PER_RUN,
                        save=lambda d: state.save("photos", d))


def start_worker(name, fn, results):
    def target():
        try:
            results[name] = fn()
        except Exception:
            print(f"[{name}] worker crashed:")
            traceback.print_exc()
            results[name] = 0
    t = threading.Thread(target=target, name=name, daemon=True)
    t.start()
    return t


def run(max_calls, minutes, commit=False):
    """Three workers run in parallel, each on a different quota, so a slow or exhausted
    provider only holds up its own work:
      research (thread): OpenRouter + archive APIs -> Deep Research import, evidence
      photos   (thread): Gemma vision + Commons    -> photo evidence
      gemini   (main):   Gemini 2.5 / 3.x           -> fact-check, then drafting
    """
    pool = ModelPool()
    plan = load_plan()
    deadline = time.time() + minutes * 60
    print(f"Quota at start: {pool.summary()}")
    print(f"Model ids: {pool.state['resolved']}")
    events = by_priority(plan["events"])  # snapshot: workers never see the drafting loop's appends
    results = {}
    workers = [start_worker("research", lambda: research_worker(pool, events, deadline), results),
               start_worker("photos", lambda: photos_worker(pool, events, deadline), results)]

    done = verify_pages(pool, plan, deadline)
    if TRANSLATE_WITH_AI:
        # OpenRouter's free budget is separate from Gemini's, so spend it every run.
        openrouter = [k for k in pool.routing.get("translate", []) if pool.models[k].get("provider") == "openrouter"]
        done += translate_batch(pool, plan, deadline, only=openrouter, save=save_plan)
    while done < max_calls and time.time() < deadline:
        task = next_task(plan)
        if task is None:
            print("Seed plan complete: every era outlined, drafted and deepened.")
            if TRANSLATE_WITH_AI:
                done += translate_batch(pool, plan, deadline, limit=max_calls - done, save=save_plan)
            break
        kind, arg = task
        try:
            if kind == "outline":
                outline(pool, plan, arg, 20)
                plan["eras"][arg]["outlined"] = True
            elif kind == "deepen":
                titles = [e["title"] for e in era_events(plan, arg)]
                plan["eras"][arg]["rounds"] += 1
                outline(pool, plan, arg, 10, exclude=titles)
            elif kind == "overview":
                name, span = ERA_BY_SLUG[arg]
                titles = "; ".join(e["title"] for e in era_events(plan, arg))
                data, model, _ = pool.generate_json("outline", OVERVIEW_PROMPT.format(
                    name=name, span=span, titles=titles, style=STYLE))
                rel = write_overview_page(arg, data, model)
                plan["eras"][arg]["overview"] = True
                print(f"[overview] {rel} ({model})")
            elif kind == "draft":
                ev = arg
                name, span = ERA_BY_SLUG[ev["era"]]
                data, model, _ = pool.generate_json("draft", EVENT_PROMPT.format(
                    name=name, span=span, title=ev["title"], date=ev["date"] or ev["year"],
                    summary=ev["summary"], style=STYLE))
                ev["file"] = write_event_page(ev["era"], ev, data, model)
                ev["status"] = "done"
                register_entities(plan, ev, data)
                print(f"[draft] {ev['file']} ({model})")
            elif kind == "entity":
                ent = arg
                data, model, _ = pool.generate_json("draft", ENTITY_PROMPT.format(
                    kind=ent["kind"].title(), kind_lower=ent["kind"], name=ent["name"],
                    context="; ".join(ent["mentions"][:8]), style=STYLE))
                ent["file"] = write_entity_page(ent, data, model)
                ent["status"] = "done"
                print(f"[entity] {ent['file']} ({model})")
        except QuotaExhausted as e:
            print(f"Out of quota: {e}")
            break
        except Exception as e:
            # A malformed response should not stall the queue forever.
            print(f"[{kind}] failed: {e}")
            if kind in ("draft", "entity"):
                arg["status"] = "failed"
            elif kind in ("outline", "overview"):
                plan["eras"][arg]["outlined" if kind == "outline" else "overview"] = True
        save_plan(plan)
        done += 1
        if commit and done % COMMIT_EVERY == 0:
            try:
                git_commit()
            except subprocess.CalledProcessError as e:
                print(f"Periodic commit failed, will retry at the end: {e}")
    for t in workers:
        t.join(timeout=max(0, deadline - time.time()) + 180)
        if t.is_alive():
            print(f"[{t.name}] still running at the deadline; its progress so far is saved")
    done += sum(results.values())
    counts = {}
    for e in plan["events"]:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    ent_done = sum(1 for e in plan["entities"].values() if e["status"] == "done")
    checked = sum(1 for e in plan["events"] if e.get("verified"))
    print(f"Workers: {results}")
    print(f"Ran {done} tasks. Events: {counts}, fact-checked {checked}. "
          f"Entities: {ent_done}/{len(plan['entities'])}. Quota now: {pool.summary()}")
    return done


def git_commit():
    paths = ["content/00_Meta", "content/01_Timeline", "content/02_Entities", "content/zh",
             "research", "scripts/state", "scripts/seed_plan.json", "scripts/quota_state.json"]
    subprocess.run(["git", "add", "-A", "--"] + [p for p in paths if os.path.exists(os.path.join(PROJECT_ROOT, p))],
                   cwd=PROJECT_ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT).returncode == 0:
        print("Nothing new to commit.")
        return
    msg = f"auto(seed): AI-drafted history pages {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)
    print("Git push completed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-calls", type=int, default=10_000, help="stop after this many tasks")
    ap.add_argument("--minutes", type=float, default=120, help="stop after this many minutes")
    ap.add_argument("--no-commit", action="store_true", help="write files but skip git commit/push")
    args = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")
    ran = run(args.max_calls, args.minutes, commit=not args.no_commit)
    if ran and not args.no_commit:
        git_commit()
