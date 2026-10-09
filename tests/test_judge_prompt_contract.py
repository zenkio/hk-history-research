import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evidence


def test_judge_prompt_prioritises_passages_over_metadata():
    prompt = evidence.JUDGE_PROMPT
    assert "Use the passage field as the deciding evidence" in prompt
    assert "matching title or catalogue entry alone is not enough" in prompt
    assert "Never infer the contents of an archive record from its catalogue description or title." in prompt


def test_prompt_version_change_reopens_previous_evidence_judgements():
    page = "# Example\n\n## Evidence\nOld judgement based on metadata.\n"
    assert evidence.JUDGE_VERSION == 7
    assert evidence._to_rejudge(6, "A", page, "06-early-colony/example.md")
    assert evidence._to_rejudge(6, "none", page, "06-early-colony/example.md")
