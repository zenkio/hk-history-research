import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consolidate_drafts as cd
import consolidate_pipeline as cp
import draft_page as dp
import page_status as ps

DRAFT = ("**1. What happened**\nThe Convention was agreed in January 1841 near Canton. " + "More words here. " * 80
         + "\n\n**2. Background**\nThe war went on.\n\n**7. Uncertain or disputed points**\nWhether it was ratified.")
TOPICS = [
    {"slug": "late-1841", "title": "Late", "year": 1841, "reason": "gap", "status": "proposed"},
    {"slug": "first-1843", "title": "First", "year": 1843, "reason": "gap", "status": "approved", "order": 2},
    {"slug": "zero-1841", "title": "Zero", "year": 1841, "reason": "gap", "status": "approved", "order": 1},
    {"slug": "done-1842", "title": "Done", "year": 1842, "reason": "gap", "status": "held"},
]


def setup(tmp_path, topics=TOPICS):
    (tmp_path / ps.PAGES).mkdir(parents=True)
    ps.save(tmp_path / dp.QUEUE, {"pages": ["handover-1997"], "proposals": [dict(t) for t in topics]})
    return tmp_path


def gateway_of(answers):
    def make(model, token, seed=None, fallbacks=None):
        assert fallbacks == []  # a draft is pinned: a fallback model would write a different draft

        def call(system, prompt):
            a = answers[model]
            if isinstance(a, Exception):
                raise a
            return a
        return call
    return make


def test_approved_topics_come_first_by_order_then_proposed_ones_and_held_ones_never(tmp_path):
    root = setup(tmp_path)
    got = dp.next_topics(ps.load(root / dp.QUEUE, {}), root, limit=5)
    assert [t["slug"] for t in got] == ["zero-1841", "first-1843", "late-1841"]


def test_a_page_is_made_from_the_drafts_in_the_format_the_fold_reads(tmp_path):
    root = setup(tmp_path)
    gw = gateway_of({dp.REQUIRED[0]: DRAFT, "gemini-3.5-flash": DRAFT})
    assert dp.draft_pending(root, "t", limit=1, gateway=gw) == ["zero-1841"]
    page = (root / ps.PAGES / "zero-1841.md").read_text()
    c = cd.callouts(page)
    assert list(c) == ["Nemotron 3 Ultra", "Gemini 3.5 Flash"]
    assert cd.sections(c["Nemotron 3 Ultra"])[0] and "unverified" in page and "ai-draft" in page
    q = ps.load(root / dp.QUEUE, {})
    assert {t["slug"]: t["status"] for t in q["proposals"]}["zero-1841"] == "page-exists"
    assert "zero-1841" in q["pages"]


def test_an_optional_model_that_fails_is_skipped_but_a_missing_nemotron_draft_waits(tmp_path):
    root = setup(tmp_path)
    gw = gateway_of({dp.REQUIRED[0]: DRAFT, "gemini-3.5-flash": Exception("422 no_eligible_route")})
    assert dp.draft_pending(root, "t", limit=1, gateway=gw) == ["zero-1841"]
    root2 = setup(tmp_path / "x")
    gw2 = gateway_of({dp.REQUIRED[0]: cp.WriterUnavailable("busy"), "gemini-3.5-flash": DRAFT})
    assert dp.draft_pending(root2, "t", gateway=gw2) == []
    assert not list((root2 / ps.PAGES).glob("*.md"))  # no page without Nemotron's draft: the topic waits for the next run
    assert {t["slug"]: t["status"] for t in ps.load(root2 / dp.QUEUE, {})["proposals"]}["zero-1841"] == "approved"


def test_a_too_short_answer_is_not_a_draft(tmp_path):
    root = setup(tmp_path)
    gw = gateway_of({dp.REQUIRED[0]: "Too short.", "gemini-3.5-flash": DRAFT})
    assert dp.draft_pending(root, "t", gateway=gw) == []
