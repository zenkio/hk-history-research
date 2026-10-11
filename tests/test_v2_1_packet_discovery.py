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
