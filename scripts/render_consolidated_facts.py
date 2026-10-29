#!/usr/bin/env python3
"""Fill the consolidated-facts marker of a page with the facts kept in data/consolidated_facts/<event>.json.

Owner request 2026-10-29: each multi-AI page shows a consolidated version (the main claims) in which hovering
a fact tells which AIs back it, with a switch that turns that layer off. Official sources are added later to
the same records (`backed_by_sources`) and appear in the same tip.

Run in the data checkout before the Quartz build. A page opts in by containing `<!-- consolidated-facts -->`;
its record file is data/consolidated_facts/<file stem>.json. The page is rewritten in the working copy only.
The switch is a plain checkbox styled in quartz/styles/custom.scss (no script, so it survives SPA navigation);
a tap on a phone focuses the fact and shows the tip.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

MARKER = "<!-- consolidated-facts -->"
FACTS = Path("data/consolidated_facts")
PAGES = Path("content")
KINDS = {"date": "Date", "number": "Number", "person": "Person", "place": "Place", "other": "Fact"}
STATUS = {"accepted": "accepted (not yet checked against an official source)",
          "corroborated": "corroborated", "disputed": "disputed"}


def esc(text):
    return html.escape(str(text), quote=True)


def tip(fact):
    rows = []
    backed = fact.get("backed_by_ai", [])
    rows.append(("<b>Only this AI:</b> " if len(backed) == 1 else "<b>Backed by AI:</b> ")
                + (", ".join(esc(b["model"]) for b in backed) or "none"))
    if fact.get("differs"):
        rows.append("<b>Says differently:</b> " + "; ".join(
            f'{esc(d["model"])} ({esc(d["said"])})' for d in fact["differs"]))
    if fact.get("not_mentioned_by"):
        rows.append("<b>Not mentioned by:</b> " + ", ".join(esc(m) for m in fact["not_mentioned_by"]))
    sources = fact.get("backed_by_sources", [])
    rows.append("<b>Official sources:</b> " + (
        "; ".join(esc(s.get("source", s)) for s in sources) if sources else "none yet"))
    rows.append("<i>" + esc(STATUS.get(fact.get("status"), fact.get("status", ""))) + "</i>")
    return '<span class="fact-tip">' + "<br>".join(rows) + "</span>"


TOKEN = re.compile(r"\{\{([\w-]+)\|(.*?)\}\}")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def fact_span(fact, text):
    status = esc(fact.get("status", "accepted"))
    return f'<span class="fact fact-{status}" tabindex="0">{text}{tip(fact)}</span>'


def paragraph(text, facts):
    """One narrative paragraph as HTML: **bold** and {{fact-id|text}} markers; everything else is escaped."""
    def inline(match):
        fact = facts.get(match.group(1))
        if fact is None:
            raise SystemExit(f"narrative names an unknown fact id: {match.group(1)}")
        return fact_span(fact, esc(match.group(2)))
    parts, last = [], 0
    for match in TOKEN.finditer(text):
        parts.append(BOLD.sub(r"<strong>\1</strong>", esc(text[last:match.start()])))
        parts.append(inline(match))
        last = match.end()
    parts.append(BOLD.sub(r"<strong>\1</strong>", esc(text[last:])))
    return "<p>" + "".join(parts) + "</p>"


def render(record):
    facts = {f["id"]: f for f in record["facts"]}
    narrative = [paragraph(t, facts) for t in record.get("narrative", [])]
    items = []
    for fact in record["facts"]:
        kind = KINDS.get(fact.get("kind"), "Fact")
        status = esc(fact.get("status", "accepted"))
        items.append(
            f'<li><span class="fact fact-{status}" tabindex="0"><span class="fact-kind">{kind}</span> '
            f'{esc(fact["text"])}{tip(fact)}</span></li>')
    return "\n".join([
        "## Consolidated version (main claims)", "",
        '<div class="consolidated">',
        '<p class="cons-note">One account written from what the AI drafts below say (unverified). Underlined facts show which AIs back them. '
        "Agreement between AIs is not evidence; official sources will be added to each fact later.</p>",
        '<label class="fact-switch"><input type="checkbox" checked> '
        "Show which AI backs each fact (hover, or tap on a phone)</label>",
        *narrative,
        f'<details class="cons-facts-box"><summary class="cons-facts-title">All {len(items)} facts and who backs them</summary>',
        '<ul class="cons-facts">', *items, "</ul>", "</details>", "</div>"])


def build(root=Path(".")):
    done = []
    for page in sorted((root / PAGES).rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        if MARKER not in text:
            continue
        record_file = root / FACTS / f"{page.stem}.json"
        if not record_file.is_file():
            raise SystemExit(f"{page}: has the marker but {record_file} is missing")
        record = json.loads(record_file.read_text(encoding="utf-8"))
        page.write_text(text.replace(MARKER, render(record), 1), encoding="utf-8")
        done.append(str(page))
    return done


def main():
    argparse.ArgumentParser().parse_args()
    done = build()
    print(f"consolidated facts rendered on {len(done)} page(s)")


if __name__ == "__main__":
    sys.exit(main())
