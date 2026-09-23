"""Small text helpers shared by the pipeline scripts."""
import re


def plain(text):
    """Strip markdown emphasis, links and wikilinks so text reads cleanly in previews."""
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def make_summary(text, limit=220):
    """Whole sentences up to `limit` characters, never cut mid-word.

    Quartz shows this as the page description in search results and link
    previews, so a hard slice like text[:120] produced 'expand its broadc'.
    """
    text = plain(text)
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    out = ""
    for s in sentences:
        if len(out) + len(s) + 1 > limit:
            break
        out = f"{out} {s}".strip()
    if not out:
        # First sentence alone is too long: cut at a word boundary.
        out = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


def yaml_quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', "'").replace("\n", " ") + '"'
