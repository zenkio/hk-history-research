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


def test_mmis_probe_uses_official_https_homepage_as_optional():
    spec = next(item for item in probe.PROBES if item["name"] == "Hong Kong Public Libraries MMIS legacy hostname")
    assert spec["required"] is False
    assert spec["url"] == "https://mmis.hkpl.gov.hk/"
    assert spec["format"] == "html"



def test_grs_live_probe_reports_metadata_only_record_link_count(monkeypatch):
    spec = next(item for item in probe.PROBES if item["name"] == "Hong Kong Government Records Service catalogue")
    monkeypatch.setattr(
        probe,
        "parse_grs_catalogue_results",
        lambda html, query: [{"passage_status": "metadata_only"}],
    )

    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit):
            return b"<html><body>Search Results</body></html>"

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    ok, detail = probe.probe(spec)
    assert ok
    assert "parser found 1 metadata-only record link" in detail


def test_grs_live_probe_warns_when_parser_finds_no_record_links(monkeypatch):
    spec = next(item for item in probe.PROBES if item["name"] == "Hong Kong Government Records Service catalogue")
    monkeypatch.setattr(probe, "parse_grs_catalogue_results", lambda html, query: [])

    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit):
            return b"<html><body>Search Results</body></html>"

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    ok, detail = probe.probe(spec)
    assert not ok
    assert "parser found 0 metadata-only record links" in detail



def test_current_hkpl_and_hku_repository_probes_are_optional_https():
    expected = {
        "HKPL Digital Collection (current MMIS successor)": "https://sls.hkpl.gov.hk/digital-collection/en/",
        "HKU Scholars Hub OAI-PMH": "https://hub.hku.hk/oai/request?verb=Identify",
    }
    by_name = {item["name"]: item for item in probe.PROBES}
    for name, url in expected.items():
        assert name in by_name
        assert by_name[name]["url"] == url
        assert by_name[name]["required"] is False
        assert url.startswith("https://")



def test_legco_bills_api_and_hansard_docs_are_optional_https_probes():
    expected = {
        "LegCo Bills open data (bills since 1844)": "https://app.legco.gov.hk/BillsDB/odata/Vbills?$top=1&$format=json",
        "LegCo Hansard API documentation": "https://www.legco.gov.hk/en/open-legco/open-data/hansard-database.html",
    }
    by_name = {item["name"]: item for item in probe.PROBES}
    for name, url in expected.items():
        assert by_name[name]["url"] == url
        assert by_name[name]["required"] is False
        assert url.startswith("https://")
