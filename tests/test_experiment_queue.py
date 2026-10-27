import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import experiment_queue as eq
from score_extraction_models import ROLE

JOB = {"id": "yearbook-1", "mode": "document", "models": "A, B", "approved_by": "Zenkio", "approved_on": "2026-10-27"}


class FakePool:
    def __init__(self, left=1000):
        self.models = {"A": {"provider": "google", "rpm": 60}, "B": {"provider": "google", "rpm": 60}}
        self.routing = {ROLE: ["A", "B"]}
        self.gateway_quota = {}
        self.left = left

    def remaining(self, name, role):
        return self.left


def test_only_approved_pending_jobs_are_picked():
    unapproved = {"id": "x", "mode": "document", "models": "A"}
    done = dict(JOB, id="old", status="dispatched")
    bad_mode = dict(JOB, id="bad", mode="nonsense")
    assert eq.next_job({"jobs": [unapproved, done, bad_mode]}) is None
    assert eq.next_job({"jobs": [unapproved, done, bad_mode, JOB]})["id"] == "yearbook-1"


def test_a_busy_experiment_or_missing_quota_starts_nothing():
    queue = {"jobs": [JOB]}
    assert eq.decide(queue, FakePool(), busy=True)[0] is None
    job, reason = eq.decide(queue, FakePool(left=1), busy=False)
    assert job is None and "calls left today" in reason
    assert eq.decide(queue, FakePool(), busy=False)[0]["id"] == "yearbook-1"


def test_extract_and_verify_check_only_the_first_model():
    assert eq.models_of(dict(JOB, mode="extract")) == ["A"]
    assert eq.models_of(JOB) == ["A", "B"]


def test_marking_runs_a_job_once():
    queue = {"jobs": [JOB]}
    assert eq.mark(queue, "yearbook-1") and eq.next_job(queue) is None
    assert not eq.mark(queue, "missing")


def test_missing_queue_file_is_an_empty_queue(tmp_path):
    assert eq.load(str(tmp_path / "none.json")) == {"jobs": []}
