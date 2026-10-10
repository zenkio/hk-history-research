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


def test_probe_accepts_expected_html_catalogue_page():
    spec = {"format": "html", "shape": "Search Results"}
    ok, detail = probe.inspect_response(
        spec, 200, "text/html; charset=utf-8",
        b"<html><body><h1>Search Results</h1></body></html>",
    )
    assert ok
    assert "200" in detail


def test_probe_rejects_html_without_expected_catalogue_marker():
    spec = {"format": "html", "shape": "Search Results"}
    ok, detail = probe.inspect_response(
        spec, 200, "text/html",
        b"<html><body>Service unavailable</body></html>",
    )
    assert not ok
    assert "unexpected HTML response shape" in detail


def test_bounded_probe_accepts_large_html_when_marker_is_in_sample():
    spec = {"format": "html", "shape": "Search Results"}
    body = b"<html><body>Search Results</body></html>" + b"x" * probe.MAX_BYTES
    ok, detail = probe.inspect_bounded_response(spec, 200, "text/html", body)
    assert ok
    assert "inspected first" in detail


def test_bounded_probe_still_rejects_oversized_json():
    spec = {"format": "json", "shape": "records"}
    body = b'{"records": []}' + b" " * probe.MAX_BYTES
    ok, detail = probe.inspect_bounded_response(spec, 200, "application/json", body)
    assert not ok
    assert "safety limit" in detail
