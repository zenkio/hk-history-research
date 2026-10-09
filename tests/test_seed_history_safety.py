import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_history as seed


def test_generated_event_page_is_explicitly_unverified_ai_hypothesis(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "TIMELINE_DIR", str(tmp_path))
    relative = seed.write_event_page(
        "05-opium-war",
        {"title": "Example Event", "year": 1841, "summary": "Planning summary"},
        {
            "title_zh": "示例事件",
            "summary": "A short summary.",
            "body": "## Background\n\nDraft body.",
            "claims_to_verify": ["The event occurred in 1841."],
            "tags": [],
        },
        "test-model",
    )
    page = (tmp_path / relative).read_text(encoding="utf-8")
    assert 'origin: ai' in page
    assert 'verification_status: unverified' in page
    assert 'confidence: ai-draft' in page
    assert '> [!warning] AI draft' in page
    assert 'Claims to verify' in page



def test_worker_timeout_is_recorded_as_partial_failure(monkeypatch):
    plan = {
        "eras": {slug: {"outlined": True, "overview": True, "rounds": seed.MAX_ROUNDS}
                 for slug, _, _ in seed.ERAS},
        "events": [],
        "entities": {},
    }
    class Pool:
        state = {"resolved": {}}
        def summary(self):
            return "fake quota"
    class StuckThread:
        def __init__(self, name):
            self.name = name
        def join(self, timeout=None):
            pass
        def is_alive(self):
            return True

    monkeypatch.setattr(seed, "ModelPool", Pool)
    monkeypatch.setattr(seed, "load_plan", lambda: plan)
    monkeypatch.setattr(seed, "save_plan", lambda p: None)
    monkeypatch.setattr(seed, "verify_pages", lambda *args: 0)
    monkeypatch.setattr(seed, "start_worker", lambda name, *args, **kwargs: StuckThread(name))
    failures = []

    seed.run(max_calls=0, minutes=0, failures=failures)

    assert {item["stage"] for item in failures} == {"research", "photos"}
    assert all("did not finish before shutdown deadline" in item["error"] for item in failures)
    assert plan["last_run"]["status"] == "partial_failure"


def test_failed_atomic_page_write_preserves_previous_page(tmp_path, monkeypatch):
    page = tmp_path / "existing.md"
    page.write_text("previous complete page\n", encoding="utf-8")

    def fail_write(*args, **kwargs):
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(seed.state, "atomic_write", fail_write)
    try:
        seed.write_page(page, {"title": '"Replacement"'}, ["replacement body"])
    except OSError:
        pass
    else:
        raise AssertionError("simulated write failure should propagate")

    assert page.read_text(encoding="utf-8") == "previous complete page\n"
