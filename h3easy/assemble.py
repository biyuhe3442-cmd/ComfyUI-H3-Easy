"""Decode segments and join them into one video + soundtrack.

Video: a segment that the next one continues is decoded together with that
segment's first 5 *generated* latent slots, then trimmed back. ComfyUI's H3 VAE
decodes in 7-slot windows with a 5-slot stride, so without that right context
the 5 frames before each join would be decoded differently from a continuous
decode. Idea from MiniMax-H3-Flow-Aligned-Regenerate's "Continuum Decode
Context" (Apache-2.0, see THIRD_PARTY_NOTICES.md).

Audio: the audio latents of continued segments overlap exactly, so each run is
concatenated without the repeated prefixes and decoded once (no per-segment
loudness jumps). A segment that starts with a cut begins a new run.
"""

from __future__ import annotations

import math

import torch

from .timing import CONTEXT_AUDIO_TICKS, CONTEXT_SLOTS, DECODE_CONTEXT_SLOTS, FPS, Segment


def decode_plan(segments: list[Segment]) -> list[tuple[int, int, int]]:
    """(segment index, right-context slots appended, frames dropped at the start)."""
    plan = []
    for seg, following in zip(segments, segments[1:] + [None]):
        # a segment that starts with a cut has no prefix: nothing to drop, no context for the one before
        right = DECODE_CONTEXT_SLOTS if following is not None and following.prefix_frames else 0
        plan.append((seg.index, right, seg.prefix_frames))
    return plan


def _decode_video(vae, latent: torch.Tensor) -> torch.Tensor:
    images = vae.decode(latent)
    if images.ndim == 5:
        images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
    return images


def decode_video(vae, video_latents: list[torch.Tensor], segments: list[Segment],
                 on_segment=None) -> torch.Tensor:
    pieces = []
    for index, right, drop in decode_plan(segments):
        latent = video_latents[index]
        if right:
            nxt = video_latents[index + 1]
            context = nxt[:, :, CONTEXT_SLOTS:CONTEXT_SLOTS + right].to(latent)
            latent = torch.cat([latent, context], dim=2)
        frames = _decode_video(vae, latent)
        want = segments[index].frames
        if frames.shape[0] < want:
            raise RuntimeError(f"segment {index + 1} decoded {frames.shape[0]} frames, expected {want}")
        pieces.append(frames[drop:want].to("cpu", torch.float16))
        del frames
        if on_segment is not None:
            on_segment(index)
    video = torch.cat(pieces, dim=0)
    del pieces
    return video.float()


def chains(segments: list[Segment]) -> list[list[int]]:
    """Segment indices grouped into runs joined by continuation; a cut starts a new run."""
    runs: list[list[int]] = []
    for seg in segments:
        if seg.prefix_frames:
            runs[-1].append(seg.index)
        else:
            runs.append([seg.index])
    return runs


def join_audio_latents(audio_latents: list[torch.Tensor]) -> torch.Tensor:
    """One soundtrack latent for a run of continued segments."""
    parts = [audio_latents[0]] + [a[..., CONTEXT_AUDIO_TICKS:] for a in audio_latents[1:]]
    return torch.cat([p.to(parts[0]) for p in parts], dim=-1)


def fit_audio(audio: dict, seconds: float) -> dict:
    """Crop or zero-pad a ComfyUI AUDIO dict to an exact duration."""
    waveform = audio["waveform"]
    rate = int(audio["sample_rate"])
    want = int(round(seconds * rate))
    have = waveform.shape[-1]
    if have > want:
        waveform = waveform[..., :want]
    elif have < want:
        pad = torch.zeros(waveform.shape[:-1] + (want - have,), dtype=waveform.dtype, device=waveform.device)
        waveform = torch.cat([waveform, pad], dim=-1)
    return {"waveform": waveform.contiguous(), "sample_rate": rate}


def slice_audio(audio: dict, start_seconds: float, end_seconds: float) -> dict | None:
    """Cut [start, end) out of an AUDIO dict; None when the source has ended."""
    waveform = audio["waveform"]
    rate = int(audio["sample_rate"])
    a = int(math.floor(start_seconds * rate))
    b = int(math.ceil(end_seconds * rate))
    if a >= waveform.shape[-1] or b <= a:
        return None
    return {"waveform": waveform[..., a:b].contiguous(), "sample_rate": rate}


def total_seconds(segments: list[Segment]) -> float:
    return segments[-1].end_frame / FPS
