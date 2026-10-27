import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import quota_report as qr
from score_extraction_models import ROLE


class FakePool:
    def __init__(self):
        self.models = {"FAST": {"provider": "google", "rpm": 60}, "SLOW": {"provider": "openrouter", "rpm": 1},
                       "OUT": {"provider": "google", "rpm": 60}}
        self.routing = {ROLE: list(self.models)}
        self.gateway_quota = {}
        self.left = {"FAST": 1000, "SLOW": 1000, "OUT": 0}

    def remaining(self, name, role):
        return self.left[name]


def test_report_says_what_fits_what_is_too_slow_and_what_is_out():
    lines = {line.split(" | ")[0]: line for line in qr.report(FakePool())}
    assert "score" in lines["FAST"].split("fits: ")[1] and "too slow" not in lines["FAST"]
    assert "document" in lines["SLOW"].split("fits: ")[1] and "too slow for: " in lines["SLOW"] and "score" in lines["SLOW"].split("too slow for: ")[1]
    assert "0 calls left today" in lines["OUT"] and "fits: nothing" in lines["OUT"]
