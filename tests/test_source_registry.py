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
    assert row["rights_policy"] == "review_required"
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
    policies = {row["source_id"]: row["rights_policy"] for row in rows}
    assert policies == {
        "hk-government-records-service": "metadata_only",
        "uk-national-archives-discovery": "metadata_only",
        "internet-archive": "item_rights_gate",
        "openalex": "cc0_dataset",
    }


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


def test_unreviewed_source_cannot_send_inspectable_passage_to_judge():
    registry = SourceRegistry([source("unreviewed", lambda query: [
        {"title": "Record", "passage": "A real passage of sufficient length.", "passage_status": "inspectable_record"},
    ])])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""
    assert "rights policy 'review_required'" in candidate["registry_note"]


def test_cc0_dataset_policy_allows_inspectable_dataset_content():
    registry = SourceRegistry([source("cc0", lambda query: [
        {"title": "Abstract", "passage": "Abstract text supplied in the CC0 dataset.", "passage_status": "inspectable_abstract"},
    ], rights_policy="cc0_dataset")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "inspectable_abstract"
    assert candidate["passage"] == "Abstract text supplied in the CC0 dataset."


def test_item_rights_gate_requires_explicit_public_domain_or_cc0_status():
    registry = SourceRegistry([source("archive", lambda query: [
        {"title": "OCR", "passage": "A passage whose item rights are unknown.", "passage_status": "inspectable_text"},
    ], rights_policy="item_rights_gate")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""
    assert "item_rights_gate" in candidate["registry_note"]


def test_item_rights_gate_allows_explicit_public_domain_or_cc0_status():
    registry = SourceRegistry([source("archive", lambda query: [
        {"title": "OCR", "passage": "A passage with explicit item rights.", "passage_status": "inspectable_text",
         "rights_status": "public_domain_or_cc0"},
    ], rights_policy="item_rights_gate")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "inspectable_text"
    assert candidate["rights_status"] == "public_domain_or_cc0"


def test_metadata_only_policy_downgrades_even_a_populated_passage():
    registry = SourceRegistry([source("catalogue", lambda query: [
        {"title": "Archive metadata", "passage": "A passage accidentally returned by adapter.",
         "passage_status": "inspectable_record"},
    ], rights_policy="metadata_only")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""


def test_unsupported_rights_policy_is_rejected():
    with pytest.raises(ValueError, match="unsupported rights_policy"):
        SourceRegistry([source("bad-policy", lambda query: [], rights_policy="unknown")])



def test_metadata_only_status_clears_any_accidentally_supplied_passage():
    registry = SourceRegistry([source("catalogue", lambda query: [
        {"title": "Catalogue entry", "passage": "Text that must not be sent to the model.",
         "passage_status": "metadata_only"},
    ], rights_policy="metadata_only")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""
    assert "passage cleared before AI judgement" in candidate["registry_note"]




def test_cc0_dataset_policy_does_not_authorize_full_text_passages():
    registry = SourceRegistry([source("cc0", lambda query: [
        {"title": "Full text", "passage": "Full text is not the OpenAlex abstract dataset.",
         "passage_status": "inspectable_text"},
    ], rights_policy="cc0_dataset")])
    candidate = registry.search("event")["candidates"][0]
    assert candidate["passage_status"] == "metadata_only"
    assert candidate["passage"] == ""
    assert "cc0_dataset" in candidate["registry_note"]


