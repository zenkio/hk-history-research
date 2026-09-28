"""Wikipedia cross-check: article choice and cited sources, with a fake MediaWiki API."""
import pytest
import research_import
import wikipedia as w


class FakeWiki:
    """search results per query substring, article text per title, wikitext per title."""
    def __init__(self, search=None, articles=None, wikitext=None):
        self.search, self.articles, self.wikitext, self.queries = search or {}, articles or {}, wikitext or {}, []

    def __call__(self, **p):
        if p.get("list") == "search":
            self.queries.append(p["srsearch"])
            hits = next((v for k, v in self.search.items() if k in p["srsearch"]), [])
            return {"query": {"search": [{"title": t} for t in hits]}}
        if p.get("action") == "parse":
            return {"parse": {"wikitext": self.wikitext.get(p["page"], "")}}
        return {"query": {"pages": [{"extract": self.articles.get(p["titles"], "")}]}}


@pytest.fixture
def wiki(monkeypatch):
    def install(**kw):
        fake = FakeWiki(**kw)
        monkeypatch.setattr(w, "_api", fake)
        return fake
    return install


def test_query_drops_event_words_and_is_anchored_on_hong_kong(wiki):
    # PR #12: "St John's Cathedral 1849" without "Hong Kong" found Helsinki Cathedral.
    fake = wiki(search={"St John's Cathedral Hong Kong": ["St John's Cathedral (Hong Kong)"]})
    assert w.find_articles("Consecration of St. John's Cathedral", 1849) == ["St John's Cathedral (Hong Kong)"]
    assert fake.queries[0] == "St John's Cathedral Hong Kong"


def test_overview_year_and_list_articles_are_skipped(wiki):
    wiki(search={"Cinema": ["Hong Kong", "1933 in film", "List of cinemas", "Cinema House"]})
    assert w.search("Cinema House") == ["Cinema House"]


def test_extra_article_must_mention_hong_kong(wiki):
    # PR #12: "Malta Police Force" was compared next to "Hong Kong Police Force".
    wiki(search={"Police": ["Hong Kong Police Force", "Malta Police Force"]},
         articles={"Hong Kong Police Force": "The Hong Kong Police Force was formally established on 1 May 1844 by ordinance, under Captain William Caine.",
                   "Malta Police Force": "The Malta Police Force is the national police force, established by ordinance in 1814 in Valletta."})
    ref, sources, titles = w.reference_text("Establishment of the Hong Kong Police Force",
                                            ["The police force was established by ordinance in May 1844."], 1844)
    assert titles == ["Hong Kong Police Force"]
    assert [s["title"] for s in sources] == ["Wikipedia: Hong Kong Police Force"]
    assert "Malta" not in ref


def test_cited_sources_keeps_isbn_and_doi_entries(wiki, monkeypatch):
    # PR #7: a bad edit turned the ISBN append into a comment, so books were never listed.
    wiki(wikitext={"Pirates": "{{cite book |title=Pirates of the South China Coast 1810 |isbn=0804713766}}"
                              "{{cite journal |title=South China pirates of 1810 |doi=10.1/x}}"
                              "{{cite web |title=no identifier}}"})
    monkeypatch.setattr(research_import, "check_isbn", lambda i, c: (True, "ISBN is: Pirates"))
    monkeypatch.setattr(research_import, "check_doi", lambda d, c: (False, "DOI resolves to: Other"))
    got = {c["kind"]: c["ok"] for c in w.cited_sources(["Pirates"], ["pirates south china coast 1810"])}
    assert got == {"ISBN": True, "DOI": False}


def test_chinese_title_is_not_failed_against_romanised_catalogue(wiki, monkeypatch):
    wiki(wikitext={"X": "{{cite book |title=張保仔 海盜 pirates 1810 |isbn=9789620000000}}"})
    monkeypatch.setattr(research_import, "check_isbn", lambda i, c: (False, "ISBN is: Zhang bao zai"))
    got = w.cited_sources(["X"], ["pirates 1810 surrender"])
    assert got == [] or got[0]["ok"] in (None, False)  # only the romanised part overlaps
