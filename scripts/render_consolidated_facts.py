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
    sources = fact.get("backed_by_sources", [])
    if sources:
        rows.append("<b>Official sources:</b> " + "; ".join(esc(s.get("source", s)) for s in sources))
    if fact.get("status", "accepted") != "accepted":  # everything shown is accepted, so only say when it is not
        rows.append("<i>" + esc(STATUS.get(fact.get("status"), fact.get("status", ""))) + "</i>")
    return '<span class="fact-tip">' + "<br>".join(rows) + "</span>"


TOKEN = re.compile(r"\{\{([\w-]+)\|(.*?)\}\}")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def fact_span(fact, text):
    status = esc(fact.get("status", "accepted"))
    return f'<span class="fact fact-{status}" tabindex="0">{text}{tip(fact)}</span>'


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(\[{*])")
HEAD = re.compile(r"^\*\*[^*]+\*\*\s*")


def split_sentences(text):
    """(heading, [sentences]) of one narrative paragraph; shared with consolidate_drafts so that
    `sentence_ai[paragraph][sentence]` lines up with what is rendered."""
    m = HEAD.match(text)
    head = m.group(0) if m else ""
    return head, [x for x in SENTENCE_END.split(text[len(head):]) if x.strip()]


def sentence_span(sentence, facts, models):
    """A sentence, wholly underlined; hovering anywhere in it shows which AIs back it and its facts."""
    inside, parts, last = [], [], 0
    for match in TOKEN.finditer(sentence):
        fact = facts.get(match.group(1))
        if fact is None:
            raise SystemExit(f"narrative names an unknown fact id: {match.group(1)}")
        inside.append((fact, match.group(2)))
        parts.append(BOLD.sub(r"<strong>\1</strong>", esc(sentence[last:match.start()])))
        parts.append(f'<mark class="fact-in">{esc(match.group(2))}</mark>')
        last = match.end()
    parts.append(BOLD.sub(r"<strong>\1</strong>", esc(sentence[last:])))
    rows = []
    if models:
        rows.append("<b>Backed by AI:</b> " + ", ".join(esc(m) for m in models))
    for fact, shown in inside:
        backed = [b["model"] for b in fact.get("backed_by_ai", [])]
        row = f"<b>{esc(shown)}</b>: " + (", ".join(esc(m) for m in backed) or "none")
        if fact.get("differs"):
            row += " &middot; says differently: " + "; ".join(
                f'{esc(d["model"])} ({esc(d["said"])})' for d in fact["differs"])
        sources = fact.get("backed_by_sources", [])
        if sources:
            row += " &middot; official sources: " + "; ".join(esc(x.get("source", x)) for x in sources)
        if fact.get("status", "accepted") != "accepted":
            row += " &middot; <i>" + esc(STATUS.get(fact.get("status"), fact.get("status", ""))) + "</i>"
        rows.append(row)
    if not rows:
        return "".join(parts)
    status = " fact-disputed" if any(f.get("status") == "disputed" for f, _ in inside) else ""
    return (f'<span class="sent{status}" tabindex="0">{"".join(parts)}'
            f'<span class="fact-tip">{"<br>".join(rows)}</span></span>')


def paragraph(text, facts, models=None):
    """One narrative paragraph as HTML: **bold**, {{fact-id|text}} markers and one hover span per sentence;
    everything else is escaped. `models` lists, per sentence, the AIs whose drafts hold it."""
    head, sentences = split_sentences(text)
    models = models or []
    out = BOLD.sub(r"<strong>\1</strong>", esc(head))
    out += " ".join(sentence_span(x, facts, models[i] if i < len(models) else [])
                    for i, x in enumerate(sentences))
    return "<p>" + out + "</p>"


def render(record):
    facts = {f["id"]: f for f in record["facts"]}
    ai = record.get("sentence_ai", [])
    narrative = [paragraph(t, facts, ai[i] if i < len(ai) else None)
                 for i, t in enumerate(record.get("narrative", []))]
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
        '<p class="cons-note">One account written from what the AI drafts below say (unverified). Underlined sentences show which AIs back them (switch at the bottom right, off by default). '
        "Agreement between AIs is not evidence; official sources will be added to each fact later.</p>",
        '<label class="fact-switch"><input type="checkbox"> '
        "Show which AI backs each sentence</label>",
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
