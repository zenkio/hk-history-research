import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consolidate_drafts as cd

PAGE = """---
title: T
---

> [!info]- Claude (Anthropic): written from general knowledge, unverified
> _Author: Claude._
>
> **What happened.** The treaty was signed on 29 August 1842. Pottinger signed for Britain.
>
> **Background.** Opium paid for tea.

> [!info]- Nemotron 3 Ultra: AI draft, unverified
> _Model `x`_
>
> **1. What happened: when, where, who, in short**
> The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking.
>
> **2. Background: why it happened**
> Opium from India paid for tea and silk in China.

> [!info]- Gemini 3.6 Flash: AI draft, unverified
> _Model `y`_
>
> **1. What happened**
> * **When:** 29 August 1843 was given by this draft.
"""
FACTS = [{"id": "f1", "text": "Signed 29 August 1842"}]


def test_base_is_kept_and_new_sentences_from_other_drafts_are_added_with_their_model():
    paragraphs, stats = cd.build(PAGE)
    text = " ".join(paragraphs)
    assert "The treaty was signed on 29 August 1842 aboard HMS Cornwallis off Nanking." in text
    assert "Pottinger signed for Britain. (Claude)" in text
    assert "29 August 1843 was given by this draft. (Gemini 3.6 Flash)" in text  # a conflicting number is kept
    assert "Opium paid for tea." not in text  # said already by the base: not repeated


def test_check_passes_and_fails_when_a_number_is_lost():
    paragraphs, _ = cd.build(PAGE)
    assert cd.check(PAGE, paragraphs) == []
    lost = [p.replace("1843", "") for p in paragraphs]
    assert any("1843" in problem for problem in cd.check(PAGE, lost))
    short = [p for p in paragraphs if "Cornwallis" not in p]
    assert any("base sentence missing" in problem for problem in cd.check(PAGE, short))


def test_dates_of_a_fact_get_a_hover_marker_once():
    paragraphs, _ = cd.build(PAGE)
    marked, placed = cd.mark_facts(paragraphs, FACTS)
    text = " ".join(marked)
    assert placed == {"f1"} and "{{f1|29 August 1842}}" in text and text.count("{{f1|") == 1
