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


def name(model):
    """Model names must not be translated by the reader's browser."""
    return f'<span translate="no">{esc(model)}</span>'


def tip(fact):
    rows = []
    backed = fact.get("backed_by_ai", [])
    rows.append(("<b>Only this AI:</b> " if len(backed) == 1 else "<b>Backed by AI:</b> ")
                + (", ".join(name(b["model"]) for b in backed) or "none"))
    if fact.get("differs"):
        rows.append("<b>Says differently:</b> " + "; ".join(
            f'{name(d["model"])} ({esc(d["said"])})' for d in fact["differs"]))
    sources = fact.get("backed_by_sources", [])
    if sources:
        rows.append("<b>Official sources:</b> " + "; ".join(esc(s.get("source", s)) for s in sources))
    if fact.get("status", "accepted") != "accepted":  # everything shown is accepted, so only say when it is not
        rows.append("<i>" + esc(STATUS.get(fact.get("status"), fact.get("status", ""))) + "</i>")
    return '<span class="fact-tip">' + "<br>".join(rows) + "</span>"


COLOURS = ["sky", "butter", "mint", "rose", "peach", "lilac"]  # soft highlight colours; the first is the default
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


NAME_MARK = re.compile(r"⟦([^⟦⟧]+)⟧")


def mark_names(escaped):
    """Chinese proper-name mark (專名號): names the translation wrapped in ⟦ ⟧ are drawn underlined."""
    return NAME_MARK.sub(r'<span class="pn">\1</span>', escaped)


def sentence_span(sentence, facts, models, fact_ids=(), english=None, conflict=None):
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
    if english:  # sentence is a translation: both are in the page, the language switch shows one
        parts = [f'<span class="lang-zh">{mark_names("".join(parts))}</span><span class="lang-en" lang="en">{esc(english)}</span>']
    shown_ids = {f["id"] for f, _ in inside}
    inside += [(facts[i], facts[i]["text"]) for i in fact_ids if i in facts and i not in shown_ids]
    rows = []
    if models:
        rows.append("<b>Backed by AI:</b> " + ", ".join(name(m) for m in models))
    for fact, shown in inside:
        backed = [b["model"] for b in fact.get("backed_by_ai", [])]
        row = f"<b>{esc(shown)}</b>: " + (", ".join(name(m) for m in backed) or "none")
        if fact.get("differs"):
            row += " &middot; says differently: " + "; ".join(
                f'{name(d["model"])} ({esc(d["said"])})' for d in fact["differs"])
        sources = fact.get("backed_by_sources", [])
        if sources:
            row += " &middot; official sources: " + "; ".join(esc(x.get("source", x)) for x in sources)
        if fact.get("status", "accepted") != "accepted":
            row += " &middot; <i>" + esc(STATUS.get(fact.get("status"), fact.get("status", ""))) + "</i>"
        rows.append(row)
    if conflict:
        rows.append("<i>Disputed: an AI reviewer found this sentence conflicts with another sentence on this page ("
                    + esc(conflict.get("note", "")) + ")</i>")
    if not rows:
        return "".join(parts)
    status = " fact-disputed" if conflict or any(f.get("status") == "disputed" for f, _ in inside) else ""
    return (f'<span class="sent{status}" tabindex="0">{"".join(parts)}'
            f'<span class="fact-tip">{"<br>".join(rows)}</span></span>')


def paragraph(text, facts, models=None, fact_ids=None):
    """One narrative paragraph as HTML: **bold**, {{fact-id|text}} markers and one hover span per sentence;
    everything else is escaped. `models` lists, per sentence, the AIs whose drafts hold it."""
    head, sentences = split_sentences(text)
    models = models or []
    fact_ids = fact_ids or []
    out = BOLD.sub(r"<strong>\1</strong>", esc(head))
    out += " ".join(sentence_span(x, facts, models[i] if i < len(models) else [],
                                        fact_ids[i] if i < len(fact_ids) else ())
                    for i, x in enumerate(sentences))
    return "<p>" + out + "</p>"


ZH_TITLES = {"What happened": "事件經過", "Background": "背景", "Hong Kong at this time": "當時的香港",
             "China at this time": "當時的中國", "Britain at this time": "當時的英國", "Consequences": "後果",
             "Uncertain or disputed points": "不確定或有爭議之處"}


def both(english, chinese, translated):
    return (f'<span class="lang-zh">{chinese}</span><span class="lang-en" lang="en">{english}</span>'
            if translated else english)


def heading(number, title, translated):
    """Section heading; in both languages when the section has a Chinese version."""
    if not (translated and title in ZH_TITLES):
        return f"**{number}. {title}** "
    return (f'<strong>{number}. <span class="lang-zh">{ZH_TITLES[title]}</span>'
            f'<span class="lang-en" lang="en">{esc(title)}</span></strong> ')


def paragraph_from_units(head, units, facts):
    """A paragraph built from exact units {text, by, facts}: no re-splitting, so the backing lines up for sure.
    `head` is Markdown (**bold**) or ready HTML from heading()."""
    head_html = head if head.startswith("<strong>") else BOLD.sub(r"<strong>\1</strong>", esc(head))
    return "<p>" + head_html + " ".join(
        sentence_span(u.get("zh") or u["text"], facts, u.get("by", []), u.get("facts", ()),
                      u["text"] if u.get("zh") else None, u.get("conflict")) for u in units) + "</p>"


def render(record):
    facts = {f["id"]: f for f in record["facts"]}
    ai = record.get("sentence_ai", [])
    sf = record.get("sentence_facts", [])
    if record.get("sections"):  # written by the fold pipeline: exact sentence units with their backers
        narrative = [paragraph_from_units(heading(i + 1, sec["title"], all(u.get("zh") for u in sec["units"])),
                                         sec["units"], facts)
                     for i, sec in enumerate(record["sections"])]
    else:
        narrative = [paragraph(t, facts, ai[i] if i < len(ai) else None, sf[i] if i < len(sf) else None)
                     for i, t in enumerate(record.get("narrative", []))]
    has_zh = any(u.get("zh") for sec in record.get("sections", []) for u in sec["units"])
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
        *([ '<span class="lang-switch" role="group" aria-label="Language"><button type="button" data-lang="zh">中文</button>'
           '<button type="button" data-lang="en">English</button></span>'] if has_zh else []),
        '<p class="cons-note">' + both(
            "One account written from what the AI drafts below say (unverified). On a computer, turn on the switch at the bottom right and point at a sentence to see which AIs back it; on a phone, hold a sentence for a moment. "
            "Agreement between AIs is not evidence; official sources will be added to each fact later.",
            "根據下方各 AI 草稿寫成的綜合版本（未經核實）。電腦版請開啟右下角的開關，再把滑鼠移到句子上，即可看到哪些 AI 支持；手機版請按住句子片刻。"
            "多個 AI 意見一致並不等於有證據；官方來源日後會逐項加入。", has_zh) + "</p>",
        '<label class="fact-switch"><input type="checkbox"> '
        + both("Show which AI backs each sentence", "顯示每句由哪些 AI 支持", has_zh) + "</label>",
        '<span class="fact-colors" role="group" aria-label="Highlight colour">'
        + "".join(f'<label class="hl-{c}" title="{c}"><input type="radio" name="hl" value="{c}"'
                  f'{" checked" if c == COLOURS[0] else ""}></label>' for c in COLOURS)
        + "</span>",
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
