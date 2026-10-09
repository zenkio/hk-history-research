"""Regression tests for ingestion failure safety."""
import process_ingestion as ingestion



def test_successful_ingestion_is_still_an_unverified_ai_hypothesis(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    timeline = tmp_path / "timeline"
    angles = tmp_path / "angles"
    unverified = tmp_path / "unverified"
    for directory in (queue, timeline, angles, unverified):
        directory.mkdir()
    source = queue / "source.md"
    source.write_text(
        "source_url: https://example.org/history\\n"
        "feed: test-feed\\n"
        "pub_date: 2026-10-08\\n"
        "title: Example source\\n\\n"
        "Historical source text.",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingestion, "TIMELINE_DIR", str(timeline))
    monkeypatch.setattr(ingestion, "ANGLES_DIR", str(angles))
    monkeypatch.setattr(ingestion, "UNVERIFIED_DIR", str(unverified))
    monkeypatch.setattr(ingestion, "call_gemini", lambda *args, **kwargs: {
        "title": "Example historical event",
        "narrative": "The source reports an event.",
        "historical_date": "1841",
        "year_tags": ["1841"],
        "tags": ["history"],
        "confidence": "high",
        "category": "Timeline",
        "context": "",
    })

    ingestion.analyze_and_route(object(), str(source))

    pages = list(timeline.glob("*.md"))
    assert len(pages) == 1
    page = pages[0].read_text(encoding="utf-8")
    assert "confidence: ai-draft" in page
    assert "source_confidence: high" in page
    assert "origin: ai" in page
    assert "verification_status: unverified" in page
    assert "> [!warning] AI draft — research hypothesis" in page
    assert "not established history" in page
    assert not source.exists()


def test_classification_failure_keeps_source_queued(tmp_path, monkeypatch):
    queue_file = tmp_path / "queued-source.md"
    queue_file.write_text(
        "source_url: https://example.org/history\n"
        "feed: test-feed\n"
        "pub_date: 2026-10-08\n"
        "title: Example history source\n\n"
        "Historical source text.",
        encoding="utf-8",
    )
    unverified_dir = tmp_path / "unverified"
    unverified_dir.mkdir()
    monkeypatch.setattr(ingestion, "UNVERIFIED_DIR", str(unverified_dir))

    def fail_classification(*args, **kwargs):
        raise ValueError("temporary model failure")

    monkeypatch.setattr(ingestion, "call_gemini", fail_classification)

    try:
        ingestion.analyze_and_route(object(), str(queue_file))
    except RuntimeError as exc:
        assert "source remains queued" in str(exc)
    else:
        raise AssertionError("classification failure should stop processing")

    assert queue_file.exists()
    assert not (unverified_dir / queue_file.name).exists()
