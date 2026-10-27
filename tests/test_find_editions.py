import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import find_editions as fe


class Resp:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body

    def geturl(self):
        return "u"


def opener(docs):
    return lambda request, timeout=0: Resp({"response": {"docs": docs}})


SPEC = {"id": "gov", "name": "Gov Yearbook", "query": 'title:("hong kong" AND yearbook)', "first_year": 1950, "last_year": 1953,
        "for": "gov yearbook"}


def test_hits_are_listed_and_missing_years_go_to_the_blocked_list():
    docs = [{"identifier": "hk1951", "title": "HK Yearbook 1951", "year": "1951", "mediatype": "texts"},
            {"identifier": "hk1953", "title": "HK Yearbook 1953", "year": 1953, "licenseurl": "https://x/l"}]
    results, blocked = fe.run([SPEC], opener(docs))
    assert [i["identifier"] for i in results[0]["items"]] == ["hk1951", "hk1953"]
    assert results[0]["years_missing"] == ["1950", "1952"]
    assert "1950, 1952" in blocked[0]["why_blocked"] and blocked[0]["wanted_for"] == "gov yearbook"


def test_a_complete_run_has_nothing_blocked():
    docs = [{"identifier": f"hk{y}", "title": "t", "year": str(y)} for y in range(1950, 1954)]
    assert fe.run([SPEC], opener(docs))[1] == []


def test_a_failed_search_is_reported_not_raised():
    def broken(request, timeout=0):
        raise ValueError("boom")
    results, blocked = fe.run([SPEC], broken)
    assert results[0]["error"].startswith("ValueError") and blocked and blocked[0]["why_blocked"].startswith("ValueError")


def test_the_search_url_carries_the_query_and_year_range():
    url = fe.search_url("title:x", 1950, 1970)
    assert "year%3A%5B1950+TO+1970%5D" in url and "fl%5B%5D=licenseurl" in url
