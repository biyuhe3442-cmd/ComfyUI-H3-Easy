"""Per-segment H3 conditioning built with ComfyUI Core's own MiniMax H3 nodes."""

from __future__ import annotations

import copy

import torch

from comfy_extras import nodes_minimax_h3 as core_h3

from .media import Media
from .timing import Segment


def _out(node_output):
    return node_output.args if hasattr(node_output, "args") else node_output


class ConditioningBuilder:
    def __init__(self, clip, video_vae, audio_vae, width: int, height: int, media: Media,
                 ref_image_size: str = "match"):
        self.clip = clip
        self.video_vae = video_vae
        self.audio_vae = audio_vae
        self.width = width
        self.height = height
        self.media = media
        self.ref_image_size = ref_image_size
        self._cache: dict = {}

    # ---- image / text mode (t2va, fl2va) ----
    def image_mode(self, prompt: str, segment: Segment, is_last: bool, guide_audio: dict | None):
        first = self.media.first_frame if segment.index == 0 else None
        last = self.media.last_frame if is_last else None
        key = ("image", prompt, segment.frames, first is not None, last is not None)
        if key not in self._cache:
            positive, latent = _out(core_h3.MiniMaxH3ImageToVideo.execute(
                clip=self.clip, vae=self.video_vae, prompt=prompt,
                width=self.width, height=self.height, length=segment.frames,
                first_frame=first, last_frame=last))
            self._cache[key] = (positive, latent)
        positive, latent = self._cache[key]
        if guide_audio is not None:
            positive = _out(core_h3.MiniMaxH3AddGuide.execute(
                positive=positive, latent=latent, frame_idx=0,
                audio_vae=self.audio_vae, audio=guide_audio))[0]
        return positive, latent

    # ---- reference mode (ref2va) ----
    def reference_mode(self, prompt: str, segment: Segment):
        key = ("reference", prompt, segment.frames)
        if key not in self._cache:
            media = self.media
            ref_images = {f"ref_image_{i + 1}": img for i, img in enumerate(media.ref_images)}
            ref_videos, ref_video_audios, ref_audios = {}, {}, {}
            if media.video is not None:
                ref_videos["ref_video_1"] = media.video
                if media.video_audio is not None:
                    ref_video_audios["ref_video_audio_1"] = media.video_audio
            if media.audio is not None:
                ref_audios["ref_audio_1"] = media.audio
            self._cache[key] = _out(core_h3.MiniMaxH3ReferenceToVideo.execute(
                clip=self.clip, prompt=prompt, width=self.width, height=self.height,
                length=segment.frames, ref_image_size=self.ref_image_size,
                vae=self.video_vae, audio_vae=self.audio_vae,
                ref_images=ref_images or None, ref_videos=ref_videos or None,
                ref_video_audios=ref_video_audios or None, ref_audios=ref_audios or None))
        return self._cache[key]

    # ---- low-resolution copy for the progressive prefix ----
    def rescale_keyframes(self, positive, width: int, height: int):
        """Same conditioning with keyframe image latents re-encoded at another size.

        Only the first segment is sampled progressively, so a keyframe at frame 0 is
        the first frame and any later one is the last frame.
        """
        out = []
        for tensor, meta in positive:
            meta = dict(meta)
            keyframes = meta.get("minimax_keyframes")
            if keyframes:
                rebuilt = []
                for kf in keyframes:
                    kf = dict(kf)
                    if kf.get("latent") is not None:
                        if kf.get("resolved_frame_index", 0) == 0 and self.media.first_frame is not None:
                            img = core_h3._resize(self.media.first_frame[:1], width, height, "disabled")
                        elif self.media.last_frame is not None:
                            img = core_h3._resize(self.media.last_frame[:1], width, height, "center")
                        else:
                            raise RuntimeError("cannot rebuild a keyframe without its source image")
                        kf["latent"] = self.video_vae.encode(img)
                    rebuilt.append(kf)
                meta["minimax_keyframes"] = rebuilt
            out.append([tensor, meta])
        return out


def empty_av_latent(width: int, height: int, frames: int):
    latent, _ = core_h3._empty_av_latent(width, height, frames)
    return latent["samples"]


def clone_conditioning(positive):
    return [[t, copy.copy(m)] for t, m in positive]


def to_cpu(tensor):
    return tensor.to("cpu") if isinstance(tensor, torch.Tensor) else tensor
