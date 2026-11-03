import plan_queue as pq
import page_status as ps
from test_page_status import fake_execute


def setup(tmp_path, pages=("a-1842",)):
    (tmp_path / "content/05_Multi_AI").mkdir(parents=True)
    for p in pages:
        (tmp_path / f"content/05_Multi_AI/{p}.md").write_text(f"---\ntitle: Title of {p}\n---\ndrafts")
    return tmp_path


ANSWER = ("P | convention-of-chuenpi-1841 | Convention of Chuenpi | 1841 | Not covered yet.\n"
          "P | a-1842 | Duplicate | 1842 | Already a page.\n"
          "P | bad slug | Nope | 1900 | Bad.\n"
          "P | riots-1967 | Riots | 1967 | Valid.\n"
          "P | far-future-2999 | Future | 2999 | Out of range.\n"
          "chatter that is not a topic line")


def test_valid_new_topics_are_proposed_and_bad_lines_refused(tmp_path):
    root = setup(tmp_path)
    got = pq.plan(lambda s, p: ANSWER, "M", root)
    assert [g["slug"] for g in got] == ["convention-of-chuenpi-1841", "riots-1967"]
    queue = ps.load(root / pq.QUEUE, {})
    assert queue["proposals"][0]["status"] == "proposed" and queue["proposals"][0]["proposed_by"] == "M"


def test_no_call_while_enough_work_is_queued_or_proposals_wait(tmp_path, monkeypatch):
    root = setup(tmp_path, pages=("a-1842", "b-1860"))
    calls = []
    assert pq.plan(lambda s, p: calls.append(1) or ANSWER, "M", root) == [] and calls == []  # 2 open pages
    monkeypatch.setattr(pq, "MAX_OPEN", 1)
    root2 = setup(tmp_path / "x")
    ps.save(root2 / pq.QUEUE, {"proposals": [{"slug": "z-1900", "title": "Z", "status": "proposed"}]})
    assert pq.plan(lambda s, p: calls.append(1) or ANSWER, "M", root2) == [] and calls == []


def test_a_proposal_is_not_proposed_twice_and_a_finished_page_is_promoted(tmp_path, monkeypatch):
    root = setup(tmp_path)
    monkeypatch.setattr(ps, "execute", fake_execute([]))
    ps.run_page("a-1842", None, "M", root=root)  # nothing open, so planning may run
    pq.plan(lambda s, p: ANSWER, "M", root)
    assert pq.plan(lambda s, p: ANSWER, "M", root) == []  # the same topic is refused the second time
    (root / "content/05_Multi_AI/convention-of-chuenpi-1841.md").write_text("---\ntitle: C\n---\nx")
    ps.save(root / pq.QUEUE, dict(ps.load(root / pq.QUEUE, {}), pages=["a-1842"]))
    q = pq.promote(root, ps.load(root / pq.QUEUE, {}))
    assert "convention-of-chuenpi-1841" in q["pages"] and q["proposals"][0]["status"] == "page-exists"


def test_unavailable_writer_proposes_nothing(tmp_path):
    def call(s, p):
        raise pq.cp.WriterUnavailable("busy")
    assert pq.plan(call, "M", setup(tmp_path)) == []
