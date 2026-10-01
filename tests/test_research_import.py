"""Deep Research import. Each test pins a bug found on the live site (see PR numbers)."""
import research_import as ri
import state
from conftest import event_page

EVENTS = [
    {"file": "a/1845-triad.md", "title": "Enactment of the First Ordinance Outlawing Triad Societies", "year": 1845},
    {"file": "a/1844-police.md", "title": "Establishment of the Hong Kong Police Force", "year": 1844},
    {"file": "a/1851-fire.md", "title": "The Great Sheung Wan Fire", "year": 1851},
]


def row(event, date, a="", b="", c=""):
    return {"#": "1", "event": event, "date (yyyy or yyyy-mm-dd)": date, "what happened (one sentence)": "x",
            "grade a source": a, "grade b source": b, "grade c source": c, "disputes or myths": "none"}


# --- matching (PR #10) ------------------------------------------------------

def test_generic_words_alone_do_not_match():
    # "Enactment ... Ordinance" is shared with the triad page, but it is a different law.
    assert ri.match_page(row("Enactment and Disallowance of the Slavery Ordinance", "1844"), EVENTS) is None


def test_distinctive_word_and_year_match():
    got = ri.match_page(row("Formal Establishment of the Hong Kong Police Force", "1844-05-01"), EVENTS)
    assert got["file"] == "a/1844-police.md"


def test_year_more_than_one_off_does_not_match():
    assert ri.match_page(row("The Great Fire of Sheung Wan", "1855"), EVENTS) is None


# --- reference checks (PR #9) -------------------------------------------------

def test_homepage_link_is_never_verified(monkeypatch):
    monkeypatch.setattr(ri, "link_ok", lambda u: True)
    checks = ri.check_cell("See https://www.hsbc.com and https://www.pro.gov.hk/", {})
    assert [(k, ok) for k, _, ok, _ in checks] == [("site", None), ("site", None)]


def test_wikipedia_link_is_never_evidence(monkeypatch):
    monkeypatch.setattr(ri, "link_ok", lambda u: True)
    (kind, _, ok, _), = ri.check_cell("https://en.wikipedia.org/wiki/Hong_Kong", {})
    assert (kind, ok) == ("wiki", None)


def test_cite_numbers_resolve_through_google_redirects(monkeypatch):
    monkeypatch.setattr(ri, "link_ok", lambda u: True)
    text = "1. Some record, [https://www.google.com/url?sa=E&amp;q=https%3A%2F%2Fdiscovery.nationalarchives.gov.uk%2Fdetails%2Fr%2FC1]"
    refs = ri.reference_list(text)
    checks = ri.check_cell("CO 129/1 [cite: 1]", refs)
    assert ("link", "https://discovery.nationalarchives.gov.uk/details/r/C1", True, "") in checks


def test_doi_must_match_the_cited_title(monkeypatch):
    monkeypatch.setattr(ri, "_json", lambda url: {"message": {"title": ["Something Else Entirely"]}})
    ok, note = ri.check_doi("10.1/x", "Fairbank, Trade and Diplomacy on the China Coast")
    assert ok is False and "Something Else" in note


# --- grading (PR #9) -----------------------------------------------------------

def test_grade_comes_from_what_the_link_is_not_its_column():
    blog = [("Grade A", "cell", [("link", "https://zolimacitymag.com/x", True, "")])]
    archive = [("Grade C", "cell", [("link", "https://discovery.nationalarchives.gov.uk/details/r/1", True, "")])]
    book = [("Grade A", "cell", [("ISBN", "https://openlibrary.org/isbn/1", True, "")])]
    assert ri.row_grade(blog) is None
    assert ri.row_grade(archive) == "A"
    assert ri.row_grade(book) == "B"


def test_normal_import_never_lowers_a_grade(timeline):
    p = timeline / "p.md"
    p.write_text(event_page("P", grade="A"), encoding="utf-8")
    assert ri.attach(str(p), "## Research notes\n\nx\n\n", "B") == "A"
    assert "evidence_grade: A" in p.read_text()


def test_regrade_can_lower_and_tags_follow(timeline):
    p = timeline / "p.md"
    p.write_text(event_page("P", grade="A").replace('tags: ["ai-draft"]', 'tags: ["evidence-a", "ai-draft"]'))
    assert ri.attach(str(p), "", None, regrade=True) == "none"
    text = p.read_text()
    assert "evidence_grade: none" in text and '"evidence-none"' in text and '"evidence-a"' not in text


# --- whole import (integration) -----------------------------------------------

INBOX_FILE = """Intro.

| # | Event | Date (YYYY or YYYY-MM-DD) | What happened (one sentence) | Grade A source | Grade B source | Grade C source | Disputes or myths |
|---|---|---|---|---|---|---|---|
| 1 | Formal Establishment of the Hong Kong Police Force | 1844-05-01 | Police set up. | Gazette [cite: 1] | none found | none found | none |
| 2 | Enactment and Disallowance of the Slavery Ordinance | 1844 | Law. | https://www.pro.gov.hk | none found | none found | none |
| 3 | The Great Fire of Sheung Wan | 1851 | Fire. | none found | Book, ISBN 9789622099289 | none found | none |

1. Gazette 1844, [https://digitalrepository.lib.hku.hk/catalog/abc]
"""


def test_import_inbox_attaches_grades_and_moves_file(tmp_path, monkeypatch, write_page):
    for ev in EVENTS:
        write_page(ev["file"], ev["title"], ev["year"])
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "01-test.md").write_text(INBOX_FILE, encoding="utf-8")
    monkeypatch.setattr(ri, "INBOX", str(inbox))
    monkeypatch.setattr(ri, "UNMATCHED", str(tmp_path / "unmatched.md"))
    monkeypatch.setattr(ri, "link_ok", lambda u: True)
    monkeypatch.setattr(ri, "check_isbn", lambda i, c: (True, "ISBN is: Book"))
    state.save("research", {"grading_version": ri.GRADING_VERSION})  # skip the one-time regrade

    grades = {}
    ri.import_inbox(EVENTS, grades)

    assert grades == {"a/1844-police.md": "A", "a/1851-fire.md": "B"}
    assert "## Research notes" not in (tmp_path / "01_Timeline/a/1845-triad.md").read_text()
    assert "Slavery Ordinance" in (tmp_path / "unmatched.md").read_text()
    assert (inbox / "done" / "01-test.md").exists() and not (inbox / "01-test.md").exists()


def test_regrade_removes_notes_a_looser_matcher_put_on_the_wrong_page(tmp_path, monkeypatch, write_page):
    # PR #11: run 14 attached the Slavery Ordinance row to the triad page.
    for ev in EVENTS:
        write_page(ev["file"], ev["title"], ev["year"])
    triad = tmp_path / "01_Timeline/a/1845-triad.md"
    ri.attach(str(triad), "## Research notes\n\n> [!note] From Gemini Deep Research (01-test.md), x\n\n", "A")
    inbox = tmp_path / "inbox"
    (inbox / "done").mkdir(parents=True)
    (inbox / "done" / "01-test.md").write_text(INBOX_FILE, encoding="utf-8")
    monkeypatch.setattr(ri, "INBOX", str(inbox))
    monkeypatch.setattr(ri, "link_ok", lambda u: True)
    monkeypatch.setattr(ri, "check_isbn", lambda i, c: (True, "ISBN is: Book"))

    grades = {}
    ri.import_inbox(EVENTS, grades)

    text = triad.read_text()
    assert "## Research notes" not in text and "evidence_grade: none" in text
    assert state.load("research")["grading_version"] == ri.GRADING_VERSION


# --- saving imports (PR #9) ---------------------------------------------------------------------
# Drafting was finished, so seed_history never committed: every run since 2026-09-30 imported the
# inbox again and threw the result away. And a prose file with no table would have vanished into done/.

TABLE = ("| # | Event | Date (YYYY or YYYY-MM-DD) | What happened (one sentence) | Grade A source |\n"
         "|---|---|---|---|---|\n| 1 | Opening of a ferry pier | 1999 | x | none |\n")


def test_prose_file_without_a_table_stays_in_the_inbox(tmp_path, monkeypatch, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(ri, "INBOX", str(inbox))
    monkeypatch.setattr(ri, "UNMATCHED", str(tmp_path / "unmatched.md"))
    (inbox / "prose.md").write_text("An essay about the period, with sources but no table.", encoding="utf-8")
    (inbox / "table.md").write_text(TABLE, encoding="utf-8")
    ri.import_inbox(EVENTS, {})
    assert (inbox / "prose.md").exists(), "nothing could be imported, so it must not disappear"
    assert (inbox / "done" / "table.md").exists() and not (inbox / "table.md").exists()
    assert "prose.md: no table with an Event column found; left in the inbox" in capsys.readouterr().out


def test_seeding_commits_even_when_no_page_was_drafted(monkeypatch):
    import seed_history
    commits = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(seed_history, "run", lambda *a, **k: 0)  # drafting finished: 0 tasks
    monkeypatch.setattr(seed_history, "git_commit", lambda: commits.append(1))
    seed_history.main(["--minutes", "1"])
    assert commits == [1], "imports and evidence from the workers must be saved"
    seed_history.main(["--minutes", "1", "--no-commit"])
    assert commits == [1]
