import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_snapshot as snap

# Acceptance criterion E3 (after the reviews of run 38180297601): every live page needs a
# retrieval time and a hash of what was fetched. All pages here are synthetic.
PAGE = ("<html><head><style>p{}</style></head><body><p>The harbour office opened on 3&nbsp;March"
        " and the ‘new’ pier‑head was built.</p></body></html>").encode("utf-8")
WAYBACK_REPLY = json.dumps({"archived_snapshots": {"closest": {
    "available": True, "url": "http://web.archive.org/web/2024/https://records.example/a",
    "timestamp": "20240101000000"}}}).encode()


class Response(io.BytesIO):
    def __init__(self, data, url, content_type="text/html; charset=utf-8"):
        super().__init__(data)
        self.status, self.url = 200, url
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener(pages):
    calls = []

    def open_(request, timeout=None):
        url = request.full_url
        calls.append(url)
        if url.startswith(snap.WAYBACK):
            return Response(WAYBACK_REPLY, url, "application/json")
        if url not in pages:
            raise OSError("connection refused")
        return Response(pages[url], url)
    open_.calls = calls
    return open_


def packets(*sources):
    return [("topic.json", {"sources": [
        {"source_id": sid, "url": url, "passage": passage} for sid, url, passage in sources]})]


def test_page_is_hashed_and_passages_are_matched_without_saving_the_page():
    fake = opener({"https://records.example/a": PAGE})
    pages = snap.snapshot_packets(packets(
        ("found", "https://records.example/a", "the 'new' pier-head was built"),
        ("missing", "https://records.example/a", "the pier was demolished")), fake)
    record = pages["https://records.example/a"]
    assert record["status"] == "fetched" and record["http_status"] == 200
    assert record["sha256"] == snap.hashlib.sha256(PAGE).hexdigest() and record["bytes"] == len(PAGE)
    assert record["retrieved_at"].endswith("Z")
    assert [s["passage_found"] for s in record["sources"]] == [True, False]
    assert record["wayback"]["timestamp"] == "20240101000000"
    # One fetch per URL plus one archive lookup, and no page text in the output.
    assert sum(not c.startswith(snap.WAYBACK) for c in fake.calls) == 1
    assert "harbour office" not in json.dumps(pages)


def test_unreachable_page_is_an_access_failure_not_a_crash():
    pages = snap.snapshot_packets(packets(("gone", "https://blocked.example/b", "anything at all here")),
                                  opener({}))
    record = pages["https://blocked.example/b"]
    assert record["status"] == "access_failure" and "connection refused" in record["error"]
    assert record["sources"] == [{"packet": "topic.json", "source_id": "gone", "passage_found": None}]


def test_unreadable_pdf_is_unchecked_not_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)  # as on a runner without pypdf
    assert snap.page_text(b"%PDF-1.4 binary", "application/pdf") is None
    assert snap.passage_found("any passage", None) is None
