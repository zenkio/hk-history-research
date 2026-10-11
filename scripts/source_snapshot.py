#!/usr/bin/env python3
"""Record what each v2.1 source page held when a run fetched it (acceptance criterion E3).

For every source URL in the given packets this fetches the page once and records the HTTP status,
retrieval time, content type, size and the SHA-256 of the bytes received, and whether each
source's passage is still found in the page text. It also asks the Internet Archive for its
closest saved copy, which a reviewer can open even after the live page changes.

Only hashes and metadata are written: the page itself is never saved, because the internal
processing basis covers short excerpts, not copies of whole pages. A page that cannot be fetched
is recorded as an access failure with its error; when the Internet Archive has a copy, that copy is
hashed and checked instead (status archived_copy_only). Nothing here ever stops the run.
"""
import argparse
import datetime
import hashlib
import html
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "hk-history-research/2.1 (source snapshot; https://github.com/zenkio/hk-history-research)"
WAYBACK = "https://archive.org/wayback/available?url="
TIMEOUT = 30
# Characters that differ between a page and a copied excerpt without changing the words.
FOLD = str.maketrans({"‑": "-", "‐": "-", "–": "-", "—": "-", " ": " ",
                      "‘": "'", "’": "'", "“": '"', "”": '"'})


def fold(text):
    """Lower-case text with dashes, quotes and spaces made uniform, for passage matching."""
    return re.sub(r"\s+", " ", str(text or "").translate(FOLD)).strip().casefold()


def page_text(data, content_type):
    """Plain text of a page, or None when it cannot be read here (e.g. a PDF without pypdf)."""
    if "pdf" in content_type or data[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception:
            return None
    charset = re.search(r"charset=([\w-]+)", content_type)
    text = data.decode(charset.group(1) if charset else "utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def squeeze(text):
    """Letters and digits only: PDF text breaks lines and words where a passage does not."""
    return re.sub(r"[\W_]+", "", fold(text))


def passage_found(passage, text):
    """True/False when the page text could be read, None when it could not."""
    if text is None:
        return None
    # Run 38181951012 missed an AAB PDF sentence that is on the page: compare squeezed text too.
    return fold(passage) in fold(text) or squeeze(passage) in squeeze(text)


def archived_copy_url(snapshot, url):
    """The raw bytes of a Wayback copy (the id_ form omits the archive's banner)."""
    return f"https://web.archive.org/web/{snapshot['timestamp']}id_/{url}"


def fetch(url, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=TIMEOUT) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read(), response.geturl()


def wayback(url, opener=urllib.request.urlopen):
    """The Internet Archive's closest saved copy of url, or None."""
    try:
        _, _, data, _ = fetch(WAYBACK + urllib.parse.quote(url, safe=""), opener)
        closest = json.loads(data).get("archived_snapshots", {}).get("closest") or {}
        if closest.get("available"):
            return {"url": closest.get("url"), "timestamp": closest.get("timestamp")}
    except Exception:
        pass
    return None


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_packets(packets, opener=urllib.request.urlopen):
    """{url: record} for every source URL in packets (a list of (file name, packet))."""
    pages = {}
    for name, packet in packets:
        for source in packet.get("sources", []):
            url = source.get("url")
            if not url:
                continue
            if url not in pages:
                record = {"retrieved_at": now(), "sources": []}
                try:
                    status, content_type, data, final_url = fetch(url, opener)
                    text = page_text(data, content_type)
                    record.update(status="fetched", http_status=status, final_url=final_url,
                                  content_type=content_type, bytes=len(data),
                                  sha256=hashlib.sha256(data).hexdigest(),
                                  text_readable=text is not None)
                    record["_text"] = text
                except Exception as exc:
                    record.update(status="access_failure", error=f"{type(exc).__name__}: {str(exc)[:200]}")
                record["wayback"] = wayback(url, opener)
                if record["status"] == "access_failure" and record["wayback"]:
                    # The live page failed (an SSL error, a 429): hash the archived copy instead,
                    # so a reviewer still has a fixed copy to check the passage against.
                    try:
                        _, content_type, data, _ = fetch(archived_copy_url(record["wayback"], url), opener)
                        record["wayback"].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                        record["_text"] = page_text(data, content_type)
                        record["status"] = "archived_copy_only"
                    except Exception as exc:
                        record["wayback"]["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                pages[url] = record
            record = pages[url]
            record["sources"].append({
                "packet": name,
                "source_id": source.get("source_id"),
                "passage_found": passage_found(source.get("passage"), record.get("_text"))
                if record["status"] in ("fetched", "archived_copy_only") else None,
            })
    for record in pages.values():
        record.pop("_text", None)
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packets", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    packets = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in args.packets]
    pages = snapshot_packets(packets)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump({"purpose": "E3 snapshot hashes; pages themselves are not saved", "pages": pages},
                  handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    sources = [s for r in pages.values() for s in r["sources"]]
    # Counts only: URLs and passages stay in the private output.
    print(f"snapshots | pages={len(pages)} | fetched={sum(r['status'] == 'fetched' for r in pages.values())} "
          f"| passages found={sum(s['passage_found'] is True for s in sources)} "
          f"not found={sum(s['passage_found'] is False for s in sources)} "
          f"unchecked={sum(s['passage_found'] is None for s in sources)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
