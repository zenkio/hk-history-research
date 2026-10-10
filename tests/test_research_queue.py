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
    assert queue.main(["--output", str(output)]) == 2
    error = capsys.readouterr().err
    assert "FileExistsError" in error or "File exists" in error



def test_queue_includes_judgement_context_and_inspectable_conflict(monkeypatch):
    monkeypatch.setattr(queue, "validate_record", lambda row: [])
    claim = {"id": "c1", "event_id": "e", "importance": "core", "status": "contradicted",
             "text": "A disputed date", "updated_at": "2026-10-01T00:00:00Z", "is_current": True}
    evidence = [
        {"claim_id": "c1", "evidence_id": "ev1", "source_id": "s1", "relation": "supports",
         "passage_status": "inspectable", "passage": "A direct passage supporting the stated date."},
        {"claim_id": "c1", "evidence_id": "ev2", "source_id": "s2", "relation": "contradicts",
         "passage_status": "inspectable", "passage": "A direct passage contradicting the stated date."},
    ]
    judgement = {"claim_id": "c1", "judgement_id": "j1", "verdict": "contradicted",
                 "rationale": "The sources conflict on the year.", "uncertainty": "Needs source review.",
                 "evidence_ids": ["ev1", "ev2"], "judged_at": "2026-10-02T00:00:00Z"}
    result = queue.build_queue({"claims": [claim], "sources": [], "evidence": evidence, "judgements": [judgement]})
    assert result[0]["has_inspectable_contradiction"] is True
    assert result[0]["latest_judgement_rationale"] == "The sources conflict on the year."
    assert result[0]["judged_evidence_ids"] == ["ev1", "ev2"]
    assert result[0]["source_ids"] == ["s1", "s2"]


def test_limit_zero_emits_the_full_queue(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(queue, "load_records", lambda records_dir: {
        "claims": [
            {"id": "c1", "event_id": "e", "importance": "core", "status": "unverified",
             "text": "Claim one", "updated_at": "2026-10-01T00:00:00Z", "is_current": True},
            {"id": "c2", "event_id": "e", "importance": "core", "status": "unverified",
             "text": "Claim two", "updated_at": "2026-10-02T00:00:00Z", "is_current": True},
        ], "sources": [], "evidence": [], "judgements": [],
    })
    output = tmp_path / "all.jsonl"
    assert queue.main(["--limit", "0", "--output", str(output)]) == 0
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2
    assert "2 of 2 eligible claim(s)" in capsys.readouterr().err



def test_queue_prioritizes_core_period_and_then_internal_link_count(tmp_path):
    content = tmp_path / "content"
    timeline = content / "01_Timeline"
    timeline.mkdir(parents=True)
    (timeline / "1841-unlinked.md").write_text("---\ntitle: Unlinked 1841\n---\n", encoding="utf-8")
    (timeline / "1842-linked.md").write_text("---\ntitle: Linked 1842\n---\n", encoding="utf-8")
    (timeline / "1830-old.md").write_text("---\ntitle: Old 1830\n---\n", encoding="utf-8")
    (content / "ref-a.md").write_text("[[01_Timeline/1842-linked]] [[01_Timeline/1830-old]]\n", encoding="utf-8")
    (content / "ref-b.md").write_text("[[01_Timeline/1842-linked]] [[01_Timeline/1830-old]]\n", encoding="utf-8")
    (content / "ref-c.md").write_text("[[01_Timeline/1830-old]]\n", encoding="utf-8")
    claims = [
        {"id": "c1841", "event_id": "event:05-opium-war-1841-unlinked", "importance": "core",
         "status": "unverified", "text": "An 1841 claim", "updated_at": "2026-10-01T00:00:00Z",
         "is_current": True, "provenance": {"source_page": "content/01_Timeline/1841-unlinked.md"}},
        {"id": "c1842", "event_id": "event:05-opium-war-1842-linked", "importance": "core",
         "status": "unverified", "text": "An 1842 claim", "updated_at": "2026-10-02T00:00:00Z",
         "is_current": True, "provenance": {"source_page": "content/01_Timeline/1842-linked.md"}},
        {"id": "c1830", "event_id": "event:05-opium-war-1830-old", "importance": "core",
         "status": "unverified", "text": "An 1830 claim", "updated_at": "2026-10-03T00:00:00Z",
         "is_current": True, "provenance": {"source_page": "content/01_Timeline/1830-old.md"}},
    ]
    result = queue.build_queue({"claims": claims, "sources": [], "evidence": [], "judgements": []}, content_root=content)
    assert [row["claim_id"] for row in result] == ["c1842", "c1841", "c1830"]
    assert result[0]["core_period"] is True
    assert result[0]["internal_link_count"] == 2
    assert result[1]["internal_link_count"] == 0
    assert result[2]["core_period"] is False
