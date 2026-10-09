"""Tests for the non-destructive legacy AI-draft labelling migration."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import label_legacy_ai_drafts as labels


def test_legacy_ingestion_page_gets_warning_without_changing_narrative():
    original = """---
title: Legacy event
confidence: high
source_feed: archive-feed
source_url: "https://example.org/history"
---

The existing narrative must remain byte-for-byte unchanged.

> Source: [archive](https://example.org/history)
"""
    updated, changed = labels.label_page(original)
    assert changed
    assert "confidence: ai-draft" in updated
    assert "source_confidence: high" in updated
    assert "origin: ai" in updated
    assert "verification_status: unverified" in updated
    assert "> [!warning] AI draft — research hypothesis" in updated
    assert "The existing narrative must remain byte-for-byte unchanged." in updated
    assert "> Source: [archive](https://example.org/history)" in updated
    again, changed_again = labels.label_page(updated)
    assert not changed_again
    assert again == updated


def test_explicitly_verified_source_feed_page_is_not_downgraded():
    original = """---
title: Reviewed event
confidence: reviewed
source_feed: archive-feed
verification_status: verified
---

Reviewed narrative.
"""
    updated, changed = labels.label_page(original)
    assert not changed
    assert updated == original


def test_preview_mode_does_not_write_files(tmp_path, capsys):
    page = tmp_path / "legacy.md"
    original = """---
title: Legacy event
confidence: medium
source_feed: archive-feed
---

Legacy narrative.
"""
    page.write_text(original, encoding="utf-8")
    assert labels.main(["--content-root", str(tmp_path)]) == 0
    assert page.read_text(encoding="utf-8") == original
    assert "Preview only; no files written" in capsys.readouterr().out
