import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_source_connectivity as probe


def test_probe_validates_expected_json_shape():
    spec = {"format": "json", "shape": "records"}
    ok, detail = probe.inspect_response(spec, 200, "application/json", b'{"Records": []}')
    assert ok
    assert "200" in detail


def test_probe_rejects_html_error_page_with_http_200():
    spec = {"format": "json", "shape": "records"}
    ok, detail = probe.inspect_response(spec, 200, "text/html", b"<html>service unavailable</html>")
    assert not ok
    assert "invalid JSON" in detail


def test_probe_rejects_wrong_xml_root():
    spec = {"format": "xml", "shape": "OAI-PMH"}
    ok, detail = probe.inspect_response(spec, 200, "application/xml", b"<Error>not an OAI response</Error>")
    assert not ok
    assert "unexpected XML response shape" in detail


def test_strict_connectivity_mode_only_fails_required_endpoints(monkeypatch):
    monkeypatch.setattr(probe, "PROBES", [
        {"name": "optional", "required": False},
        {"name": "required", "required": True},
    ])
    monkeypatch.setattr(probe, "probe", lambda item, timeout=15: (item["name"] == "required", "mock result"))
    assert probe.main(["--strict"]) == 0
    monkeypatch.setattr(probe, "probe", lambda item, timeout=15: (False, "mock failure"))
    assert probe.main(["--strict"]) == 1
