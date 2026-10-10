import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import uk_legislation as uk


SEARCH_HTML = """<html><body>
<nav>Site navigation must not become evidence.</nav>
<a href="/ukpga/1981/61">British Nationality Act 1981</a>
<a href="/ukpga/1990/34">British Nationality (Hong Kong) Act 1990</a>
<a href="https://example.org/not-a-law">British Nationality (Hong Kong) Act 1990</a>
</body></html>"""
ACT_HTML = """<html><body>
<nav>Search Help Home</nav>
<div id="viewLegContents">
<h1>British Nationality (Hong Kong) Act 1990</h1>
<p>[26th July 1990] An Act to provide for the acquisition of British citizenship by selected Hong Kong residents, their spouses and minor children.</p>
<p>The Secretary of State shall register as British citizens up to 50,000 persons recommended by the Governor of Hong Kong.</p>
</div>
</body></html>"""


def test_irrelevant_queries_do_not_make_network_requests(monkeypatch):
    monkeypatch.setattr(uk, "_fetch_html", lambda url: (_ for _ in ()).throw(AssertionError("network call")))
    assert uk.search("Shek Kip Mei fire") == []
    assert uk.search("Hong Kong") == []


def test_search_returns_official_inspectable_text_and_ignores_external_links(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if "/search?" in url:
            return SEARCH_HTML
        if url.endswith("/ukpga/1990/34"):
            return ACT_HTML
        if url.endswith("/ukpga/1981/61"):
            return "<html><div id='viewLegContents'>An unrelated short text.</div></html>"
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(uk, "_fetch_html", fake_fetch)
    results = uk.search("British Nationality Act 1990")
    assert len(results) == 1
    row = results[0]
    assert row["title"] == "British Nationality (Hong Kong) Act 1990"
    assert row["year"] == "1990"
    assert row["url"] == "https://www.legislation.gov.uk/ukpga/1990/34"
    assert row["passage_status"] == "inspectable_text"
    assert "up to 50,000 persons" in row["passage"]
    assert "Site navigation" not in row["passage"]
    assert row["rights_status"] == "open_government_licence"
    assert calls == [
        "https://www.legislation.gov.uk/search?title=British+Nationality+Act+1990",
        "https://www.legislation.gov.uk/ukpga/1990/34",
    ]


def test_search_keeps_short_or_unreadable_result_metadata_only(monkeypatch):
    monkeypatch.setattr(
        uk,
        "_fetch_html",
        lambda url: SEARCH_HTML if "/search?" in url else "<html><div id='viewLegContents'>Short</div></html>",
    )
    row = uk.search("British Nationality Act 1990")[0]
    assert row["passage_status"] == "metadata_only"
    assert row["passage"] == ""
    assert row["rights_status"] == "not_verified"


def test_query_url_host_validation_and_five_second_pacing(monkeypatch):
    sleeps = []
    monkeypatch.setattr(uk, "_last_request_at", 8.0)
    monkeypatch.setattr(uk.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(uk.time, "sleep", sleeps.append)
    uk._pace_request()
    assert sleeps == [3.0]
    try:
        uk._fetch_html("https://example.org/not-allowed")
    except ValueError as exc:
        assert "Only HTTPS URLs" in str(exc)
    else:
        raise AssertionError("non-official host must be rejected")
