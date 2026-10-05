"""Exact continuation through ComfyUI Core's native MiniMax H3 denoise masks.

The previous segment's last 39 frames (12 video latent slots) and, when the
generated soundtrack continues, its last 65 audio latent ticks are copied into
the start of the next segment's latent and marked 0 = keep. Core samples only
the rest. Same mechanism as H3 Continuum-Plus "Native Masked" continuation
(MIT, see THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import torch

import comfy.nested_tensor

from .timing import CONTEXT_AUDIO_TICKS, CONTEXT_SLOTS, FRAME_PER_TOKEN


def split_av(samples):
    if not getattr(samples, "is_nested", False):
        raise ValueError("expected a MiniMax H3 audio+video latent")
    video, audio = samples.unbind()[:2]
    if video.ndim != 5 or video.shape[1] != 24:
        raise ValueError(f"unexpected H3 video latent shape {tuple(video.shape)}")
    return video, audio


def join_av(video, audio):
    return comfy.nested_tensor.NestedTensor((video, audio))


def tail_context(samples) -> tuple[torch.Tensor, torch.Tensor]:
    """Last 39 frames of video and the matching 65 audio ticks of a finished segment."""
    video, audio = split_av(samples)
    start = video.shape[2] - CONTEXT_SLOTS
    if start < 0 or start % len(FRAME_PER_TOKEN):
        raise ValueError("segment tail does not start on an H3 latent cycle boundary")
    if audio.shape[-1] < CONTEXT_AUDIO_TICKS:
        raise ValueError("segment audio is shorter than the continuation context")
    return video[:, :, start:].clone(), audio[..., -CONTEXT_AUDIO_TICKS:].clone()


def apply_prefix(samples, video_context: torch.Tensor, audio_context: torch.Tensor | None):
    """Copy the protected prefix into a fresh target latent and build its noise mask.

    ``audio_context=None`` leaves the whole soundtrack generatable (used when the
    final audio comes from a locked source file).
    """
    video, audio = split_av(samples)
    video = video.clone()
    audio = audio.clone()
    if tuple(video.shape[-2:]) != tuple(video_context.shape[-2:]):
        raise ValueError("continuation context resolution differs from the new segment")
    if video.shape[2] <= CONTEXT_SLOTS:
        raise ValueError("segment has no room after the continuation prefix")
    video[:, :, :CONTEXT_SLOTS] = video_context.to(video)
    video_mask = torch.ones((1, 1) + tuple(video.shape[2:]), dtype=torch.float32, device=video.device)
    video_mask[:, :, :CONTEXT_SLOTS] = 0
    audio_mask = torch.ones((1, 1) + tuple(audio.shape[2:]), dtype=torch.float32, device=audio.device)
    if audio_context is not None:
        audio[..., :CONTEXT_AUDIO_TICKS] = audio_context.to(audio)
        audio_mask[..., :CONTEXT_AUDIO_TICKS] = 0
    return join_av(video, audio), join_av(video_mask, audio_mask)


def restore_prefix(samples, video_context: torch.Tensor, audio_context: torch.Tensor | None):
    """Overwrite the protected region with the exact source values after sampling."""
    video, audio = split_av(samples)
    video = video.clone()
    audio = audio.clone()
    video[:, :, :CONTEXT_SLOTS] = video_context.to(video)
    if audio_context is not None:
        audio[..., :CONTEXT_AUDIO_TICKS] = audio_context.to(audio)
    return join_av(video, audio)
