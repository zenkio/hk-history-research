"""Tests for the pluggable source registry contract; all adapters are faked."""
import pytest

from source_registry import SourceDefinition, SourceRegistry, build_default_registry


def source(source_id, search, **overrides):
    fields = {
        "source_id": source_id,
        "name": source_id,
        "institution": "Test archive",
        "source_type": "archive_record",
        "authority_level": "primary",
        "language": "en",
        "coverage": "Test-only coverage",
        "stable_url": "https://example.org/",
        "retrieval_method": "api",
        "search": search,
    }
    fields.update(overrides)
    return SourceDefinition(**fields)


def test_registry_lists_stable_metadata_without_adapter_callable():
    registry = SourceRegistry([source("test-archive", lambda query: [])])
    row = registry.list_sources()[0]
    assert row["source_id"] == "test-archive"
    assert row["institution"] == "Test archive"
    assert "search" not in row


def test_duplicate_source_ids_are_rejected():
    registry = SourceRegistry([source("duplicate", lambda query: [])])
    with pytest.raises(ValueError, match="duplicate source_id"):
        registry.register(source("duplicate", lambda query: []))


def test_search_attaches_provenance_and_preserves_metadata_only_status():
    registry = SourceRegistry([source("catalogue", lambda query: [
        {"title": "Possible record", "passage": "", "passage_status": "metadata_only"},
    ])])
    result = registry.search("Hong Kong 1841")
    candidate = result["candidates"][0]
    assert result["query"] == "Hong Kong 1841"
    assert candidate["registry_source_id"] == "catalogue"
    assert candidate["institution"] == "Test archive"
    assert candidate["passage_status"] == "metadata_only"
    assert result["failures"] == []


def test_inspectable_status_without_passage_is_downgraded():
    registry = SourceRegistry([source("broken-adapter", lambda query: [
        {"title": "Record", "passage": "  ", "passage_status": "inspectable_record"},
    ])])
    candidate = registry.search("treaty")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""
    assert "downgraded" in candidate["registry_note"]


def test_adapter_failure_is_explicit_not_a_false_zero_result():
    def fail(query):
        raise TimeoutError("archive unavailable")

    registry = SourceRegistry([source("offline", fail)])
    result = registry.search("fire")
    assert result["candidates"] == []
    assert result["failures"] == [{
        "source_id": "offline",
        "source_name": "offline",
        "error_type": "TimeoutError",
        "error": "archive unavailable",
    }]


def test_unknown_source_id_and_blank_query_are_rejected():
    registry = SourceRegistry([source("known", lambda query: [])])
    with pytest.raises(KeyError):
        registry.search("event", source_ids=["missing"])
    with pytest.raises(ValueError, match="non-empty"):
        registry.search("  ")


def test_default_registry_wraps_existing_adapters_without_network_calls():
    registry = build_default_registry()
    rows = registry.list_sources()
    assert {row["source_id"] for row in rows} == {
        "hk-government-records-service", "uk-national-archives-discovery", "internet-archive", "openalex",
    }
    assert all(row["stable_url"].startswith("https://") for row in rows)


def test_evidence_uses_registry_as_its_default_adapter_list():
    import evidence

    assert evidence.SOURCES == evidence.SOURCE_REGISTRY.adapters()
    assert [name for name, _ in evidence.SOURCES] == [
        "Hong Kong Government Records Service", "UK National Archives Discovery", "Internet Archive", "OpenAlex",
    ]


def test_search_reports_success_even_when_an_adapter_returns_zero_results():
    registry = SourceRegistry([source("empty-archive", lambda query: [])])
    result = registry.search("event")
    assert result["candidates"] == []
    assert result["failures"] == []
    assert result["successful_source_ids"] == ["empty-archive"]
