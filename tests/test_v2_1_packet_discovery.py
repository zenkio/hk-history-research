from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "v2-1-source-first.yml"


def test_v21_packet_discovery_excludes_manifest_json():
    """A packet directory can contain metadata JSON that is not a source packet."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    discovery_lines = [
        line.strip()
        for line in workflow.splitlines()
        if "mapfile -t packets" in line
    ]

    assert len(discovery_lines) == 1
    assert "-name '*.json'" in discovery_lines[0]
    assert "! -name 'MANIFEST.json'" in discovery_lines[0]


def test_v21_workflow_normalises_integral_number_input_before_bash_arithmetic():
    """GitHub may pass a number input as '4.0'; Bash arithmetic needs an integer."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'raw_max_packets="${MAX_PACKETS:-4}"' in workflow
    assert '[[ "$raw_max_packets" =~ ^([1-4])(\\.0+)?$ ]]' in workflow
    assert 'MAX_PACKETS="${BASH_REMATCH[1]}"' in workflow
    assert "max_packets must be an integer between 1 and 4" in workflow