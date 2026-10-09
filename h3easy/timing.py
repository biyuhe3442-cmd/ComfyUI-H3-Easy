"""MiniMax H3 time grid: segment planning for multi-segment continuation.

H3 video lengths live on a 17k+5 frame grid at 24 fps; video latent slots carry
(1, 4, 4, 4, 4) frames; audio latents run at 40 Hz. Every segment here uses a
frame count that is also a multiple of 3, so its audio length (frames * 40/24)
is an integer and video/audio never drift apart across segments.

Continuation segments repeat the previous segment's last 39 frames
(12 latent slots, 65 audio ticks) as a protected prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

FPS = 24
AUDIO_FPS = 40
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)

CONTEXT_FRAMES = 39
CONTEXT_SLOTS = 12
CONTEXT_AUDIO_TICKS = 65

# 17k+5 and divisible by 3: 39, 90, 141, 192, ...
EXACT_AV_BASE = 39
EXACT_AV_STEP = 51
MIN_SEGMENT_FRAMES = 90
MAX_SEGMENT_FRAMES = 345  # H3's trained range is roughly 124-362 frames
MAX_SHOT_FRAMES = 362     # 17k+5 but not exact-AV: only for a shot with no continuation on either side
# right-context tokens appended when decoding a segment (see decode.py)
DECODE_CONTEXT_SLOTS = 5


def is_valid_frame_count(frames: int) -> bool:
    return frames >= 5 and frames % 17 == 5


def video_latent_t(frames: int) -> int:
    if not is_valid_frame_count(frames):
        raise ValueError(f"H3 frame count must be 17k+5, got {frames}")
    return 2 if frames <= 5 else ((frames - 5) // 17) * 5 + 2


def frames_for_slots(slots: int) -> int:
    return sum(FRAME_PER_TOKEN[i % len(FRAME_PER_TOKEN)] for i in range(slots))


def audio_ticks(frames: int) -> int:
    if (frames * AUDIO_FPS) % FPS:
        raise ValueError(f"{frames} frames do not land on the 40 Hz audio grid")
    return frames * AUDIO_FPS // FPS


def exact_av_frames_near(target: int, minimum: int = MIN_SEGMENT_FRAMES,
                         maximum: int = MAX_SEGMENT_FRAMES) -> int:
    """Nearest exact-AV frame count to ``target`` within [minimum, maximum]."""
    candidates = [f for f in range(EXACT_AV_BASE, maximum + 1, EXACT_AV_STEP) if f >= minimum]
    if not candidates:
        raise ValueError("no exact-AV frame count fits the requested range")
    # ties go to the longer segment
    return min(candidates, key=lambda f: (abs(f - target), -f))


@dataclass(frozen=True)
class Segment:
    index: int          # 0-based
    start_frame: int    # global timeline position of this segment's first frame
    frames: int         # total frames sampled, including the protected prefix
    prefix_frames: int  # 0 for the first segment, CONTEXT_FRAMES afterwards

    @property
    def new_frames(self) -> int:
        return self.frames - self.prefix_frames

    @property
    def video_t(self) -> int:
        return video_latent_t(self.frames)

    @property
    def audio_t(self) -> int:
        return audio_ticks(self.frames)

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames

    @property
    def new_window_seconds(self) -> tuple[float, float]:
        """Time span of the content this segment adds to the final video."""
        return (self.start_frame + self.prefix_frames) / FPS, self.end_frame / FPS

    @property
    def window_seconds(self) -> tuple[float, float]:
        return self.start_frame / FPS, self.end_frame / FPS


def _place(lengths: list[tuple[int, bool]]) -> list[Segment]:
    """Lay (frames, continues the one before) out on the global timeline."""
    segments: list[Segment] = []
    for index, (frames, continues) in enumerate(lengths):
        prefix = CONTEXT_FRAMES if continues else 0
        start = segments[-1].end_frame - prefix if segments else 0
        segments.append(Segment(index, start, frames, prefix))
    return segments


def plan_segments(count: int, seconds: float) -> list[Segment]:
    if count < 1:
        raise ValueError("at least one segment is required")
    requested = max(1, round(float(seconds) * FPS))
    first = exact_av_frames_near(requested)
    later = exact_av_frames_near(requested + CONTEXT_FRAMES)
    return _place([(first, False)] + [(later, True)] * (count - 1))


def frames_at_least(requested: int, exact_av: bool) -> int:
    """Shortest H3 length that covers ``requested`` frames (the longest one when none does).

    A shot on its own may use every 17k+5 length. Shots joined by continuation need the
    exact-AV grid, whose steps are 2 s apart, so there a length up to 3 frames short counts.
    """
    if exact_av:
        lengths, slack = range(MIN_SEGMENT_FRAMES, MAX_SEGMENT_FRAMES + 1, EXACT_AV_STEP), 3
    else:
        lengths, slack = range(MIN_SEGMENT_FRAMES, MAX_SHOT_FRAMES + 1, 17), 0
    return next((frames for frames in lengths if frames >= requested - slack), lengths[-1])


def plan_shots(shots: list[tuple[float, bool]]) -> list[Segment]:
    """Segments for shot cards given as (seconds of new video, continues the shot before)."""
    lengths = []
    for index, (seconds, continues) in enumerate(shots):
        chained = continues or (index + 1 < len(shots) and shots[index + 1][1])
        requested = round(float(seconds) * FPS) + (CONTEXT_FRAMES if continues else 0)
        lengths.append((frames_at_least(requested, chained), continues))
    return _place(lengths)


def total_frames(segments: list[Segment]) -> int:
    return segments[-1].end_frame


def unshift_sigma(sigma: float, shift: float) -> float:
    """Inverse of the flow shift sigma = s*t / (1 + (s-1)*t)."""
    return sigma / (shift - (shift - 1.0) * sigma)


def handoff_index(sigmas: list[float], shift: float, coordinate: float, min_high_steps: int = 2) -> int:
    """Schedule index where the low-resolution prefix hands over to full resolution.

    Picks the sigma whose unshifted time is closest to ``coordinate`` while leaving
    at least one low step and ``min_high_steps`` full-resolution steps.
    """
    last = len(sigmas) - 1 - min_high_steps
    if last < 1:
        raise ValueError("too few steps for progressive sampling")
    return min(range(1, last + 1), key=lambda i: abs(unshift_sigma(float(sigmas[i]), shift) - coordinate))
