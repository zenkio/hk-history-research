import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evidence


def test_judge_prompt_prioritises_passages_over_metadata():
    prompt = evidence.JUDGE_PROMPT
    assert "Use the passage field as the deciding evidence" in prompt
    assert "matching title or catalogue entry alone is not enough" in prompt
    assert "Never infer the contents of an archive record from its catalogue description or title." in prompt
