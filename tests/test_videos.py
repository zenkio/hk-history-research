"""YouTube: subtitles first, AI viewing to compare or as fallback."""
import pytest
import process_ingestion as pi
import state
import videos as yt


class Pool:
    def __init__(self, video_left=5):
        self.video_left, self.calls = video_left, []

    def total_remaining(self, role):
        return self.video_left

    def generate_json(self, role, prompt, media=None, **k):
        self.calls.append(role)
        if role == "video_text":
            assert "[00:31]" in prompt, "subtitles must reach the model with time markers"
            return {"summary": "Tung Wah founded 1870.", "key_points": [{"time": "00:31", "point": "Founded"}]}, "Flash Lite", []
        if "summarised it from its subtitles" in prompt:
            return {"subtitles_enough": False, "why": "Shows the ordinance.",
                    "visual_only": [{"time": "01:05", "what": "Ordinance No. 3 of 1870 on screen"}]}, "Flash Lite", []
        return {"summary": "Watched.", "key_points": []}, "Flash Lite", []


SUBS = {"kind": "channel", "lang": "zh-HK", "segments": [(0.0, "Tung Wah"), (31.0, "founded 1870"), (65.0, "ordinance")]}


def test_subtitles_first_then_compare(monkeypatch):
    monkeypatch.setattr(yt, "fetch_transcript", lambda vid: SUBS)
    pool = Pool()
    (v,) = pi.summarize_videos(pool, ["A"], "Tung Wah")
    assert pool.calls == ["video_text", "video"]
    md = "\n".join(pi.video_section([v]))
    assert "own subtitles (channel, zh-HK)" in md
    assert "What the video shows beyond its words" in md and "youtu.be/A?t=65" in md
    assert state.load("videos")["A"]["subtitles_enough"] is False


def test_no_video_quota_means_no_comparison(monkeypatch):
    monkeypatch.setattr(yt, "fetch_transcript", lambda vid: SUBS)
    pool = Pool(video_left=0)
    (v,) = pi.summarize_videos(pool, ["A"], "T")
    assert pool.calls == ["video_text"] and "compare" not in v


def test_blocked_subtitles_fall_back_to_watching(monkeypatch):
    monkeypatch.setattr(yt, "fetch_transcript", lambda vid: {"error": "IpBlocked"})
    pool = Pool()
    (v,) = pi.summarize_videos(pool, ["B"], "T")
    assert pool.calls == ["video"] and v["source"] == "watched"
    assert "from watching the video" in "\n".join(pi.video_section([v]))
    assert state.load("videos")["B"]["subtitles_error"] == "IpBlocked"


def test_first_block_stops_further_subtitle_requests(monkeypatch):
    import sys, types
    tries = []

    class Api:
        def list(self, vid):
            tries.append(vid)
            raise type("IpBlocked", (Exception,), {})()
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", types.SimpleNamespace(YouTubeTranscriptApi=Api))
    monkeypatch.setattr(yt, "_blocked", False)
    assert yt.fetch_transcript("a") == {"error": "IpBlocked"}
    assert yt.fetch_transcript("b") == {"error": "blocked earlier in this run"}
    assert tries == ["a"]


def test_transcript_markers():
    assert yt.transcript_text([(0, "a"), (12, "b"), (31, "c"), (95, "d")]) == "[00:00] a b\n[00:31] c\n[01:35] d"
