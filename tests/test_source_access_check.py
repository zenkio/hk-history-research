import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_access_check as sac


class Resp:
    def __init__(self, body, status=200, ctype="text/html; charset=utf-8"):
        self.body, self.status = body.encode(), status
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body

    def geturl(self):
        return "https://example.org/final"


def opener_for(pages):
    def opener(request, timeout=0):
        url = request.full_url
        if "archive.org/wayback/available" in url:
            return Resp(json.dumps({"archived_snapshots": {}}), ctype="application/json")
        page = pages[url.split("?")[0]] if url.split("?")[0] in pages else pages["default"]
        if isinstance(page, int):
            raise urllib.error.HTTPError(url, page, "x", {}, None)
        return Resp(page)
    return opener


def test_a_long_open_page_is_reachable_and_rights_wording_is_noted():
    body = "<p>" + "Hong Kong Government Gazette index. " * 200 + " Copyright reserved. Sign in</p>"
    records, blocked = sac.run([{"id": "a", "name": "A", "url": "https://example.org/a"}], opener_for({"default": body}))
    assert records[0]["state"] == "reachable" and records[0]["rights_wording_found"] and not blocked


def test_a_short_login_page_and_http_errors_go_to_the_blocked_list():
    pages = {"https://x/login": "<p>Please sign in to continue</p>", "https://x/paid": 402,
             "https://x/gone": 404, "https://x/forbidden": 403}
    cands = [{"id": k, "name": k, "url": u, "for": "gazette 1955"} for k, u in
             (("login", "https://x/login"), ("paid", "https://x/paid"), ("gone", "https://x/gone"),
              ("forbidden", "https://x/forbidden"))]
    records, blocked = sac.run(cands, opener_for({**pages, "default": ""}))
    assert {r["id"]: r["state"] for r in records} == {"login": "login_or_paywall", "paid": "login_or_paywall",
                                                      "gone": "not_found", "forbidden": "forbidden"}
    assert len(blocked) == 4 and all(b["wanted_for"] == "gazette 1955" and b["needs"] for b in blocked)


def test_candidates_without_a_url_are_skipped(tmp_path):
    cands = tmp_path / "c.json"
    cands.write_text(json.dumps({"candidates": [{"id": "n", "name": "no url"}]}), encoding="utf-8")
    records, blocked = sac.run(json.loads(cands.read_text())["candidates"], opener_for({"default": ""}))
    assert records == [] and blocked == []
