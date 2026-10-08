"""Regression tests for ingestion failure safety."""
import process_ingestion as ingestion


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
