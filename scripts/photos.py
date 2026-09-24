#!/usr/bin/env python3
"""Photos as historical evidence.

Two sources, handled differently because of copyright:

1. Photos inside source posts (HPHK Bristol, Gwulo, ...). Usually owned by the
   donors' families, so we never re-host or embed them. An AI reads each photo
   (what it shows, date and place clues) and the page gets a caption card that
   links to the photo and the post. Used by process_ingestion.py.

2. Wikimedia Commons. Freely licensed (public domain, CC0, CC BY, CC BY-SA), so
   matching photos are shown on our event pages with author, licence and a link
   back. Candidates come from Commons search; an AI looks at each one next to the
   event text and keeps it only if it is really relevant, noting what it
   corroborates or contradicts. Run from seed_history.py; progress in
   seed_plan.json under "photos".
"""
import os
import re
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

from gemini_pool import QuotaExhausted, RequestRejected
from state import PAGE_LOCK

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_DIR = os.path.join(PROJECT_ROOT, "content", "01_Timeline")
USER_AGENT = "hk-history-research/1.0 (https://github.com/zenkio/hk-history-research)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FREE_LICENSE = re.compile(r"public domain|^pd\b|pd-|cc0|^cc[ -]by(-sa)?\b", re.I)
MAX_SOURCE_PHOTOS = 3
MAX_EVENT_PHOTOS = 4   # enough to compare angles; more turns an event page into a gallery
CANDIDATES = 8          # vision checks per page; most search hits are generic views
MAX_IMAGE_BYTES = 4_000_000
STOPWORDS = set("""a an the of and or in on at to for from by with during after before under over into
its his her their new first second great end rise fall era period age""".split())

SOURCE_PHOTO_PROMPT = """This photo appears in a Hong Kong history post titled "{title}" ({url}).
Describe it as historical evidence, from what is visible only (signs, buildings, vehicles,
clothing, landscape). Do not guess beyond the evidence; say "unclear" where needed.

Respond with ONLY this JSON:
{{"caption": "One short caption",
  "shows": "2-3 sentences on what is visible",
  "date_estimate": "Year or range the visual clues suggest, with the clue, or unclear",
  "place": "Location if identifiable, with the clue, or unclear"}}"""

MATCH_PROMPT = """You are choosing illustrations for a Hong Kong history page.

Event: {title} ({date})
Page summary: {summary}

Candidate image from Wikimedia Commons:
File: {file}
Commons description: {description}
Commons date: {cdate}

Look at the image. Keep it only if it genuinely relates to this event (the event itself, the
people or place involved, or a map/document/artefact of it). A generic Hong Kong view is NOT enough.

Respond with ONLY this JSON:
{{"relevant": true,
  "kind": "contemporary photo | later photo of the site | map | artwork | document | artefact",
  "caption": "One sentence on what is visible",
  "supports": "One sentence on what it corroborates on the page, or empty",
  "conflicts": "Anything in the image or its metadata that contradicts the page, or empty"}}"""


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_IMAGE_BYTES + 1), r.headers.get("Content-Type", "")


def download_image(url):
    """(bytes, mime) for a photo URL, or None if it is not a usable image."""
    try:
        data, ctype = _get(url)
    except Exception:
        return None
    mime = ctype.split(";")[0].strip()
    if len(data) > MAX_IMAGE_BYTES or not mime.startswith("image/") or mime == "image/gif":
        return None
    return data, mime


# ---- 1. photos inside source posts -------------------------------------

def describe_source_photos(pool, image_urls, title, post_url):
    out = []
    for url in image_urls[:MAX_SOURCE_PHOTOS]:
        img = download_image(url)
        if not img:
            continue
        try:
            data, model, _ = pool.generate_json("vision", SOURCE_PHOTO_PROMPT.format(title=title, url=post_url),
                                                media=[img])
        except QuotaExhausted:
            print("  photos not described: vision quota used up")
            break
        except RequestRejected as e:
            print(f"  photo {url} not described: {str(e)[:100]}")
            continue
        data.update(url=url, model=model)
        out.append(data)
        print(f"  photo described ({model})")
    return out


def source_photo_section(photos, post_url, credit):
    if not photos:
        return []
    lines = ["## Photos in the source", "",
             f"> [!info] Photos belong to {credit}; shown here as descriptions with links, not copies. "
             f"Descriptions are AI readings of the images.", ""]
    for p in photos:
        lines.append(f"- 📷 **{p.get('caption', 'Photo')}** — {p.get('shows', '')}")
        details = []
        if p.get("date_estimate"):
            details.append(f"Date clues: {p['date_estimate']}")
        if p.get("place"):
            details.append(f"Place: {p['place']}")
        if details:
            lines.append(f"  {' · '.join(details)}")
        lines.append(f"  [View photo]({p['url']}) · [Original post]({post_url})")
    lines.append("")
    return lines


# ---- 2. Wikimedia Commons ---------------------------------------------

def search_query(title):
    words = [w for w in re.findall(r"[\w'-]+", title) if w.lower() not in STOPWORDS]
    q = " ".join(words)
    if "hong kong" not in q.lower():
        q += " Hong Kong"
    return q


def commons_search(query, limit=15):
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(limit),
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "800",
        "iiextmetadatafilter": "LicenseShortName|Artist|DateTimeOriginal|ImageDescription|Credit",
    }
    data, _ = _get(f"{COMMONS_API}?{urllib.parse.urlencode(params)}")
    pages = sorted(json.loads(data).get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = {k: re.sub(r"<[^>]+>", "", v.get("value", "")).strip()
                for k, v in (info.get("extmetadata") or {}).items()}
        lic = meta.get("LicenseShortName", "")
        if not FREE_LICENSE.search(lic) or not info.get("thumburl"):
            continue
        out.append({"file": p["title"], "thumb": info["thumburl"], "page": info.get("descriptionurl", ""),
                    "license": lic, "artist": meta.get("Artist", "unknown")[:120],
                    "date": meta.get("DateTimeOriginal", "")[:40],
                    "description": meta.get("ImageDescription", "")[:400]})
    return out


def _page_parts(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm = text.split("---", 2)[1] if text.startswith("---") else ""
    get = lambda k: (re.search(rf"^{k}: *\"?(.*?)\"?$", fm, re.M) or [None, ""])[1]
    return text, get("title"), get("date") or get("year"), get("summary")


def photo_block(photos):
    lines = ["## Photos from this period", ""]
    for p in photos:
        lines += [f"![{p['caption']}]({p['thumb']})", "",
                  f"*{p['caption']}* ({p['kind']}). {p['artist']}, {p['license']}, via "
                  f"[Wikimedia Commons]({p['page']})."]
        if p.get("supports"):
            lines.append(f"Corroborates: {p['supports']}")
        if p.get("conflicts"):
            lines.append(f"⚠️ Possible conflict: {p['conflicts']}")
        lines.append("")
    return lines


def add_photos_to_page(path, photos):
    with PAGE_LOCK:
        return _add_photos_to_page_unlocked(path, photos)


def _add_photos_to_page_unlocked(path, photos):
    text = _page_parts(path)[0]
    block = "\n".join(photo_block(photos)) + "\n"
    if "\nPart of: " in text:
        i = text.rindex("\nPart of: ")
        text = text[:i] + "\n" + block + text[i:]
    else:
        text = text.rstrip() + "\n\n" + block
    if "photo-corroborated" not in text and any(p.get("supports") for p in photos):
        text = re.sub(r"^tags: \[", 'tags: ["photo-corroborated", ', text, count=1, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def find_event_photos(pool, path, used=frozenset()):
    _, title, date, summary = _page_parts(path)
    try:
        candidates = commons_search(search_query(title))
    except Exception as e:
        print(f"  [photos] Commons search failed: {str(e)[:100]}")
        return None
    chosen = []
    # One photo per page: a single famous image should not illustrate dozens of events.
    for c in [c for c in candidates if c["file"] not in used][:CANDIDATES]:
        img = download_image(c["thumb"])
        if not img:
            continue
        try:
            verdict, model, _ = pool.generate_json("vision", MATCH_PROMPT.format(
                title=title, date=date, summary=summary, file=c["file"],
                description=c["description"] or "none", cdate=c["date"] or "unknown"), media=[img])
        except RequestRejected:
            continue
        if verdict.get("relevant") is True or str(verdict.get("relevant")).lower() == "true":
            c.update(caption=verdict.get("caption", c["file"]), kind=verdict.get("kind", "photo"),
                     supports=verdict.get("supports", ""), conflicts=verdict.get("conflicts", ""), model=model)
            chosen.append(c)
            if len(chosen) >= MAX_EVENT_PHOTOS:
                break
    return chosen


def photos_batch(pool, done_map, events, deadline, limit=None, save=None):
    """Illustrate event pages in `events` order; progress in done_map (rel -> files or "none").
    QuotaExhausted from the vision role ends the batch."""
    used = {f for v in done_map.values() if isinstance(v, list) for f in v}
    done = 0
    for ev in events:
        rel = ev.get("file")
        if not rel or rel in done_map:
            continue
        if time.time() > deadline or (limit is not None and done >= limit):
            break
        path = os.path.join(TIMELINE_DIR, rel)
        if not os.path.exists(path):
            continue
        try:
            chosen = find_event_photos(pool, path, used)
        except QuotaExhausted:
            break
        if chosen is None:
            break  # Commons unreachable; try again next run
        if chosen:
            add_photos_to_page(path, chosen)
        done_map[rel] = [c["file"] for c in chosen] or "none"
        used.update(c["file"] for c in chosen)
        done += 1
        print(f"[photos] {rel}: {len(chosen)} photo(s)")
        if save:
            save(done_map)
        time.sleep(1)  # be polite to the Commons API
    return done
