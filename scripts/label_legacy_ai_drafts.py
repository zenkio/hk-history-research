#!/usr/bin/env python3
"""Safely label legacy AI-generated history pages as unverified research hypotheses.

Preview is the default. --write changes only frontmatter labels and adds a visible warning;
it never rewrites the narrative or source citations.
"""
import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTENT_ROOT = PROJECT_ROOT / "content"
WARNING = (
    "> [!warning] AI draft — research hypothesis\n"
    "> AI-generated summary from a discovered source. It has not been independently verified "
    "against inspectable historical evidence; treat it as a research lead, not established history.\n"
)
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---(?=\s|\Z)", re.S)
WARNING_MARKER = re.compile(r"(?im)^>\s*\[!warning\]\s*AI draft\b")


def fields(frontmatter):
    result = {}
    for line in frontmatter.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if match:
            result[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return result


def needs_warning(meta):
    confidence = meta.get("confidence", "").lower()
    origin = meta.get("origin", "").lower()
    verification = meta.get("verification_status", "").lower()
    publication = meta.get("publication_status", "").lower()
    tags = meta.get("tags", "").lower()
    if confidence == "ai-draft" or "ai-draft" in tags:
        return True
    # Legacy feed-ingested pages used confidence=high/medium/low without stating that
    # the narrative itself was AI-written. Do not downgrade pages explicitly verified/published.
    return (origin == "ai" or bool(meta.get("source_feed"))) and verification != "verified" and publication != "published"


def label_page(text):
    match = FRONTMATTER.match(text)
    if not match:
        return text, False
    raw_frontmatter = match.group(1)
    meta = fields(raw_frontmatter)
    if not needs_warning(meta):
        return text, False

    lines = raw_frontmatter.splitlines()
    changed = False

    def set_field(key, value):
        nonlocal changed
        prefix = re.compile(rf"^{re.escape(key)}:\s*")
        for index, line in enumerate(lines):
            if prefix.match(line):
                if line != f"{key}: {value}":
                    lines[index] = f"{key}: {value}"
                    changed = True
                return
        lines.append(f"{key}: {value}")
        changed = True

    old_confidence = meta.get("confidence", "")
    if old_confidence and old_confidence.lower() != "ai-draft" and not meta.get("source_confidence"):
        set_field("source_confidence", old_confidence)
    set_field("confidence", "ai-draft")
    if "origin" not in meta:
        lines.append("origin: ai")
        changed = True
    if "verification_status" not in meta:
        lines.append("verification_status: unverified")
        changed = True

    updated_frontmatter = "\n".join(lines)
    body = text[match.end():]
    if not WARNING_MARKER.search(body):
        body = "\n\n" + WARNING + body.lstrip("\n")
        changed = True
    if not changed:
        return text, False
    return "---\n" + updated_frontmatter + "\n---" + body, True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-root", type=Path, default=DEFAULT_CONTENT_ROOT)
    parser.add_argument("--write", action="store_true", help="apply labels; default is preview only")
    parser.add_argument("--quiet", action="store_true", help="suppress file paths; useful for public CI logs")
    args = parser.parse_args(argv)
    if not args.content_root.is_dir():
        print(f"Content root not found: {args.content_root}", file=sys.stderr)
        return 2

    scanned = changed = 0
    for path in sorted(args.content_root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(args.content_root).parts):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"Cannot read {path}: {exc}", file=sys.stderr)
            return 2
        scanned += 1
        updated, modified = label_page(original)
        if not modified:
            continue
        changed += 1
        if not args.quiet:
            print(f"{'Updated' if args.write else 'Would update'}: {path.relative_to(args.content_root)}")
        if args.write:
            from state import atomic_write
            atomic_write(str(path), updated)

    print(f"Pages scanned: {scanned}")
    print(f"Legacy AI-draft labels {'applied' if args.write else 'previewed'}: {changed}")
    if not args.write:
        print("Preview only; no files written. Re-run with --write to apply labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
