"""Evidence engine with fake archive/scholarship sources and a fake AI judge."""
import time

import pytest
import evidence as ev
import state

A_RECORD = {"kind": "archive record", "grade": "A", "year": 1900, "title": "CO 129 Treaty file",
            "url": "https://discovery.nationalarchives.gov.uk/details/r/1", "cite": "CO 129/1", "note": "n",
            "passage": "The treaty was signed in Hong Kong in 1849.", "passage_status": "inspectable_record"}


class Judge:
    """Keeps the first candidate, like a model that finds it relevant."""
    def __init__(self):
        self.calls = 0

    def generate_json(self, role, prompt, **k):
        self.calls += 1
        return {"relevant": [{"id": "c1", "relation": "supports", "claims": [1], "why": "about this"}]}, "gemma", []


def fail(q):
    raise Exception("HTTP Error 429: Too Many Requests")


@pytest.fixture(autouse=True)
def fresh_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "_source_fails", {})
    monkeypatch.setattr(ev, "AUDIT_SHARE", 0)  # the audit test turns it on
    monkeypatch.setattr(ev, "RESEARCH_RECORDS_DIR", str(tmp_path / "research-records"))


def batch(pages, sources, monkeypatch, done=None):
    monkeypatch.setattr(ev, "SOURCES", sources)
    done = {} if done is None else done
    events = [{"file": f, "status": "done"} for f in pages]
    ev.evidence_batch(Judge(), done, events, time.time() + 60, limit=50)
    return done



def test_legacy_error_marker_is_reopened_for_retry(write_page, monkeypatch):
    write_page("pending.md", "Example event")
    monkeypatch.setattr(ev, "evidence_for_page", lambda *args, **kwargs: "B")
    done = {"pending.md": "error"}
    result = ev.evidence_batch(
        Judge(), done, [{"file": "pending.md", "status": "done"}],
        time.time() + 10, limit=1,
    )
    assert result == 1
    assert done == {"pending.md": "B"}


def test_page_with_no_results_while_a_source_is_down_remains_pending(write_page, monkeypatch, capsys):
    # Incomplete retrieval stays retryable without failing the entire scheduled run.
    write_page("p.md", "Plague outbreak")
    done = {}
    batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [])], monkeypatch, done)
    assert done == {}
    assert "remain pending" in capsys.readouterr().out


def test_evidence_found_elsewhere_is_kept_while_a_source_is_down(write_page, monkeypatch, timeline):
    write_page("p.md", "Treaty signing")
    done = batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [A_RECORD])], monkeypatch)
    assert done == {"p.md": "A"}
    assert "evidence_grade: A" in (timeline / "p.md").read_text()


def test_all_sources_answering_with_nothing_is_recorded_none(write_page, monkeypatch):
    write_page("p.md", "Plague outbreak")
    assert batch(["p.md"], [("OpenAlex", lambda q: []), ("National Archives", lambda q: [])], monkeypatch) == {"p.md": "none"}


def test_failing_source_is_rested_after_three_failures(write_page, monkeypatch, capsys):
    calls = []

    def counting_fail(q):
        calls.append(q)
        fail(q)
    for i in range(5):
        write_page(f"p{i}.md", f"Harbour event {'abcde'[i]}")
    done = batch([f"p{i}.md" for i in range(5)], [("OpenAlex", counting_fail), ("National Archives", lambda q: [])], monkeypatch)
    assert len(calls) == ev.SOURCE_FAILS_TO_REST
    assert len(done) == 0
    assert "remain pending" in capsys.readouterr().out


def test_old_none_results_are_searched_again_once():
    done = {"a.md": "none", "b.md": "B", "c.md": "A"}
    assert ev.reopen_unsearched(done) == 1
    assert done == {"b.md": "B", "c.md": "A"}
    done["a.md"] = "none"
    assert ev.reopen_unsearched(done) == 0  # only once per SEARCH_VERSION
    assert state.load("evidence_meta")["search_version"] == ev.SEARCH_VERSION


def test_openalex_sends_the_api_key_when_set(monkeypatch):
    # Since Feb 2026 OpenAlex gives 100 credits a day without a key (10 searches): run 27's 429s.
    seen = []
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: seen.append(url) or {"results": []})
    monkeypatch.setenv("OPENALEX_API_KEY", " key123\n")
    ev.openalex("Tung Wah")
    monkeypatch.delenv("OPENALEX_API_KEY")
    ev.openalex("Tung Wah")
    assert "api_key=key123" in seen[0] and "api_key" not in seen[1]


def test_descriptive_words_are_dropped_from_the_search():
    # Run 31 (after PR #19): "Disastrous Shek Kip Mei Fire" found no evidence for the 1953 fire.
    assert ev.keywords("The Disastrous Shek Kip Mei Fire") == "Shek Kip Mei Fire"
    assert ev.keywords("Establishment of the Hong Kong Housing Authority") == "Housing Authority"
    assert ev.keywords("Japanese Invasion of Hong Kong Begins") == "Japanese Invasion"


def test_log_shows_what_each_source_returned_and_what_the_ai_kept(write_page, monkeypatch, capsys):
    # Run 31 graded 42 of 50 pages "none" and the log could not say whether search or AI found nothing.
    write_page("p.md", "Treaty signing")
    batch(["p.md"], [("OpenAlex", fail), ("National Archives", lambda q: [dict(A_RECORD)]),
                     ("Internet Archive", lambda q: [])], monkeypatch)
    out = capsys.readouterr().out
    assert '"Treaty; claim about event": OpenAlex failed, National Archives 1, Internet Archive 0; AI kept 1' in out


def test_log_line_for_a_search_that_found_nothing(write_page, monkeypatch, capsys):
    write_page("p.md", "Plague outbreak")
    batch(["p.md"], [("OpenAlex", lambda q: []), ("National Archives", lambda q: [])], monkeypatch)
    assert '"Plague; claim about event": OpenAlex 0, National Archives 0; nothing to judge' in capsys.readouterr().out


# --- stricter judging (2026-09-28 audit: general-topic works were graded as evidence) ---------

B_PAPER = {"kind": "scholarship", "grade": "B", "year": 2009, "title": "Chinese ancestor worship in general",
           "url": "https://doi.org/10.1/x", "cite": "Lakos (2009)", "note": "n",
           "passage": "This study examines the founding and history of the institution in Hong Kong.",
           "passage_status": "inspectable_abstract"}


class SaysJudge:
    """Answers with the given `relevant` list; a second, different model can answer differently."""
    def __init__(self, relevant, second=None, second_model="nemotron-super"):
        self.relevant, self.second, self.second_model, self.calls = relevant, second, second_model, []
        self.routing = {"evidence": ["nemotron-ultra", "nemotron-super", "gemma"]}

    def generate_json(self, role, prompt, only=None, **k):
        self.calls.append(only)
        if only is not None:
            return {"relevant": self.second or []}, self.second_model, []
        return {"relevant": self.relevant, "missing": ""}, "nemotron-ultra", []


def judge_page(write_page, monkeypatch, timeline, relevant, sources, **kw):
    write_page("p.md", "Consecration of St John's Cathedral", 1849)
    monkeypatch.setattr(ev, "SOURCES", sources)
    pool = SaysJudge(relevant, **kw)
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    return done, (timeline / "p.md").read_text(encoding="utf-8"), pool


def test_background_reading_is_listed_but_earns_no_grade(write_page, monkeypatch, timeline):
    done, text, pool = judge_page(write_page, monkeypatch, timeline,
                                  [{"id": "c1", "relation": "background", "claims": [], "why": "general topic"}],
                                  [("OpenAlex", lambda q: [dict(B_PAPER)])])
    assert done == {"p.md": "none"} and "evidence_grade: none" in text
    assert len(pool.calls) == 1, "one AI call per page"
    assert "### Background reading (does not count towards coverage)" in text and "Lakos (2009)" in text



def test_evidence_section_labels_grade_as_coverage_not_verification(write_page, monkeypatch, timeline):
    done, text, _ = judge_page(
        write_page, monkeypatch, timeline,
        [{"id": "c1", "relation": "supports", "claims": [1], "why": "passage directly supports"}],
        [("National Archives", lambda q: [dict(A_RECORD)])],
    )
    assert done == {"p.md": "A"}
    assert "Evidence coverage: **A** (not a verification verdict)" in text
    assert "source coverage, not a verification verdict" in text
    assert "Evidence grade:" not in text


def test_supports_without_a_claim_counts_as_background(write_page, monkeypatch, timeline):
    done, _, _ = judge_page(write_page, monkeypatch, timeline,
                            [{"id": "c1", "relation": "supports", "claims": [], "why": "vague"}],
                            [("OpenAlex", lambda q: [dict(B_PAPER)])])
    assert done == {"p.md": "none"}


def test_a_contradicting_record_does_not_raise_the_grade_and_is_shown_separately(write_page, monkeypatch, timeline):
    done, text, _ = judge_page(write_page, monkeypatch, timeline,
                               [{"id": "c1", "relation": "contradicts", "claims": [1], "why": "dated 1850"}],
                               [("National Archives", lambda q: [dict(A_RECORD)])])
    assert done == {"p.md": "none"}
    assert "evidence_grade: none" in text
    assert "### Contradictory evidence (does not count as support)" in text
    assert "⚠ contradicts claim 1" in text and '"evidence-contradicts"' in text


def test_supporting_record_still_earns_grade(write_page, monkeypatch, timeline):
    done, text, _ = judge_page(write_page, monkeypatch, timeline,
                               [{"id": "c1", "relation": "supports", "claims": [1], "why": "dated 1849"}],
                               [("National Archives", lambda q: [dict(A_RECORD)])])
    assert done == {"p.md": "A"}
    assert "supports claim 1" in text


def test_complete_empty_search_downgrades_stale_grade_and_records_history(write_page, monkeypatch, timeline):
    import state
    write_page("p.md", "Consecration of St John's Cathedral", 1849, grade="A")
    monkeypatch.setattr(ev, "SOURCES", [
        ("National Archives", lambda q: []),
        ("OpenAlex", lambda q: []),
    ])

    done = {}
    ev.evidence_batch(
        Judge(), done, [{"file": "p.md", "status": "done"}],
        time.time() + 60, limit=5,
    )

    assert done == {"p.md": "none"}
    assert "evidence_grade: none" in (timeline / "p.md").read_text(encoding="utf-8")
    changes = state.load("evidence_meta")["grade_changes"]
    assert changes[-1]["from"] == "A" and changes[-1]["to"] == "none"
    assert changes[-1]["contradiction_found"] is False


def test_new_judgement_can_downgrade_a_stale_grade_and_records_history(write_page, monkeypatch, timeline):
    import state
    write_page("p.md", "Consecration of St John's Cathedral", 1849, grade="A")
    monkeypatch.setattr(ev, "SOURCES", [("OpenAlex", lambda q: [dict(B_PAPER)])])
    pool = SaysJudge([{"id": "c1", "relation": "supports", "claims": [1], "why": "specific study"}])
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert done == {"p.md": "B"}
    assert "evidence_grade: B" in (timeline / "p.md").read_text(encoding="utf-8")
    changes = state.load("evidence_meta")["grade_changes"]
    assert changes[-1]["from"] == "A" and changes[-1]["to"] == "B"
    assert changes[-1]["contradiction_found"] is False


def test_graded_pages_are_judged_again_once_but_research_graded_pages_are_not(write_page, timeline):
    engine = write_page("engine.md", "Treaty signing", extra="\n## Evidence\n\nold judgement\n")
    write_page("research.md", "Police founding", extra="\n## Evidence\n\nx\n\n## Research notes\n\ny\n")
    done = {"engine.md": "B", "research.md": "A", "none.md": "none", "gone.md": "A"}
    assert ev.reopen_for_rejudge(done) == 1
    assert done == {"research.md": "A", "none.md": "none", "gone.md": "A"}
    done["engine.md"] = "B"
    assert ev.reopen_for_rejudge(done) == 0  # only once per JUDGE_VERSION
    assert engine.exists()


def test_audit_asks_a_different_model_and_records_agreement(write_page, monkeypatch, timeline):
    monkeypatch.setattr(ev, "AUDIT_SHARE", 1)
    _, _, pool = judge_page(write_page, monkeypatch, timeline,
                            [{"id": "c1", "relation": "supports", "claims": [1], "why": "x"}],
                            [("OpenAlex", lambda q: [dict(B_PAPER), dict(B_PAPER, url="https://doi.org/10.1/y")])],
                            second=[{"id": "c1", "relation": "background", "claims": [], "why": "general"}])
    assert pool.calls == [None, ["nemotron-super", "gemma"]], "one judgement, then an audit that excludes the first model"
    (rec,) = state.load("evidence_audit")["audits"]
    assert rec["models"] == ["nemotron-ultra", "nemotron-super"] and rec["grades"] == ["B", "none"]
    assert (rec["same"], rec["candidates"]) == (1, 2)  # c2 left out by both; c1 judged differently
    assert "same grade on 0%" in "\n".join(ev.audit_summary())


def test_audit_answered_by_the_same_model_is_not_recorded(write_page, monkeypatch, timeline):
    monkeypatch.setattr(ev, "AUDIT_SHARE", 1)
    judge_page(write_page, monkeypatch, timeline, [], [("OpenAlex", lambda q: [dict(B_PAPER)])],
               second_model="nemotron-ultra")
    assert state.load("evidence_audit") == {}


# --- the event itself is claim 1 (PR #4: archive files named after the event could only be
# background reading, so graded pages fell to none under JUDGE_VERSION 2) ---

class PromptJudge(SaysJudge):
    def generate_json(self, role, prompt, only=None, **k):
        self.prompt = prompt
        return super().generate_json(role, prompt, only=only, **k)


def test_the_event_itself_is_claim_1_so_a_record_of_it_can_grade_the_page(write_page, monkeypatch, timeline):
    write_page("p.md", "Signing of the Treaty", 1900, claims=())
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: [dict(A_RECORD)])])
    pool = PromptJudge([{"id": "c1", "relation": "supports", "claims": [1], "why": "file on the treaty"}])
    done = {}
    ev.evidence_batch(pool, done, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert "1. Signing of the Treaty occurred in 1900." in pool.prompt
    assert "no explicit claims" not in pool.prompt
    assert done == {"p.md": "A"}


def test_legacy_background_and_support_grades_are_rejudged_once(write_page, timeline):
    state.save("evidence_meta", {"judge_version": 2})
    write_page("bg.md", "Harbour survey", extra="\n## Evidence\n\n### Background reading (does not count towards coverage)\n\n- x\n")
    write_page("empty.md", "Plague", extra="\n## Evidence\n\nnothing relevant found yet\n")
    write_page("graded.md", "Treaty", extra="\n## Evidence\n\n### Background reading\n\n- x\n")
    done = {"bg.md": "none", "empty.md": "none", "graded.md": "B"}
    assert ev.reopen_for_rejudge(done) == 3
    assert done == {}
    done["bg.md"] = "none"
    done["graded.md"] = "B"
    assert ev.reopen_for_rejudge(done) == 0  # only once per JUDGE_VERSION


# --- P0 pipeline failure safety ---------------------------------------------------------------

def test_failed_required_task_is_not_marked_complete_and_run_is_recorded(monkeypatch):
    import seed_history as sh

    class Pool:
        state = {"resolved": {}}
        def summary(self):
            return "fake quota"

    plan = {
        "eras": {slug: {"outlined": False, "overview": False, "rounds": 0}
                 for slug, _, _ in sh.ERAS},
        "events": [],
        "entities": {},
    }
    saved = []
    failures = []
    monkeypatch.setattr(sh, "ModelPool", Pool)
    monkeypatch.setattr(sh, "load_plan", lambda: plan)
    monkeypatch.setattr(sh, "save_plan", lambda p: saved.append(dict(p)))
    monkeypatch.setattr(sh, "research_worker", lambda *a: 0)
    monkeypatch.setattr(sh, "photos_worker", lambda *a: 0)
    monkeypatch.setattr(sh, "verify_pages", lambda *a: 0)

    def fail_outline(*a, **k):
        raise RuntimeError("model response malformed")
    monkeypatch.setattr(sh, "outline", fail_outline)

    sh.run(max_calls=1, minutes=1, failures=failures)

    first_era = sh.ERAS[0][0]
    assert plan["eras"][first_era]["outlined"] is False
    assert plan["last_run"]["status"] == "partial_failure"
    assert plan["last_run"]["failures"][0]["stage"] == "outline"
    assert failures[0]["error"] == "RuntimeError: model response malformed"


def test_worker_crash_is_added_to_failure_record():
    import seed_history as sh

    results, failures = {}, []
    def crash():
        raise RuntimeError("source worker crashed")

    thread = sh.start_worker("research", crash, results, failures)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results["research"] == 0
    assert failures == [{"stage": "research", "error": "RuntimeError: source worker crashed"}]


def test_main_exits_nonzero_after_pipeline_failure(monkeypatch):
    import seed_history as sh

    monkeypatch.setattr(sh, "any_ai_key", lambda: True)
    monkeypatch.setattr(sh, "git_commit", lambda: None)

    def failed_run(*args, failures, **kwargs):
        failures.append({"stage": "research", "error": "RuntimeError: worker crashed"})
        return 0
    monkeypatch.setattr(sh, "run", failed_run)

    with pytest.raises(SystemExit) as exc:
        sh.main(["--no-commit"])
    assert exc.value.code == 1



def test_rejected_evidence_judgement_is_not_marked_done_and_fails_batch(write_page, monkeypatch, timeline):
    write_page("pending.md", "Example event", 1841)

    def reject(*args, **kwargs):
        raise ev.RequestRejected("provider rejected the request")

    monkeypatch.setattr(ev, "evidence_for_page", reject)
    done = {}
    with pytest.raises(RuntimeError, match="Evidence batch had .* blocking failure"):
        ev.evidence_batch(
            object(), done, [{"file": "pending.md", "status": "done"}],
            time.time() + 10, limit=1,
        )
    assert "pending.md" not in done


def test_incomplete_evidence_search_remains_pending_without_failing_batch(write_page, monkeypatch, timeline, capsys):
    write_page("pending.md", "Example event", 1841)
    monkeypatch.setattr(ev, "evidence_for_page", lambda *args, **kwargs: "retry")
    done = {}
    ev.evidence_batch(
        object(), done, [{"file": "pending.md", "status": "done"}],
        time.time() + 10, limit=1,
    )
    assert "pending.md" not in done
    assert "remain pending" in capsys.readouterr().out



def test_malformed_judge_response_fails_instead_of_recording_no_evidence(write_page, monkeypatch):
    write_page("pending.md", "Example event", 1841)
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: [dict(A_RECORD)])])

    class MalformedJudge:
        def generate_json(self, *args, **kwargs):
            return {"kept": []}, "test-model", []

    done = {}
    with pytest.raises(ValueError, match="Evidence judge returned an invalid response"):
        ev.evidence_batch(
            MalformedJudge(), done, [{"file": "pending.md", "status": "done"}],
            time.time() + 10, limit=1,
        )
    assert "pending.md" not in done


def test_metadata_only_candidate_cannot_support_claim_or_raise_grade(write_page, monkeypatch, timeline):
    metadata_only = dict(A_RECORD, passage="", passage_status="metadata_only")
    done, text, _ = judge_page(write_page, monkeypatch, timeline,
                               [{"id": "c1", "relation": "supports", "claims": [1], "why": "title looks relevant"}],
                               [("National Archives", lambda q: [metadata_only])])
    assert done == {"p.md": "none"}
    assert "evidence_grade: none" in text
    assert "### Background reading (does not count towards coverage)" in text
    assert "Source passage not inspected" in text


def test_judge_prompt_includes_inspectable_passage_and_status(write_page, monkeypatch, timeline):
    pool = PromptJudge([{"id": "c1", "relation": "supports", "claims": [1], "why": "passage states date"}])
    monkeypatch.setattr(ev, "SOURCES", [("National Archives", lambda q: [dict(A_RECORD)])])
    write_page("p.md", "Signing of the Treaty", 1849)
    ev.evidence_batch(pool, {}, [{"file": "p.md", "status": "done"}], time.time() + 60, limit=5)
    assert "passage_status: inspectable_record" in pool.prompt
    assert "The treaty was signed in Hong Kong in 1849." in pool.prompt



def test_internet_archive_text_requires_an_ocr_text_file(monkeypatch):
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {"files": [{"name": "book.pdf"}]})
    assert ev.internet_archive_text("sample-book") is None


def test_internet_archive_text_accepts_downloaded_ocr_text(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return ("This is inspected OCR text from the scanned historical publication. " * 12).encode()

    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {
        "files": [{"name": "sample-book_djvu.txt"}],
        "metadata": {"licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
    })
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=20: Response())
    text = ev.internet_archive_text("sample-book")
    assert text and len(text) >= 300
    assert "inspected OCR text" in text


def test_internet_archive_search_marks_only_downloaded_text_as_inspectable(monkeypatch):
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {
        "response": {"docs": [
            {"identifier": "with-ocr", "title": "Hong Kong report", "year": "1900"},
            {"identifier": "without-ocr", "title": "Hong Kong register", "year": "1901"},
        ]} if "advancedsearch.php" in url else {"files": []}
    })
    monkeypatch.setattr(ev, "internet_archive_text", lambda identifier: "Readable source passage " * 20 if identifier == "with-ocr" else None)
    results = ev.internet_archive("Hong Kong report")
    assert results[0]["passage_status"] == "inspectable_text"
    assert results[0]["kind"] == "digitised publication"
    assert results[0]["grade"] == "B"
    assert results[0]["passage"]
    assert results[1]["passage_status"] == "metadata_only"
    assert results[1]["passage"] == ""


def test_failed_atomic_evidence_write_preserves_previous_page(tmp_path, monkeypatch):
    page = tmp_path / "event.md"
    original = "---\ntitle: Example\nconfidence: ai-draft\n---\n\nOriginal body.\n"
    page.write_text(original, encoding="utf-8")

    def fail_write(*args, **kwargs):
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(ev, "atomic_write", fail_write)
    try:
        ev.write_evidence(str(page), "A", ["## Evidence", "New evidence"])
    except OSError:
        pass
    else:
        raise AssertionError("simulated write failure should propagate")

    assert page.read_text(encoding="utf-8") == original


def test_claim_search_queries_include_each_distinct_claim():
    queries = ev.claim_search_queries(
        "Treaty signing",
        ["Treaty signed in 1842", "Elliot issued a proclamation", "Treaty signing"],
    )
    assert queries[0] == "Treaty"
    assert any("1842" in query for query in queries)
    assert any("Elliot" in query for query in queries)
    assert len(queries) == 3


def test_claim_candidate_search_deduplicates_and_limits_results(monkeypatch):
    monkeypatch.setattr(ev, "reserve_openalex_search", lambda: True)
    monkeypatch.setattr(ev, "SOURCES", [("Archive", lambda q: []), ("Scholarship", lambda q: [])])

    def fake_gather(query, sources=None):
        return [
            {"source": "Archive", "url": f"https://archive.example/{query}", "title": query},
            {"source": "Archive", "url": "https://archive.example/shared", "title": "shared"},
            {"source": "Scholarship", "url": f"https://scholar.example/{query}", "title": query},
        ], []

    monkeypatch.setattr(ev, "gather", fake_gather)
    candidates, failed = ev.gather_claim_candidates(["title query", "claim one", "claim two"])
    assert failed == []
    assert len(candidates) == 7
    assert len({(c["source"], c["url"]) for c in candidates}) == len(candidates)
    assert any(c["url"] == "https://archive.example/claim two" for c in candidates)


def test_claim_search_uses_openalex_only_once_without_api_key(monkeypatch):
    monkeypatch.setattr(ev, "reserve_openalex_search", lambda: True)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(ev, "SOURCES", [("OpenAlex", lambda q: []), ("Archive", lambda q: [])])
    calls = []

    def fake_gather(query, sources=None):
        calls.append((query, [name for name, _ in sources]))
        return [], []

    monkeypatch.setattr(ev, "gather", fake_gather)
    ev.gather_claim_candidates(["event title", "first claim", "second claim"])
    assert "OpenAlex" in calls[0][1]
    assert all("OpenAlex" not in source_names for _, source_names in calls[1:])


def test_read_page_extracts_current_question_mark_claim_bullets(tmp_path):
    page = tmp_path / "event.md"
    page.write_text(
        '---\ntitle: "Test event"\nyear: 1841\n---\n'
        '## Claims to verify\n'
        '- ❔ The treaty was signed in 1841.\n'
        '- [ ] Elliot issued the proclamation.\n'
        '## Wikipedia cross-check\n'
        '- ✅ **agrees with Wikipedia**: a different reference claim.\n',
        encoding="utf-8",
    )
    _, title, date, claims = ev.read_page(str(page))
    assert title == "Test event"
    assert date == "1841"
    assert claims[:2] == [
        "The treaty was signed in 1841.",
        "Elliot issued the proclamation.",
    ]


def test_anonymous_openalex_budget_is_capped_at_ten_searches_per_utc_day(tmp_path, monkeypatch):
    import state
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(state, "STATE_DIR", str(tmp_path))
    assert all(ev.reserve_openalex_search() for _ in range(10))
    assert not ev.reserve_openalex_search()
    budget = state.load("source_budget")
    assert budget["openalex_searches"] == 10


def test_national_archives_adapter_accepts_documented_pascal_case_response(monkeypatch):
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {
        "Records": [{
            "Id": "A123",
            "Reference": "CO 129/1",
            "Title": "Hong Kong administrative dispatch",
            "Description": "Catalogue description only.",
            "CoveringDates": "1841-1842",
        }]
    })
    results = ev.national_archives("Hong Kong administration")
    assert len(results) == 1
    assert results[0]["url"].endswith("/details/r/A123")
    assert results[0]["catalogue_reference"] == "CO 129/1"
    assert results[0]["year"] == "1841-1842"
    assert results[0]["passage_status"] == "metadata_only"
    assert results[0]["passage"] == ""


def test_national_archives_adapter_keeps_lower_camel_case_compatibility(monkeypatch):
    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {
        "records": [{
            "id": "A456",
            "reference": "CO 129/2",
            "title": "Another archive entry",
            "coveringDates": "1842",
        }]
    })
    results = ev.national_archives("Hong Kong administration")
    assert len(results) == 1
    assert results[0]["url"].endswith("/details/r/A456")


def test_internet_archive_ocr_is_not_downloaded_without_explicit_open_rights(monkeypatch):
    def forbidden_download(*args, **kwargs):
        raise AssertionError("OCR download must not occur without an explicit rights signal")

    monkeypatch.setattr(ev, "_get_json", lambda url, accept_json=False: {
        "files": [{"name": "restricted-book_djvu.txt"}],
        "metadata": {},
    })
    monkeypatch.setattr(ev.urllib.request, "urlopen", forbidden_download)
    assert ev.internet_archive_text("restricted-book") is None


def test_internet_archive_rights_gate_rejects_explicit_non_public_domain_text():
    assert not ev.internet_archive_ai_processing_allowed({
        "metadata": {"rights": "This item is not in the public domain."}
    })
    assert ev.internet_archive_ai_processing_allowed({
        "metadata": {"rights": "Public domain"}
    })


def test_frontmatter_declared_chinese_title_and_aliases_join_claim_search():
    page = (
        '---\ntitle: "Treaty signing"\n'
        'title_zh: "條約簽署"\n'
        'aliases: ["Treaty of Nanking", "Nanking Treaty"]\n'
        '---\n'
    )
    aliases = ev.frontmatter_aliases(page)
    assert aliases == ["條約簽署", "Treaty of Nanking", "Nanking Treaty"]
    queries = ev.claim_search_queries("Treaty signing", ["The treaty was signed in 1842."], aliases)
    assert "條約簽署" in queries
    assert any("Treaty" in query and "Nanking" in query for query in queries)
    assert "Nanking Treaty" in queries
