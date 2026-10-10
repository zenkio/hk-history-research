"""Regression tests for the experimental atomic-claim extraction contract."""
import pytest

from atomic_claims import extract_atomic_claims, validate_atomic_claims


def test_claims_require_source_excerpt_and_preserve_provenance():
    source = "Britain occupied Hong Kong Island in 1841 and established a colonial administration."
    result = validate_atomic_claims({
        "claims": [
            {
                "text": "Britain occupied Hong Kong Island in 1841.",
                "source_excerpt": "Britain occupied Hong Kong Island in 1841",
                "claim_type": "action",
                "importance": "core",
            },
            {
                "text": "A colonial administration was established.",
                "source_excerpt": "established a colonial administration",
                "claim_type": "institution",
                "importance": "core",
            },
        ]
    }, source)

    assert [item["text"] for item in result] == [
        "Britain occupied Hong Kong Island in 1841.",
        "A colonial administration was established.",
    ]
    assert all(item["extraction"] == "ai_with_source_excerpt" for item in result)


def test_claims_with_invented_or_missing_excerpts_are_rejected():
    source = "The harbour was used for trade."
    result = validate_atomic_claims({
        "claims": [
            {"text": "The harbour was used for trade.", "source_excerpt": "harbour was used for trade"},
            {"text": "The treaty was signed in 1842.", "source_excerpt": "The treaty was signed in 1842."},
            {"text": "A new port was established."},
        ]
    }, source)
    assert [item["text"] for item in result] == ["The harbour was used for trade."]


def test_duplicate_claims_are_deduplicated_and_invalid_labels_normalised():
    result = validate_atomic_claims({
        "claims": [
            {"text": "The harbour opened.", "source_excerpt": "The harbour opened.", "claim_type": "made-up", "importance": "urgent"},
            {"text": "  The harbour   opened. ", "source_excerpt": "The harbour opened.", "claim_type": "action", "importance": "core"},
        ]
    }, "The harbour opened.")
    assert len(result) == 1
    assert result[0]["claim_type"] == "other"
    assert result[0]["importance"] == "supporting"


def test_malformed_or_unanchored_extraction_fails_closed():
    with pytest.raises(ValueError, match="claims list"):
        validate_atomic_claims({"claims": "not a list"}, "A source sentence.")
    with pytest.raises(ValueError, match="no claims grounded"):
        validate_atomic_claims({
            "claims": [{"text": "An invented statement.", "source_excerpt": "not in source"}]
        }, "A source sentence.")


def test_extractor_uses_evidence_role_and_returns_model_and_version():
    class FakePool:
        def __init__(self):
            self.role = None
            self.prompt = None

        def generate_json(self, role, prompt):
            self.role = role
            self.prompt = prompt
            return {
                "claims": [{
                    "text": "The harbour was used for trade.",
                    "source_excerpt": "The harbour was used for trade.",
                    "claim_type": "action",
                    "importance": "core",
                }]
            }, "fake-model", []

    pool = FakePool()
    result = extract_atomic_claims(
        pool,
        title="Harbour trade",
        date="1842",
        draft_text="The harbour was used for trade.",
    )
    assert pool.role == "evidence"
    assert "Harbour trade" in pool.prompt
    assert result["model"] == "fake-model"
    assert result["prompt_version"] == 1
    assert result["claims"][0]["text"] == "The harbour was used for trade."
