import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import adopt_existing as ae
import consolidate_drafts as cd
import draft_page as dp
import page_status as ps

OLD = """---
title: "Negotiation of the Convention of Chuenpi"
year: 1841
tags: ["ai-draft", "1841"]
draft_model: Gemini 3.5 Flash Lite
---

## Background

Qishan was sent to negotiate.

## What happened

On January 20, 1841 Elliot and Qishan agreed the Convention of Chuenpi.
"""
RESTATED = ("**1. What happened**\nOn 20 January 1841 Elliot and Qishan agreed the Convention of Chuenpi. " + "Word " * 90
            + "\n\n**2. Background**\nQishan was sent to negotiate.")


def setup(tmp_path):
    (tmp_path / ae.TIMELINE / "05-opium-war").mkdir(parents=True)
    (tmp_path / ae.TIMELINE / "05-opium-war/1841-negotiation-of-the-convention-of-chuenpi.md").write_text(OLD)
    (tmp_path / ae.TIMELINE / "05-opium-war/1841-hong-kong-declared-a-free-port.md").write_text(OLD.replace("Chuenpi", "Port"))
    (tmp_path / ae.TIMELINE / "05-opium-war/1842-convention-of-chuenpi-again.md").write_text(OLD.replace("1841", "1842"))
    (tmp_path / ps.PAGES).mkdir(parents=True)
    (tmp_path / ps.PAGES / "convention-of-chuenpi-1841.md").write_text(
        dp.page_text({"slug": "x", "title": "Convention of Chuenpi", "year": 1841, "reason": "r"},
                     [("Nemotron 3 Ultra", dp.REQUIRED[0], "**1. What happened**\n" + "Word " * 160)]))
    ps.save(tmp_path / dp.QUEUE, {"pages": ["convention-of-chuenpi-1841"], "proposals": []})
    return tmp_path


def gateway(answer):
    calls = []

    def make(model, token, seed=None, fallbacks=None):
        def call(system, prompt):
            calls.append(prompt)
            return answer
        return call
    return make, calls


def test_only_the_earlier_page_about_the_same_event_and_year_is_related(tmp_path):
    setup(tmp_path)
    assert [p.stem for p in ae.related("convention-of-chuenpi-1841", 1841, tmp_path)] == \
        ["1841-negotiation-of-the-convention-of-chuenpi"]


def test_an_earlier_page_becomes_one_more_draft_the_fold_can_read_and_is_added_once(tmp_path):
    setup(tmp_path)
    make, calls = gateway(RESTATED)
    assert ae.adopt_pending(tmp_path, "t", gateway=make) == {"convention-of-chuenpi-1841": 1}
    md = (tmp_path / ps.PAGES / "convention-of-chuenpi-1841.md").read_text()
    drafts = cd.callouts(md)
    assert set(drafts) == {"Nemotron 3 Ultra", "Gemini 3.5 Flash Lite"}  # labelled by the model the old page names
    assert "Gemini 3.5 Flash Lite" in md and "restated from the earlier page" in md
    assert "Do not add background" in calls[0] and "Qishan was sent to negotiate" in calls[0]
    assert ae.adopt_pending(tmp_path, "t", gateway=make) == {} and len(calls) == 1  # never twice


def test_a_cut_off_restatement_is_not_added(tmp_path):
    setup(tmp_path)
    make, _ = gateway("**1. What happened**\nShort.")
    assert ae.adopt_pending(tmp_path, "t", gateway=make) == {}
    assert "restated" not in (tmp_path / ps.PAGES / "convention-of-chuenpi-1841.md").read_text()
