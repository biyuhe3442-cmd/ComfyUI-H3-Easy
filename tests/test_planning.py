import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3easy import timing  # noqa: E402
from h3easy.prompts import split_prompts  # noqa: E402


def test_exact_av_grid():
    for frames in range(39, 400, 51):
        assert timing.is_valid_frame_count(frames)
        assert frames % 3 == 0
        assert timing.audio_ticks(frames) * 3 == frames * 5
    assert timing.frames_for_slots(timing.CONTEXT_SLOTS) == timing.CONTEXT_FRAMES
    assert timing.audio_ticks(timing.CONTEXT_FRAMES) == timing.CONTEXT_AUDIO_TICKS


def test_latent_t_matches_frames():
    for frames in range(90, 400, 51):
        assert timing.frames_for_slots(timing.video_latent_t(frames)) == frames


@pytest.mark.parametrize("seconds,expected", [(3.5, 90), (5.0, 141), (6.0, 141), (7.0, 192), (14.0, 345)])
def test_first_segment_snapping(seconds, expected):
    assert timing.plan_segments(1, seconds)[0].frames == expected


def test_multi_segment_plan():
    segs = timing.plan_segments(3, 6.0)
    assert [s.frames for s in segs] == [141, 192, 192]
    assert [s.start_frame for s in segs] == [0, 102, 255]
    assert timing.total_frames(segs) == 447
    for prev, seg in zip(segs, segs[1:]):
        assert seg.start_frame == prev.end_frame - timing.CONTEXT_FRAMES
        # the protected tail starts on a latent cycle boundary
        assert (prev.video_t - timing.CONTEXT_SLOTS) % 5 == 0
        # next segment must have room for the decode right-context
        assert seg.video_t >= timing.CONTEXT_SLOTS + timing.DECODE_CONTEXT_SLOTS
    # audio ticks line up with frames everywhere on the global timeline
    for seg in segs:
        assert (seg.start_frame * 5) % 3 == 0


def test_handoff_index():
    shift = 12.0
    steps = 20
    ts = [1 - i / steps for i in range(steps + 1)]
    sigmas = [shift * t / (1 + (shift - 1) * t) for t in ts]
    k = timing.handoff_index(sigmas, shift, 0.35)
    assert k == 13
    assert abs(timing.unshift_sigma(sigmas[k], shift) - 0.35) < 1e-6
    assert 1 <= timing.handoff_index(sigmas[:5], shift, 0.05) <= len(sigmas[:5]) - 3


def test_prompts_timeline_with_shared_text():
    text = "电影感，真实光影\n[0-6s]\n她走进房间\n[6-10s]\n她坐下\n[10-14s]\n她看向窗外"
    windows = [s.new_window_seconds for s in timing.plan_segments(3, 4.0)]
    prompts, layout = split_prompts(text, windows)
    assert layout == "timeline"
    assert prompts[0] == "电影感，真实光影\n她走进房间"
    assert prompts[1].endswith("她坐下")
    assert prompts[2].endswith("她看向窗外")


def test_prompts_timeline_by_overlap_when_counts_differ():
    text = "[0-4s]\nA\n[4-8s]\nB\n[8-20s]\nC"
    windows = [s.new_window_seconds for s in timing.plan_segments(4, 6.0)]
    prompts, _ = split_prompts(text, windows)
    # windows: 0-5.875, 5.875-12.25, 12.25-18.625, 18.625-25
    assert prompts == ["A", "C", "C", "C"]


def test_prompts_timeline_chinese_range():
    prompts, layout = split_prompts("[0~5秒]\nA\n[5到10秒]\nB", [(0, 5.8), (5.8, 10)])
    assert layout == "timeline"
    assert prompts == ["A", "B"]


def test_prompts_list_and_fixed():
    prompts, layout = split_prompts("A\n---\nB", [(0, 1)] * 3)
    assert layout == "list"
    assert prompts == ["A", "B", "B"]
    prompts, layout = split_prompts("  same  ", [(0, 1)] * 2)
    assert layout == "fixed"
    assert prompts == ["same", "same"]
