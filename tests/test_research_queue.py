import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_queue as queue


def test_queue_prioritizes_core_contradictions_then_unverified_gaps(monkeypatch):
    monkeypatch.setattr(queue, "validate_record", lambda row: [])
    records = {
        "claims": [
            {"id": "supported-complete", "event_id": "e", "importance": "core", "status": "supported",
             "text": "Complete claim", "updated_at": "2026-10-01T00:00:00Z", "is_current": True},
            {"id": "core-unverified", "event_id": "e", "importance": "core", "status": "unverified",
             "text": "Unverified core claim", "updated_at": "2026-10-02T00:00:00Z", "is_current": True},
            {"id": "core-contradicted", "event_id": "e", "importance": "core", "status": "contradicted",
             "text": "Contradicted core claim", "updated_at": "2026-10-03T00:00:00Z", "is_current": True},
            {"id": "supporting-unverified", "event_id": "e", "importance": "supporting", "status": "unverified",
             "text": "Supporting claim", "updated_at": "2026-10-04T00:00:00Z", "is_current": True},
        ],
        "sources": [],
        "evidence": [
            {"claim_id": "supported-complete", "evidence_id": "ev1", "relation": "supports",
             "passage_status": "inspectable", "passage": "An inspectable passage that is comfortably longer than thirty characters."},
        ],
        "judgements": [
            {"claim_id": "supported-complete", "judgement_id": "j1", "verdict": "supported",
             "judged_at": "2026-10-05T00:00:00Z"},
        ],
    }
    result = queue.build_queue(records)
    assert [row["claim_id"] for row in result] == [
        "core-contradicted", "core-unverified", "supporting-unverified",
    ]
    assert result[0]["priority"] == 1
    assert "status=contradicted" in result[0]["priority_reasons"]
    assert "no inspectable passage" in result[1]["priority_reasons"]


def test_queue_includes_supported_claim_missing_a_judgement(monkeypatch):
    monkeypatch.setattr(queue, "validate_record", lambda row: [])
    claim = {"id": "c1", "event_id": "e", "importance": "core", "status": "supported",
             "text": "Claim", "updated_at": "2026-10-01T00:00:00Z", "is_current": True}
    evidence = {"claim_id": "c1", "evidence_id": "ev1", "relation": "supports",
                "passage_status": "inspectable", "passage": "An inspectable passage that is comfortably longer than thirty characters."}
    result = queue.build_queue({"claims": [claim], "sources": [], "evidence": [evidence], "judgements": []})
    assert len(result) == 1
    assert result[0]["claim_id"] == "c1"
    assert "no judgement" in result[0]["priority_reasons"]


def test_queue_output_is_jsonl_and_never_overwrites_existing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(queue, "load_records", lambda records_dir: {
        "claims": [], "sources": [], "evidence": [], "judgements": [],
    })
    output = tmp_path / "queue.jsonl"
    assert queue.main(["--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == ""
    assert "read-only" in capsys.readouterr().err
    try:
        queue.main(["--output", str(output)])
    except SystemExit:
        raise
    except Exception:
        pass
    else:
        raise AssertionError("expected exclusive file creation to reject overwrite")
